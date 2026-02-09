"""Yield tool — allows autonomous agents to control their execution pacing."""

from typing import Dict, Any
from ..base import Tool, ToolResult, ToolContext

VALID_MODES = ("sleep", "continue", "shutdown")


class YieldTool(Tool):
    """Tool that lets autonomous agents control their pacing."""

    name = "yield"
    description = (
        "Control your execution pacing in autonomous mode. "
        "Call with mode='sleep' to pause for N seconds, "
        "mode='continue' for immediate next turn, "
        "or mode='shutdown' to stop the autonomous loop."
    )
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["sleep", "continue", "shutdown"],
                "description": "Pacing mode: 'sleep' (pause), 'continue' (immediate next turn), 'shutdown' (stop loop)",
            },
            "sleep": {
                "type": "integer",
                "description": "Seconds to sleep (required when mode='sleep')",
            },
            "reason": {
                "type": "string",
                "description": "Human-readable explanation for this yield decision",
            },
            "wake_early_if": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Notification names that should wake the agent early during sleep",
            },
        },
        "required": ["mode"],
    }

    # Flag to indicate this tool is only for autonomous mode
    autonomous_only: bool = True

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Validate and acknowledge the yield. Actual behavior is enacted by the loop runner."""
        mode = params.get("mode", "")
        sleep_seconds = params.get("sleep", 0)
        reason = params.get("reason", "")
        wake_early_if = params.get("wake_early_if", [])

        if mode not in VALID_MODES:
            return ToolResult(
                success=False,
                error=f"Invalid mode: '{mode}'. Must be one of: {', '.join(VALID_MODES)}"
            )

        if mode == "sleep" and (not isinstance(sleep_seconds, int) or sleep_seconds <= 0):
            return ToolResult(
                success=False,
                error="mode='sleep' requires a positive integer 'sleep' parameter (seconds)"
            )

        # Build confirmation message
        if mode == "sleep":
            msg = f"Sleeping for {sleep_seconds}s"
            if wake_early_if:
                msg += f" (wake early on: {', '.join(wake_early_if)})"
        elif mode == "continue":
            msg = "Continuing immediately"
        else:  # shutdown
            msg = "Shutting down autonomous loop"

        if reason:
            msg += f" — {reason}"

        return ToolResult(success=True, message=msg)
