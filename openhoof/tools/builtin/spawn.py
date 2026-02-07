"""Sub-agent spawning tool."""

import uuid
from typing import Dict, Any, Optional

from ..base import Tool, ToolResult, ToolContext


class SpawnAgentTool(Tool):
    """Spawn a sub-agent for specialized tasks."""
    
    name = "spawn_agent"
    description = """Spawn a background sub-agent to handle a specific task.
    
Use this when:
- A task requires specialized expertise (different agent type)
- Work can proceed in parallel while you continue
- A task is complex enough to warrant isolated context

The sub-agent will run asynchronously and results will be announced when complete."""
    
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The task for the sub-agent to complete"
            },
            "agent_id": {
                "type": "string",
                "description": "Agent type to spawn (e.g., 'intel-analyst', 'fuel-analyst'). If omitted, spawns same type."
            },
            "label": {
                "type": "string",
                "description": "Human-readable label for tracking"
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Maximum time for sub-agent to complete (default: 300)"
            }
        },
        "required": ["task"]
    }
    
    # This will be set by the agent manager when registering
    spawn_callback: Optional[Any] = None
    
    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        task = params["task"]
        agent_id = params.get("agent_id", context.agent_id)
        label = params.get("label")
        timeout = params.get("timeout_seconds", 300)
        
        # Generate run ID
        run_id = str(uuid.uuid4())[:8]
        
        # If we have a spawn callback, use it
        if self.spawn_callback:
            try:
                result = await self.spawn_callback(
                    requester_session_key=context.session_key,
                    agent_id=agent_id,
                    task=task,
                    label=label,
                    timeout_seconds=timeout
                )
                return ToolResult(
                    success=True,
                    data={
                        "run_id": result.get("run_id", run_id),
                        "agent_id": agent_id,
                        "label": label or task[:50],
                        "status": "spawned"
                    },
                    message=f"Sub-agent spawned. Results will be announced when complete."
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    error=f"Failed to spawn sub-agent: {e}"
                )
        
        # No callback - try to run synchronously via the manager
        return ToolResult(
            success=True,
            data={
                "run_id": run_id,
                "agent_id": agent_id,
                "task": task,
                "label": label or task[:50],
                "status": "pending_execution",
            },
            message=f"Delegating to {agent_id}: {task[:100]}..."
        )
