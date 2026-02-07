"""Agent lifecycle management."""

import asyncio
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
from .heartbeat import HeartbeatRunner, HeartbeatConfig

logger = logging.getLogger(__name__)


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
    
    @classmethod
    def from_yaml(cls, path: Path) -> "AgentConfig":
        """Load config from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(
            agent_id=data.get("id", path.parent.name),
            name=data.get("name", path.parent.name),
            description=data.get("description", ""),
            model=data.get("model"),
            thinking=data.get("thinking"),
            heartbeat_enabled=data.get("heartbeat", {}).get("enabled", True),
            heartbeat_interval=data.get("heartbeat", {}).get("interval", 1800),
            tools=data.get("tools", []),
        )


@dataclass
class AgentHandle:
    """Handle to a running agent."""
    agent_id: str
    config: AgentConfig
    workspace: AgentWorkspace
    session: SessionEntry
    heartbeat: Optional[HeartbeatRunner] = None
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
            register_builtin_tools(self.tool_registry)
        
        # Running agents
        self._agents: Dict[str, AgentHandle] = {}
    
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
            
            agents.append({
                "agent_id": config.agent_id,
                "name": config.name,
                "description": config.description,
                "status": "running" if config.agent_id in self._agents else "stopped",
                "workspace_dir": str(agent_dir),
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
        
        # Create handle
        handle = AgentHandle(
            agent_id=agent_id,
            config=config,
            workspace=workspace,
            session=session,
            heartbeat=heartbeat,
            status="running"
        )
        
        self._agents[agent_id] = handle
        
        # Emit event
        await event_bus.emit(EVENT_AGENT_STARTED, {
            "agent_id": agent_id,
            "name": config.name,
            "session_key": session_key
        })
        
        logger.info(f"Started agent: {agent_id}")
        return handle
    
    async def stop_agent(self, agent_id: str) -> bool:
        """Stop an agent."""
        handle = self._agents.get(agent_id)
        if not handle:
            return False
        
        # Stop heartbeat
        if handle.heartbeat:
            handle.heartbeat.stop()
        
        handle.status = "stopped"
        del self._agents[agent_id]
        
        # Emit event
        await event_bus.emit(EVENT_AGENT_STOPPED, {"agent_id": agent_id})
        
        logger.info(f"Stopped agent: {agent_id}")
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
    
    def _parse_tool_calls_from_text(self, text: str) -> list:
        """Parse tool calls from model output (handles Qwen3 XML-style calls)."""
        import re
        import json
        
        tool_calls = []
        
        # Pattern for <tool_call>{"name": "...", "arguments": {...}}</tool_call>
        pattern1 = r'<tool_call>\s*(\{[^}]+\})\s*</tool_call>'
        # Pattern for <spawn_agent task="..." agent_id="..."/>
        pattern2 = r'<spawn_agent\s+task="([^"]+)"\s+agent_id="([^"]+)"\s*/>'
        # Pattern for <notify title="..." message="..." priority="..."/>
        pattern3 = r'<notify\s+title="([^"]+)"\s+message="([^"]+)"(?:\s+priority="([^"]+)")?\s*/>'
        
        # Try pattern 1 (JSON tool calls)
        for match in re.finditer(pattern1, text):
            try:
                call = json.loads(match.group(1))
                tool_calls.append({
                    "name": call.get("name"),
                    "arguments": call.get("arguments", {})
                })
            except json.JSONDecodeError:
                pass
        
        # Try pattern 2 (spawn_agent)
        for match in re.finditer(pattern2, text):
            tool_calls.append({
                "name": "spawn_agent",
                "arguments": {
                    "task": match.group(1),
                    "agent_id": match.group(2)
                }
            })
        
        # Try pattern 3 (notify)
        for match in re.finditer(pattern3, text):
            tool_calls.append({
                "name": "notify",
                "arguments": {
                    "title": match.group(1),
                    "message": match.group(2),
                    "priority": match.group(3) or "medium"
                }
            })
        
        return tool_calls

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
        
        # Get conversation history
        session = self.session_store.get_or_create(session_key, agent_id=agent_id)
        history = self.transcript_store.get_messages_for_context(session.session_id)
        
        # Build messages
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend([m.to_openai_format() for m in history])
        messages.append({"role": "user", "content": message})
        
        # Get tools
        tools = self.tool_registry.get_openai_schemas(handle.config.tools or None)
        
        # Call inference
        response = await self.inference.chat_completion(
            messages=messages,
            tools=tools if tools else None,
            model=handle.config.model,
            think=handle.config.thinking is not None,
            thinking_budget=512 if handle.config.thinking else None,
            rag_enabled=False,
            stateless=True,
        )
        
        # Emit thinking event if model produced thinking output
        if response.thinking:
            await event_bus.emit(EVENT_AGENT_THINKING, {
                "agent_id": agent_id,
                "session_key": session_key,
                "thinking": response.thinking[:500] + "..." if len(response.thinking) > 500 else response.thinking,
            })
        
        # Handle tool calls (OpenAI format)
        while response.has_tool_calls():
            # Execute tools
            tool_messages = []
            for tc in response.tool_calls:
                # Emit tool call event
                await event_bus.emit(EVENT_AGENT_TOOL_CALL, {
                    "agent_id": agent_id,
                    "session_key": session_key,
                    "tool_name": tc.name,
                    "tool_arguments": tc.arguments,
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
                })
                
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.to_content()
                })
            
            # Add assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [tc.to_openai_format() for tc in response.tool_calls]
            })
            messages.extend(tool_messages)
            
            # Get next response
            response = await self.inference.chat_completion(
                messages=messages,
                tools=tools if tools else None,
                model=handle.config.model,
                rag_enabled=False,
                stateless=True,
            )
        
        # Handle XML-style tool calls (Qwen3 format)
        parsed_calls = self._parse_tool_calls_from_text(response.content or "")
        tool_results = []
        for call in parsed_calls:
            tool_name = call["name"]
            tool_args = call["arguments"]
            
            # Special handling for spawn_agent - run sub-agent synchronously
            if tool_name == "spawn_agent":
                sub_agent_id = tool_args.get("agent_id", agent_id)
                sub_task = tool_args.get("task", "")
                
                # Emit subagent spawned event
                await event_bus.emit(EVENT_SUBAGENT_SPAWNED, {
                    "agent_id": agent_id,
                    "subagent_id": sub_agent_id,
                    "task": sub_task[:200] + "..." if len(sub_task) > 200 else sub_task,
                })
                
                try:
                    # Auto-start sub-agent if not running
                    if sub_agent_id not in self._agents:
                        await self.start_agent(sub_agent_id)
                    
                    # Run the sub-agent and get its response
                    sub_response = await self._run_agent_turn(
                        sub_agent_id,
                        f"subagent:{sub_agent_id}:{session_key}",
                        sub_task
                    )
                    tool_results.append({
                        "tool": f"spawn_agent({sub_agent_id})",
                        "result": sub_response
                    })
                    
                    # Emit subagent completed event
                    await event_bus.emit(EVENT_SUBAGENT_COMPLETED, {
                        "agent_id": agent_id,
                        "subagent_id": sub_agent_id,
                        "success": True,
                        "response_preview": sub_response[:200] + "..." if len(sub_response) > 200 else sub_response,
                    })
                    
                    logger.info(f"Sub-agent {sub_agent_id} completed task")
                except Exception as e:
                    tool_results.append({
                        "tool": f"spawn_agent({sub_agent_id})",
                        "result": f"Error: {e}"
                    })
                    
                    # Emit subagent completed (failed) event
                    await event_bus.emit(EVENT_SUBAGENT_COMPLETED, {
                        "agent_id": agent_id,
                        "subagent_id": sub_agent_id,
                        "success": False,
                        "error": str(e),
                    })
                    
                    logger.error(f"Sub-agent {sub_agent_id} failed: {e}")
            else:
                # Emit tool call event
                await event_bus.emit(EVENT_AGENT_TOOL_CALL, {
                    "agent_id": agent_id,
                    "session_key": session_key,
                    "tool_name": tool_name,
                    "tool_arguments": tool_args,
                })
                
                # Regular tool execution
                context = ToolContext(
                    agent_id=agent_id,
                    session_key=session_key,
                    workspace_dir=str(handle.workspace.dir)
                )
                result = await self.tool_registry.execute(tool_name, tool_args, context)
                
                # Emit tool result event
                await event_bus.emit(EVENT_AGENT_TOOL_RESULT, {
                    "agent_id": agent_id,
                    "session_key": session_key,
                    "tool_name": tool_name,
                    "success": result.success,
                    "result_preview": str(result.to_content())[:200],
                })
                
                tool_results.append({
                    "tool": tool_name,
                    "result": result.to_content()
                })
                logger.info(f"Executed tool {tool_name}: {result.success}")
        
        # If tools were executed, append results to response
        final_content = response.content or ""
        if tool_results:
            results_text = "\n\n---\n**Tool Execution Results:**\n"
            for tr in tool_results:
                results_text += f"- **{tr['tool']}**: {tr['result']}\n"
            final_content = final_content + results_text
        
        # Save to transcript
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
            "message": message,
            "response": final_content,
        })
        
        return final_content
    
    async def _run_heartbeat_turn(self, agent_id: str, prompt: str) -> str:
        """Run a heartbeat turn for an agent."""
        session_key = f"agent:{agent_id}:heartbeat"
        return await self._run_agent_turn(agent_id, session_key, prompt)
