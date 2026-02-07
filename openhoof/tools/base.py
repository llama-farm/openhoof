"""Base tool classes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Context provided to tools during execution."""
    agent_id: str
    session_key: str
    workspace_dir: str
    
    # For approval flow
    approval_callback: Optional[Any] = None
    
    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Result from tool execution."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    error: Optional[str] = None
    
    # For approval flow
    requires_approval: bool = False
    approval_id: Optional[str] = None
    approval_description: Optional[str] = None
    
    def to_content(self) -> str:
        """Convert to string content for the model."""
        if self.error:
            return f"Error: {self.error}"
        if self.message:
            return self.message
        if self.data:
            import json
            return json.dumps(self.data, indent=2)
        return "Success" if self.success else "Failed"


class Tool(ABC):
    """Base class for all tools."""
    
    # Tool metadata
    name: str = "unnamed_tool"
    description: str = "No description"
    
    # OpenAI-compatible parameter schema
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": []
    }
    
    # Whether this tool requires human approval
    requires_approval: bool = False
    
    @abstractmethod
    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute the tool with given parameters."""
        pass
    
    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI tool schema format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }
    
    async def validate_params(self, params: Dict[str, Any]) -> Optional[str]:
        """Validate parameters. Returns error message if invalid."""
        required = self.parameters.get("required", [])
        for field in required:
            if field not in params:
                return f"Missing required parameter: {field}"
        return None
