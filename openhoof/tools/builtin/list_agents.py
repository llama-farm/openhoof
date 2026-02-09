"""List agents tool — discover agents on the system."""

from pathlib import Path
from typing import Dict, Any, List
import yaml
import logging

from ..base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class ListAgentsTool(Tool):
    """Tool for listing agents on the system with their status."""

    name = "list_agents"
    description = (
        "List all agents on the system with their ID, name, description, status, "
        "and model. Optionally filter by status (running/stopped)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["all", "running", "stopped"],
                "description": "Filter by agent status. Default: 'all'",
            },
        },
        "required": [],
    }

    # Reference to AgentManager, wired up during registration
    _agent_manager: Any = None

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        status_filter = params.get("status", "all")
        agents_dir = Path(context.workspace_dir).parent

        if not agents_dir.exists():
            return ToolResult(success=True, data={"agents": []}, message="No agents found.")

        running_ids = set()
        if self._agent_manager:
            running_ids = set(self._agent_manager._agents.keys())

        agents: List[Dict[str, Any]] = []
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue

            agent_id = agent_dir.name
            config_path = agent_dir / "agent.yaml"

            # Load config
            name = agent_id
            description = ""
            model = None
            autonomy_enabled = False

            if config_path.exists():
                try:
                    with open(config_path) as f:
                        data = yaml.safe_load(f) or {}
                    name = data.get("name", agent_id)
                    description = data.get("description", "")
                    model = data.get("model")
                    autonomy = data.get("autonomy", {})
                    if isinstance(autonomy, dict):
                        autonomy_enabled = autonomy.get("enabled", False)
                except Exception as e:
                    logger.warning(f"Failed to read config for {agent_id}: {e}")

            status = "running" if agent_id in running_ids else "stopped"

            # Apply filter
            if status_filter == "running" and status != "running":
                continue
            if status_filter == "stopped" and status != "stopped":
                continue

            agents.append({
                "agent_id": agent_id,
                "name": name,
                "description": description,
                "status": status,
                "model": model,
                "autonomy_enabled": autonomy_enabled,
            })

        summary = f"Found {len(agents)} agent(s)"
        if status_filter != "all":
            summary += f" (filter: {status_filter})"

        return ToolResult(
            success=True,
            data={"agents": agents},
            message=summary,
        )
