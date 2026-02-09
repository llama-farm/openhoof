"""Configure agent tool — CRUD operations on agent configurations."""

import re
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List
import yaml
import logging

from ..base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

# Valid hot state field types
VALID_HS_TYPES = {"object", "number", "string", "array", "boolean"}

# Valid sensor types
VALID_SENSOR_TYPES = {"poll", "watch", "stream"}

# Agent ID pattern: kebab-case
AGENT_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Nested config sections that use shallow replacement on update
NESTED_SECTIONS = {"autonomy", "hot_state", "sensors"}

# Autonomy defaults
AUTONOMY_DEFAULTS = {
    "enabled": False,
    "max_consecutive_turns": 50,
    "token_budget_per_hour": 100000,
    "max_actions_per_minute": 10,
    "idle_timeout": 600,
}

# Protected agent IDs that cannot be deleted
PROTECTED_AGENTS = {"agent-builder"}


def _get_agents_dir(context: ToolContext) -> Path:
    """Get the agents directory from context."""
    # workspace_dir is the calling agent's workspace; go up one level to get agents_dir
    return Path(context.workspace_dir).parent


def _validate_agent_id(agent_id: str) -> Optional[str]:
    """Validate agent_id format. Returns error message or None."""
    if not agent_id:
        return "Agent ID is required"
    if not AGENT_ID_PATTERN.match(agent_id):
        return "Agent ID must be kebab-case (lowercase letters, numbers, hyphens)"
    return None


def _validate_config(config: Dict[str, Any]) -> Optional[str]:
    """Validate agent config dict. Returns error message or None."""
    # Validate hot_state fields
    if "hot_state" in config and isinstance(config["hot_state"], dict):
        fields = config["hot_state"].get("fields", {})
        if isinstance(fields, dict):
            for field_name, field_cfg in fields.items():
                if isinstance(field_cfg, dict):
                    ftype = field_cfg.get("type", "object")
                    if ftype not in VALID_HS_TYPES:
                        return (
                            f"Hot state field '{field_name}': type must be one of: "
                            f"{', '.join(sorted(VALID_HS_TYPES))}"
                        )

    # Validate sensors
    if "sensors" in config and isinstance(config["sensors"], list):
        for sensor in config["sensors"]:
            if not isinstance(sensor, dict):
                continue
            sname = sensor.get("name", "<unnamed>")
            stype = sensor.get("type", "")

            if stype not in VALID_SENSOR_TYPES:
                return (
                    f"Sensor '{sname}': type must be one of: "
                    f"{', '.join(sorted(VALID_SENSOR_TYPES))}"
                )

            if stype == "poll" and not sensor.get("interval"):
                return f"Sensor '{sname}': poll type requires 'interval' field"

            if stype == "watch":
                source = sensor.get("source", {})
                if not source.get("path"):
                    return f"Sensor '{sname}': watch type requires 'source.path' field"

            if stype == "stream":
                source = sensor.get("source", {})
                if not source.get("url"):
                    return f"Sensor '{sname}': stream type requires 'source.url' field"

    return None


def _apply_defaults(config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply safe defaults to config sections."""
    # Autonomy defaults
    if "autonomy" in config and isinstance(config["autonomy"], dict):
        for key, default in AUTONOMY_DEFAULTS.items():
            if key not in config["autonomy"]:
                config["autonomy"][key] = default

    # Hot state field defaults
    if "hot_state" in config and isinstance(config["hot_state"], dict):
        fields = config["hot_state"].get("fields", {})
        if isinstance(fields, dict):
            for field_cfg in fields.values():
                if isinstance(field_cfg, dict) and "type" not in field_cfg:
                    field_cfg["type"] = "object"

    # Sensor signal defaults
    if "sensors" in config and isinstance(config["sensors"], list):
        for sensor in config["sensors"]:
            if isinstance(sensor, dict):
                if "updates" not in sensor:
                    sensor["updates"] = []
                if "signals" not in sensor:
                    sensor["signals"] = []
                for signal in sensor.get("signals", []):
                    if isinstance(signal, dict):
                        if "threshold" not in signal:
                            signal["threshold"] = 0.8
                        if "notify" not in signal:
                            signal["notify"] = True

    return config


def _config_to_yaml(agent_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Convert config dict to YAML-ready dict with proper structure."""
    yaml_data = {"id": agent_id}

    # Map top-level fields
    for key in ("name", "description", "model", "thinking", "tools", "max_tool_rounds"):
        if key in config:
            yaml_data[key] = config[key]

    # Heartbeat
    if "heartbeat_enabled" in config or "heartbeat_interval" in config:
        yaml_data["heartbeat"] = {
            "enabled": config.get("heartbeat_enabled", True),
            "interval": config.get("heartbeat_interval", 1800),
        }

    # Nested sections passed through directly
    for section in ("autonomy", "hot_state", "sensors"):
        if section in config:
            yaml_data[section] = config[section]

    return yaml_data


def _generate_default_soul(name: str, description: str = "") -> str:
    """Generate a default SOUL.md for a new agent."""
    lines = [f"# {name}", ""]
    if description:
        lines.append(description)
        lines.append("")
    lines.extend([
        "## Mission",
        f"You are {name}. Assist users with your designated tasks.",
        "",
        "## Guidelines",
        "- Be helpful and concise",
        "- Use your available tools when appropriate",
        "- Ask for clarification when instructions are ambiguous",
        "",
    ])
    return "\n".join(lines)


class ConfigureAgentTool(Tool):
    """Tool for creating, reading, updating, and deleting agent configurations."""

    name = "configure_agent"
    description = (
        "Create, read, update, or delete agent configurations. "
        "Use action='create' to make a new agent, 'read' to inspect an existing agent, "
        "'update' to modify an agent's config or workspace files, 'delete' to remove an agent."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "read", "update", "delete"],
                "description": "The CRUD action to perform",
            },
            "agent_id": {
                "type": "string",
                "description": "The agent's unique identifier (kebab-case)",
            },
            "config": {
                "type": "object",
                "description": (
                    "Agent configuration object. Required for 'create', optional for 'update'. "
                    "Top-level fields: name, description, model, thinking, tools (list), "
                    "max_tool_rounds, heartbeat_enabled, heartbeat_interval. "
                    "Nested sections: autonomy (object), hot_state (object with fields), "
                    "sensors (list of sensor objects)."
                ),
            },
            "files": {
                "type": "object",
                "description": (
                    "Workspace files to write, as {filename: content}. "
                    "e.g., {'SOUL.md': '...', 'HEARTBEAT.md': '...'}"
                ),
            },
        },
        "required": ["action", "agent_id"],
    }

    # Reference to AgentManager, wired up during registration
    _agent_manager: Any = None

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        action = params.get("action", "")
        agent_id = params.get("agent_id", "")
        config = params.get("config", {})
        files = params.get("files", {})

        # Validate agent_id format
        id_error = _validate_agent_id(agent_id)
        if id_error:
            return ToolResult(success=False, error=id_error)

        agents_dir = _get_agents_dir(context)

        if action == "create":
            return await self._create(agents_dir, agent_id, config, files)
        elif action == "read":
            return await self._read(agents_dir, agent_id)
        elif action == "update":
            return await self._update(agents_dir, agent_id, config, files)
        elif action == "delete":
            return await self._delete(agents_dir, agent_id)
        else:
            return ToolResult(success=False, error=f"Invalid action: {action}")

    async def _create(
        self, agents_dir: Path, agent_id: str, config: Dict[str, Any], files: Dict[str, str]
    ) -> ToolResult:
        workspace_dir = agents_dir / agent_id
        if workspace_dir.exists():
            return ToolResult(success=False, error=f"Agent '{agent_id}' already exists")

        if not config:
            return ToolResult(success=False, error="Config is required for create action")

        if "name" not in config:
            return ToolResult(success=False, error="Config must include 'name'")

        # Validate config
        validation_error = _validate_config(config)
        if validation_error:
            return ToolResult(success=False, error=validation_error)

        # Apply defaults
        config = _apply_defaults(config)

        # Create workspace
        workspace_dir.mkdir(parents=True, exist_ok=True)

        # Write agent.yaml
        yaml_data = _config_to_yaml(agent_id, config)
        with open(workspace_dir / "agent.yaml", "w") as f:
            yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False)

        # Write workspace files
        for filename, content in files.items():
            (workspace_dir / filename).write_text(content)

        # Generate default SOUL.md if not provided
        if "SOUL.md" not in files:
            soul = _generate_default_soul(config["name"], config.get("description", ""))
            (workspace_dir / "SOUL.md").write_text(soul)

        return ToolResult(
            success=True,
            message=f"Created agent '{agent_id}' ({config['name']}) at {workspace_dir}",
            data={
                "agent_id": agent_id,
                "name": config["name"],
                "workspace": str(workspace_dir),
            },
        )

    async def _read(self, agents_dir: Path, agent_id: str) -> ToolResult:
        workspace_dir = agents_dir / agent_id
        if not workspace_dir.exists():
            return ToolResult(success=False, error=f"Agent '{agent_id}' not found")

        # Load agent.yaml
        config_path = workspace_dir / "agent.yaml"
        config_data = {}
        if config_path.exists():
            with open(config_path) as f:
                config_data = yaml.safe_load(f) or {}

        # List workspace files
        file_list = []
        for p in sorted(workspace_dir.rglob("*")):
            if p.is_file():
                rel = p.relative_to(workspace_dir)
                file_list.append({"path": str(rel), "size": p.stat().st_size})

        return ToolResult(
            success=True,
            data={"config": config_data, "files": file_list},
        )

    async def _update(
        self, agents_dir: Path, agent_id: str, config: Dict[str, Any], files: Dict[str, str]
    ) -> ToolResult:
        workspace_dir = agents_dir / agent_id
        if not workspace_dir.exists():
            return ToolResult(success=False, error=f"Agent '{agent_id}' not found")

        # Validate config if provided
        if config:
            validation_error = _validate_config(config)
            if validation_error:
                return ToolResult(success=False, error=validation_error)

            config = _apply_defaults(config)

        updated_parts = []

        # Update agent.yaml if config provided
        if config:
            config_path = workspace_dir / "agent.yaml"
            existing = {}
            if config_path.exists():
                with open(config_path) as f:
                    existing = yaml.safe_load(f) or {}

            # Shallow merge: top-level scalars individually, nested sections replaced whole
            for key, value in config.items():
                if key in NESTED_SECTIONS:
                    existing[key] = value
                elif key == "heartbeat_enabled":
                    existing.setdefault("heartbeat", {})["enabled"] = value
                elif key == "heartbeat_interval":
                    existing.setdefault("heartbeat", {})["interval"] = value
                else:
                    existing[key] = value

            with open(config_path, "w") as f:
                yaml.dump(existing, f, default_flow_style=False, sort_keys=False)

            updated_parts.append("config")

        # Write workspace files
        if files:
            for filename, content in files.items():
                (workspace_dir / filename).write_text(content)
            updated_parts.append(f"{len(files)} file(s)")

        # Check if agent is running
        running_note = ""
        if self._agent_manager:
            handle = self._agent_manager._agents.get(agent_id)
            if handle:
                running_note = " Note: agent is running — restart for changes to take effect."

        msg = f"Updated agent '{agent_id}': {', '.join(updated_parts)}.{running_note}"
        return ToolResult(
            success=True,
            message=msg,
            data={"agent_id": agent_id, "updated": updated_parts},
        )

    async def _delete(self, agents_dir: Path, agent_id: str) -> ToolResult:
        if agent_id in PROTECTED_AGENTS:
            return ToolResult(success=False, error="Cannot delete the builder agent")

        workspace_dir = agents_dir / agent_id
        if not workspace_dir.exists():
            return ToolResult(success=False, error=f"Agent '{agent_id}' not found")

        # Stop agent if running
        if self._agent_manager:
            handle = self._agent_manager._agents.get(agent_id)
            if handle:
                await self._agent_manager.stop_agent(agent_id)

        # Remove workspace
        shutil.rmtree(workspace_dir)

        return ToolResult(
            success=True,
            message=f"Deleted agent '{agent_id}'",
            data={"agent_id": agent_id},
        )
