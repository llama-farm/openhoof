"""Tool registry for managing available tools."""

from typing import Dict, List, Optional, Any
import logging

from .base import Tool, ToolResult, ToolContext

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for managing tools."""
    
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
    
    def register(self, tool: Tool) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing tool: {tool.name}")
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")
    
    def unregister(self, name: str) -> bool:
        """Unregister a tool."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False
    
    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)
    
    def list_tools(self) -> List[Tool]:
        """List all registered tools."""
        return list(self._tools.values())
    
    def get_openai_schemas(self, tool_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Get OpenAI tool schemas for specified tools (or all if not specified)."""
        tools = self._tools.values()
        if tool_names:
            tools = [t for t in tools if t.name in tool_names]
        return [t.to_openai_schema() for t in tools]
    
    async def execute(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: ToolContext
    ) -> ToolResult:
        """Execute a tool by name."""
        tool = self.get(tool_name)
        if tool is None:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}"
            )
        
        # Validate parameters
        error = await tool.validate_params(params)
        if error:
            return ToolResult(success=False, error=error)
        
        try:
            result = await tool.execute(params, context)
            logger.info(f"Tool {tool_name} executed: success={result.success}")
            return result
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return ToolResult(success=False, error=str(e))
