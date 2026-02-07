"""Notification tool for sending alerts."""

from typing import Dict, Any
import uuid

from ..base import Tool, ToolResult, ToolContext


class NotifyTool(Tool):
    """Send notifications to users."""
    
    name = "notify"
    description = """Send a notification or alert.
    
Use this to:
- Alert users about important events
- Request human attention for decisions
- Report findings or recommendations

By default, notifications require human approval before sending."""
    
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Notification title"
            },
            "message": {
                "type": "string",
                "description": "Notification message body"
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
                "description": "Notification priority level",
                "default": "medium"
            },
            "channel": {
                "type": "string",
                "description": "Optional: specific channel to notify (default: UI notifications)"
            }
        },
        "required": ["title", "message"]
    }
    
    requires_approval = True
    
    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        title = params["title"]
        message = params["message"]
        priority = params.get("priority", "medium")
        channel = params.get("channel")
        
        # Generate notification ID
        notification_id = str(uuid.uuid4())[:8]
        
        # If this tool requires approval, return a pending result
        if self.requires_approval:
            return ToolResult(
                success=True,
                requires_approval=True,
                approval_id=notification_id,
                approval_description=f"Send notification: {title}",
                data={
                    "notification_id": notification_id,
                    "title": title,
                    "message": message,
                    "priority": priority,
                    "channel": channel,
                    "status": "pending_approval"
                },
                message=f"Notification '{title}' queued for approval (ID: {notification_id})"
            )
        
        # Direct send (if approval not required)
        return ToolResult(
            success=True,
            data={
                "notification_id": notification_id,
                "title": title,
                "message": message,
                "priority": priority,
                "status": "sent"
            },
            message=f"Notification sent: {title}"
        )
