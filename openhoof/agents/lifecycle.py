"""Agent lifecycle management."""

import asyncio
import json
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
import logging
import yaml

from ..core.workspace import load_workspace, build_bootstrap_context, AgentWorkspace
from ..core.sessions import SessionStore, SessionEntry
from ..core.transcripts import TranscriptStore, Message
from ..core.events import (
    event_bus,
    EVENT_AGENT_STARTED,
    EVENT_AGENT_STOPPED,
    EVENT_AGENT_MESSAGE,
    EVENT_AGENT_THINKING,
    EVENT_AGENT_TOOL_CALL,
    EVENT_AGENT_TOOL_RESULT,
    EVENT_SUBAGENT_SPAWNED,
    EVENT_SUBAGENT_COMPLETED,
)
from ..inference import InferenceAdapter, ChatResponse
from ..tools import ToolRegistry, ToolContext
from ..tools.builtin import register_builtin_tools
from ..tools.builtin.spawn import SpawnAgentTool
from .heartbeat import HeartbeatRunner, HeartbeatConfig
from .autonomy_loop import AutonomyLoop
from .subagents import SubagentRegistry
from ..core.hot_state import HotState, HotStateFieldConfig as HSFieldConfig
from ..core.sensors import Sensor, sensor_factory

logger = logging.getLogger(__name__)

# Max messages before auto-compaction
MAX_CONTEXT_MESSAGES = 30
COMPACT_KEEP_LAST = 10


@dataclass
class ActiveHoursConfig:
    """Configuration for active hours."""
    start: str = "08:00"  # HH:MM
    end: str = "23:00"    # HH:MM


@dataclass
class AutonomyConfig:
    """Configuration for autonomous agent loop."""
    enabled: bool = False
    max_consecutive_turns: int = 50
    token_budget_per_hour: int = 100000
    max_actions_per_minute: int = 10
    idle_timeout: int = 600  # seconds
    active_hours: Optional[ActiveHoursConfig] = None
    precheck_model: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AutonomyConfig":
        """Parse from a dict (YAML section)."""
        active_hours = None
        if "active_hours" in data:
            ah = data["active_hours"]
            active_hours = ActiveHoursConfig(
                start=ah.get("start", "08:00"),
                end=ah.get("end", "23:00"),
            )
        return cls(
            enabled=data.get("enabled", False),
            max_consecutive_turns=data.get("max_consecutive_turns", 50),
            token_budget_per_hour=data.get("token_budget_per_hour", 100000),
            max_actions_per_minute=data.get("max_actions_per_minute", 10),
            idle_timeout=data.get("idle_timeout", 600),
            active_hours=active_hours,
            precheck_model=data.get("precheck_model"),
        )


@dataclass
class HotStateFieldConfig:
    """Configuration for a single hot state field."""
    type: str = "object"  # "object", "number", "string", "array", "boolean"
    ttl: Optional[int] = None  # seconds, None means never stale
    refresh_tool: Optional[str] = None
    max_items: Optional[int] = None  # for array types only

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HotStateFieldConfig":
        """Parse from a dict."""
        return cls(
            type=data.get("type", "object"),
            ttl=data.get("ttl"),
            refresh_tool=data.get("refresh_tool"),
            max_items=data.get("max_items"),
        )


@dataclass
class HotStateConfig:
    """Configuration for agent hot state."""
    fields: Dict[str, HotStateFieldConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HotStateConfig":
        """Parse from a dict (YAML section)."""
        fields = {}
        for name, field_data in data.get("fields", {}).items():
            fields[name] = HotStateFieldConfig.from_dict(field_data)
        return cls(fields=fields)


@dataclass
class SensorSignalConfig:
    """Configuration for an ML signal on a sensor."""
    name: str
    model: str
    prompt: str
    threshold: float = 0.8
    notify: bool = True
    cooldown: Optional[int] = None  # seconds


@dataclass
class SensorSourceConfig:
    """Configuration for a sensor data source."""
    tool: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    url: Optional[str] = None
    path: Optional[str] = None


@dataclass
class SensorUpdateConfig:
    """Configuration for a sensor hot state update mapping."""
    field: str


@dataclass
class SensorConfig:
    """Configuration for a sensor."""
    name: str
    type: str  # "poll", "watch", "stream"
    interval: Optional[int] = None  # seconds, for poll type
    source: SensorSourceConfig = field(default_factory=SensorSourceConfig)
    updates: List[SensorUpdateConfig] = field(default_factory=list)
    signals: List[SensorSignalConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SensorConfig":
        """Parse from a dict (YAML list item)."""
        source_data = data.get("source", {})
        source = SensorSourceConfig(
            tool=source_data.get("tool"),
            params=source_data.get("params", {}),
            url=source_data.get("url"),
            path=source_data.get("path"),
        )
        updates = [
            SensorUpdateConfig(field=u["field"])
            for u in data.get("updates", [])
        ]
        signals = [
            SensorSignalConfig(
                name=s["name"],
                model=s["model"],
                prompt=s["prompt"],
                threshold=s.get("threshold", 0.8),
                notify=s.get("notify", True),
                cooldown=s.get("cooldown"),
            )
            for s in data.get("signals", [])
        ]
        return cls(
            name=data["name"],
            type=data["type"],
            interval=data.get("interval"),
            source=source,
            updates=updates,
            signals=signals,
        )


@dataclass
class AgentConfig:
    """Configuration for an agent."""
    agent_id: str
    name: str
    description: str = ""
    model: Optional[str] = None
    thinking: Optional[str] = None  # "low", "medium", "high"
    heartbeat_enabled: bool = True
    heartbeat_interval: int = 1800
    tools: List[str] = field(default_factory=list)  # List of allowed tool names
    max_tool_rounds: int = 5  # Max consecutive tool-call rounds before forcing a response
    autonomy: Optional[AutonomyConfig] = None
    hot_state: Optional[HotStateConfig] = None
    sensors: List[SensorConfig] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> "AgentConfig":
        """Load config from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        # Parse autonomy config
        autonomy = None
        if "autonomy" in data:
            autonomy = AutonomyConfig.from_dict(data["autonomy"])

        # Parse hot state config
        hot_state = None
        if "hot_state" in data:
            hot_state = HotStateConfig.from_dict(data["hot_state"])

        # Parse sensor configs
        sensors = []
        for sensor_data in data.get("sensors", []):
            try:
                sensors.append(SensorConfig.from_dict(sensor_data))
            except (KeyError, TypeError) as e:
                logger.error(f"Invalid sensor config: {e}")

        return cls(
            agent_id=data.get("id", path.parent.name),
            name=data.get("name", path.parent.name),
            description=data.get("description", ""),
            model=data.get("model"),
            thinking=data.get("thinking"),
            heartbeat_enabled=data.get("heartbeat", {}).get("enabled", True),
            heartbeat_interval=data.get("heartbeat", {}).get("interval", 1800),
            tools=data.get("tools", []),
            max_tool_rounds=data.get("max_tool_rounds", 5),
            autonomy=autonomy,
            hot_state=hot_state,
            sensors=sensors,
        )


@dataclass
class AgentHandle:
    """Handle to a running agent."""
    agent_id: str
    config: AgentConfig
    workspace: AgentWorkspace
    session: SessionEntry
    heartbeat: Optional[HeartbeatRunner] = None
    autonomy_loop: Optional[AutonomyLoop] = None
    hot_state: Optional[HotState] = None
    sensors: List[Sensor] = field(default_factory=list)
    status: str = "running"


class AgentManager:
    """Manages agent lifecycle and execution."""

    def __init__(
        self,
        agents_dir: Path,
        data_dir: Path,
        inference: InferenceAdapter,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        self.agents_dir = agents_dir
        self.data_dir = data_dir
        self.inference = inference

        # Initialize stores
        self.session_store = SessionStore(data_dir / "sessions.json")
        self.transcript_store = TranscriptStore(data_dir / "transcripts")

        # Tool registry
        self.tool_registry = tool_registry or ToolRegistry()
        if not tool_registry:
            register_builtin_tools(self.tool_registry, agent_manager=self)

        # Wire up spawn tool callback
        spawn_tool = self.tool_registry.get("spawn_agent")
        if spawn_tool and isinstance(spawn_tool, SpawnAgentTool):
            spawn_tool.spawn_callback = self._handle_spawn_request

        # Sub-agent registry
        self.subagent_registry = SubagentRegistry(
            store_path=data_dir / "subagent_runs.json",
            run_agent=self._run_subagent,
            default_timeout_seconds=300,
        )

        # Provision default agents (e.g., agent-builder) if not already present
        self._provision_defaults()

        # Running agents
        self._agents: Dict[str, AgentHandle] = {}

    def _provision_defaults(self) -> None:
        """Provision default agent workspaces if they don't exist."""
        defaults_dir = Path(__file__).parent / "defaults"
        if not defaults_dir.exists():
            return

        for default_agent_dir in defaults_dir.iterdir():
            if not default_agent_dir.is_dir():
                continue
            target = self.agents_dir / default_agent_dir.name
            if not target.exists():
                shutil.copytree(default_agent_dir, target)
                logger.info(f"Provisioned default agent: {default_agent_dir.name}")

    async def _handle_spawn_request(
        self,
        requester_session_key: str,
        agent_id: str,
        task: str,
        label: Optional[str] = None,
        timeout_seconds: int = 300,
    ) -> Dict[str, Any]:
        """Handle a spawn request from the SpawnAgentTool."""
        run = await self.subagent_registry.spawn(
            requester_session_key=requester_session_key,
            agent_id=agent_id,
            task=task,
            label=label,
            timeout_seconds=timeout_seconds,
        )

        # Emit event
        await event_bus.emit(EVENT_SUBAGENT_SPAWNED, {
            "agent_id": agent_id,
            "run_id": run.run_id,
            "task": task[:200],
            "requester": requester_session_key,
        })

        return {
            "run_id": run.run_id,
            "agent_id": agent_id,
            "child_session_key": run.child_session_key,
        }

    async def _run_subagent(
        self, agent_id: str, session_key: str, task: str
    ) -> str:
        """Run a sub-agent (called by SubagentRegistry)."""
        # Auto-start agent if not running
        if agent_id not in self._agents:
            try:
                await self.start_agent(agent_id)
            except ValueError:
                # Agent workspace doesn't exist — create an ephemeral one
                await self._create_ephemeral_agent(agent_id)
                await self.start_agent(agent_id)

        handle = self._agents[agent_id]

        # Build enriched task with context
        parent_session_key = session_key.replace(f"subagent:{agent_id}:", "")
        enriched_task = self._build_subagent_prompt(handle, task, parent_session_key)

        result = await self._run_agent_turn(agent_id, session_key, enriched_task)

        # Emit completion
        await event_bus.emit(EVENT_SUBAGENT_COMPLETED, {
            "agent_id": agent_id,
            "session_key": session_key,
            "success": True,
            "response_preview": result[:300],
        })

        return result

    def _build_subagent_prompt(
        self, handle: AgentHandle, task: str, parent_session_key: str
    ) -> str:
        """Build an enriched prompt for a sub-agent with purpose, tools, and expectations."""
        # Get the tools this agent has
        tool_names = handle.config.tools or [t.name for t in self.tool_registry.list_tools()]
        tool_descriptions = []
        for name in tool_names:
            tool = self.tool_registry.get(name)
            if tool:
                tool_descriptions.append(f"- **{tool.name}**: {tool.description.strip().split(chr(10))[0]}")

        tools_text = "\n".join(tool_descriptions) if tool_descriptions else "All standard tools available."

        return f"""## Sub-Agent Task Assignment

You have been spawned as a sub-agent to handle a specific task.

### Your Task
{task}

### Tools Available to You
{tools_text}

### Important Instructions
1. Focus exclusively on the task above
2. Use `shared_write` to save any findings for other agents to access
3. Use `memory_write` to log your work in your daily memory
4. Be thorough but concise in your response
5. End with a clear **Summary** section of what you found/accomplished

### Report Format
When done, provide:
- **Findings**: What you discovered
- **Actions Taken**: What tools you used and results
- **Recommendations**: Next steps if any
- **Summary**: One-paragraph synopsis"""

    async def _create_ephemeral_agent(self, agent_id: str):
        """Create a minimal agent workspace for an ephemeral sub-agent."""
        workspace_dir = self.agents_dir / agent_id
        workspace_dir.mkdir(parents=True, exist_ok=True)
        (workspace_dir / "memory").mkdir(exist_ok=True)

        soul_content = f"""# {agent_id}

You are a specialist sub-agent in the OpenHoof system.
Your ID is `{agent_id}`.

You are spawned on-demand to handle specific tasks.
Be thorough, use your tools, and report back clearly."""

        (workspace_dir / "SOUL.md").write_text(soul_content)
        logger.info(f"Created ephemeral agent workspace: {agent_id}")

    async def list_agents(self) -> List[Dict[str, Any]]:
        """List all available agents."""
        agents = []

        if not self.agents_dir.exists():
            return agents

        for agent_dir in self.agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue

            config_path = agent_dir / "agent.yaml"
            if config_path.exists():
                config = AgentConfig.from_yaml(config_path)
            else:
                config = AgentConfig(
                    agent_id=agent_dir.name,
                    name=agent_dir.name
                )

            # Get tool info
            tool_names = config.tools or [t.name for t in self.tool_registry.list_tools()]

            agents.append({
                "agent_id": config.agent_id,
                "name": config.name,
                "description": config.description,
                "status": "running" if config.agent_id in self._agents else "stopped",
                "workspace_dir": str(agent_dir),
                "tools": tool_names,
                "model": config.model,
            })

        return agents

    async def get_agent(self, agent_id: str) -> Optional[AgentHandle]:
        """Get a running agent handle."""
        return self._agents.get(agent_id)

    async def start_agent(self, agent_id: str) -> AgentHandle:
        """Start an agent."""
        if agent_id in self._agents:
            return self._agents[agent_id]

        # Load workspace
        workspace_dir = self.agents_dir / agent_id
        if not workspace_dir.exists():
            raise ValueError(f"Agent workspace not found: {agent_id}")

        workspace = await load_workspace(workspace_dir)

        # Load config
        config_path = workspace_dir / "agent.yaml"
        if config_path.exists():
            config = AgentConfig.from_yaml(config_path)
        else:
            config = AgentConfig(agent_id=agent_id, name=agent_id)

        # Create or get session
        session_key = f"agent:{agent_id}:main"
        session = self.session_store.get_or_create(session_key, agent_id=agent_id)

        # Setup heartbeat
        heartbeat = None
        if config.heartbeat_enabled:
            heartbeat = HeartbeatRunner(
                agent_id=agent_id,
                workspace_dir=workspace_dir,
                config=HeartbeatConfig(
                    enabled=True,
                    every_seconds=config.heartbeat_interval
                ),
                run_callback=self._run_heartbeat_turn
            )
            heartbeat.start()

        # Setup autonomy (hot state, sensors, loop)
        hot_state_obj = None
        sensors_list: List[Sensor] = []
        autonomy_loop = None

        if config.autonomy and config.autonomy.enabled:
            # Create hot state
            if config.hot_state:
                field_configs = {
                    name: HSFieldConfig(
                        type=fc.type,
                        ttl=fc.ttl,
                        refresh_tool=fc.refresh_tool,
                        max_items=fc.max_items,
                    )
                    for name, fc in config.hot_state.fields.items()
                }
                hot_state_obj = HotState(field_configs)
            else:
                hot_state_obj = HotState({})

            # Create sensors
            for sensor_cfg in config.sensors:
                sensor = sensor_factory(
                    config=sensor_cfg,
                    agent_id=agent_id,
                    hot_state=hot_state_obj,
                    tool_registry=self.tool_registry,
                    inference=self.inference,
                )
                if sensor:
                    sensors_list.append(sensor)

            # Create autonomy loop
            autonomy_loop = AutonomyLoop(
                agent_id=agent_id,
                run_agent_turn=self._run_agent_turn,
                hot_state=hot_state_obj,
                sensors=sensors_list,
                tool_registry=self.tool_registry,
                inference=self.inference,
                config=config.autonomy,
            )

        # Create handle
        handle = AgentHandle(
            agent_id=agent_id,
            config=config,
            workspace=workspace,
            session=session,
            heartbeat=heartbeat,
            autonomy_loop=autonomy_loop,
            hot_state=hot_state_obj,
            sensors=sensors_list,
            status="running"
        )

        self._agents[agent_id] = handle

        # Start autonomy loop after handle is registered
        if autonomy_loop:
            autonomy_loop.start()
            logger.info(f"Autonomy loop started for agent: {agent_id}")

        # Emit event
        await event_bus.emit(EVENT_AGENT_STARTED, {
            "agent_id": agent_id,
            "name": config.name,
            "session_key": session_key,
            "tools": config.tools or [t.name for t in self.tool_registry.list_tools()],
            "autonomy_enabled": config.autonomy.enabled if config.autonomy else False,
        })

        logger.info(f"Started agent: {agent_id}")
        return handle

    async def stop_agent(self, agent_id: str) -> bool:
        """Stop an agent."""
        handle = self._agents.get(agent_id)
        if not handle:
            return False

        # Stop autonomy loop (which also stops sensors)
        if handle.autonomy_loop:
            handle.autonomy_loop.stop()

        # Stop heartbeat
        if handle.heartbeat:
            handle.heartbeat.stop()

        handle.status = "stopped"
        del self._agents[agent_id]

        # Emit event
        await event_bus.emit(EVENT_AGENT_STOPPED, {"agent_id": agent_id})

        logger.info(f"Stopped agent: {agent_id}")
        return True

    async def update_agent_tools(self, agent_id: str, tools: List[str]) -> bool:
        """Update an agent's tool list."""
        handle = self._agents.get(agent_id)
        if handle:
            handle.config.tools = tools

        # Also update the YAML config on disk
        config_path = self.agents_dir / agent_id / "agent.yaml"
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            data["tools"] = tools
            with open(config_path, "w") as f:
                yaml.dump(data, f)
        return True

    async def chat(
        self,
        agent_id: str,
        message: str,
        session_key: Optional[str] = None
    ) -> str:
        """Send a message to an agent and get a response."""
        handle = self._agents.get(agent_id)
        if not handle:
            # Auto-start if not running
            handle = await self.start_agent(agent_id)

        session_key = session_key or f"agent:{agent_id}:main"
        return await self._run_agent_turn(agent_id, session_key, message)

    async def _auto_compact_if_needed(self, session_id: str, agent_id: str):
        """Auto-compact transcript if it's getting too long."""
        transcript = self.transcript_store.load(session_id)
        if not transcript:
            return

        non_system = [m for m in transcript.messages if m.role != "system"]
        if len(non_system) <= MAX_CONTEXT_MESSAGES:
            return

        # Generate a summary of the older messages using the fast model
        old_messages = non_system[:-COMPACT_KEEP_LAST]
        summary_text = "Previous conversation:\n"
        for m in old_messages[-20:]:  # Summarize last 20 of the old messages
            summary_text += f"- [{m.role}]: {m.content[:150]}\n"

        try:
            summary_response = await self.inference.chat_completion(
                messages=[
                    {"role": "system", "content": "Summarize this conversation concisely, preserving key facts, decisions, and context."},
                    {"role": "user", "content": summary_text}
                ],
                model="qwen3-1.7b",  # Use the fast model
                stateless=True,
                rag_enabled=False,
            )
            summary = summary_response.content
        except Exception as e:
            logger.warning(f"Auto-compaction summary failed: {e}")
            # Fallback: just truncate without summary
            summary = f"[{len(old_messages)} earlier messages compacted]"

        self.transcript_store.compact(session_id, keep_last=COMPACT_KEEP_LAST, summary=summary)
        logger.info(f"Auto-compacted transcript {session_id}: {len(old_messages)} messages → summary")

    async def _run_agent_turn(
        self,
        agent_id: str,
        session_key: str,
        message: str
    ) -> str:
        """Execute a single agent turn (message → response)."""
        handle = self._agents.get(agent_id)
        if not handle:
            raise ValueError(f"Agent not running: {agent_id}")

        # Reload workspace (might have changed)
        workspace = await load_workspace(handle.workspace.dir)

        # Build system prompt from workspace
        system_prompt = build_bootstrap_context(workspace)

        # Build tools description for the system prompt
        tool_names = handle.config.tools or None
        tools = self.tool_registry.get_openai_schemas(tool_names)
        if tools:
            tool_summary = "\n\n## Available Tools\nYou have the following tools available:\n"
            for t in tools:
                func = t.get("function", {})
                tool_summary += f"- **{func['name']}**: {func.get('description', '').split(chr(10))[0]}\n"
            tool_summary += "\nUse tools via function calling when they can help accomplish the task."
            system_prompt += tool_summary

        # Get conversation history
        session = self.session_store.get_or_create(session_key, agent_id=agent_id)

        # Auto-compact if needed BEFORE loading context
        await self._auto_compact_if_needed(session.session_id, agent_id)

        history = self.transcript_store.get_messages_for_context(session.session_id)

        # Build messages
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend([m.to_openai_format() for m in history])
        messages.append({"role": "user", "content": message})

        # Call inference with tool calling loop
        tool_round = 0
        response = await self.inference.chat_completion(
            messages=messages,
            tools=tools if tools else None,
            model=handle.config.model,
            think=handle.config.thinking is not None,
            thinking_budget=512 if handle.config.thinking else None,
            rag_enabled=False,
            stateless=True,
        )

        # Emit thinking event if present
        if response.thinking:
            await event_bus.emit(EVENT_AGENT_THINKING, {
                "agent_id": agent_id,
                "session_key": session_key,
                "thinking": response.thinking[:500],
            })

        # Tool calling loop (OpenAI format only — no XML parsing)
        while response.has_tool_calls() and tool_round < handle.config.max_tool_rounds:
            tool_round += 1
            tool_messages = []

            for tc in response.tool_calls:
                # Emit tool call event
                await event_bus.emit(EVENT_AGENT_TOOL_CALL, {
                    "agent_id": agent_id,
                    "session_key": session_key,
                    "tool_name": tc.name,
                    "tool_arguments": tc.arguments,
                    "round": tool_round,
                })

                context = ToolContext(
                    agent_id=agent_id,
                    session_key=session_key,
                    workspace_dir=str(handle.workspace.dir)
                )
                result = await self.tool_registry.execute(tc.name, tc.arguments, context)

                # Emit tool result event
                await event_bus.emit(EVENT_AGENT_TOOL_RESULT, {
                    "agent_id": agent_id,
                    "session_key": session_key,
                    "tool_name": tc.name,
                    "success": result.success,
                    "result_preview": str(result.to_content())[:200],
                    "round": tool_round,
                })

                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.to_content()
                })

            # Add assistant message with tool calls + results
            assistant_msg = {
                "role": "assistant",
                "content": response.content or "",
            }
            if response.tool_calls:
                assistant_msg["tool_calls"] = [tc.to_openai_format() for tc in response.tool_calls]

            messages.append(assistant_msg)
            messages.extend(tool_messages)

            # Get next response
            response = await self.inference.chat_completion(
                messages=messages,
                tools=tools if tools else None,
                model=handle.config.model,
                rag_enabled=False,
                stateless=True,
            )

        final_content = response.content or ""

        if tool_round >= handle.config.max_tool_rounds and response.has_tool_calls():
            final_content += "\n\n[Max tool rounds reached. Stopping tool execution.]"

        # Save to transcript (user message + assistant response)
        self.transcript_store.append_message(
            session.session_id,
            agent_id,
            Message(role="user", content=message)
        )
        self.transcript_store.append_message(
            session.session_id,
            agent_id,
            Message(role="assistant", content=final_content, thinking=response.thinking)
        )

        # Update session tokens
        self.session_store.update(
            session_key,
            input_tokens=session.input_tokens + response.prompt_tokens,
            output_tokens=session.output_tokens + response.completion_tokens,
            total_tokens=session.total_tokens + response.total_tokens
        )

        # Emit event
        await event_bus.emit(EVENT_AGENT_MESSAGE, {
            "agent_id": agent_id,
            "session_key": session_key,
            "message": message[:200],
            "response": final_content[:200],
            "tool_rounds": tool_round,
        })

        return final_content

    async def _run_heartbeat_turn(self, agent_id: str, prompt: str) -> str:
        """Run a heartbeat turn for an agent."""
        session_key = f"agent:{agent_id}:heartbeat"
        return await self._run_agent_turn(agent_id, session_key, prompt)
