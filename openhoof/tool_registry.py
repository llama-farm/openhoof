"""
Tools — Tool registry and execution wrapper.

Compatible with OpenHoof tool schemas:
    {
        "name": "drone_takeoff",
        "description": "Take off and hover at specified altitude",
        "parameters": {
            "type": "object",
            "properties": {
                "alt_m": {"type": "number", "default": 15.0}
            }
        }
    }

The ToolRegistry:
1. Registers tools from OpenHoof-compatible schema
2. Routes tool calls by name
3. Validates parameters (basic)
4. Captures training data for every call
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional


class Tool:
    """A single tool definition."""
    
    def __init__(self, schema: Dict[str, Any], executor: Optional[Callable] = None):
        self.name = schema["name"]
        self.description = schema.get("description", "")
        self.parameters = schema.get("parameters", {})
        self.executor = executor
    
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the tool with given parameters."""
        if self.executor is None:
            return {
                "status": "error",
                "error": f"No executor registered for tool {self.name!r}"
            }
        
        try:
            result = self.executor(self.name, params)
            return result if isinstance(result, dict) else {"result": result}
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "tool": self.name
            }
    
    def __repr__(self) -> str:
        return f"Tool(name={self.name!r}, has_executor={self.executor is not None})"


class ToolRegistry:
    """Registry of available tools."""
    
    def __init__(self, tools: List[Dict[str, Any]] = None, executor: Optional[Callable] = None):
        """
        Initialize tool registry.
        
        Args:
            tools: List of OpenHoof-compatible tool schemas
            executor: Callable that executes tools: executor(tool_name, params) -> result
        """
        self.tools: Dict[str, Tool] = {}
        self.executor = executor
        self.call_count = 0
        
        if tools:
            self.register_tools(tools, executor)
    
    def register_tools(self, tools: List[Dict[str, Any]], executor: Optional[Callable] = None):
        """Register multiple tools at once."""
        exec_fn = executor or self.executor
        for schema in tools:
            # Support both OpenAI format and direct format
            if "function" in schema:
                # OpenAI format: {"type": "function", "function": {...}}
                tool_schema = schema["function"]
            else:
                # Direct format: {"name": "...", "description": "...", ...}
                tool_schema = schema
            
            name = tool_schema["name"]
            self.tools[name] = Tool(tool_schema, exec_fn)
    
    def register(self, schema: Dict[str, Any], executor: Optional[Callable] = None):
        """Register a single tool."""
        name = schema["name"]
        exec_fn = executor or self.executor
        self.tools[name] = Tool(schema, exec_fn)
    
    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self.tools.get(name)
    
    def execute(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool by name."""
        self.call_count += 1
        
        tool = self.get(tool_name)
        if tool is None:
            return {
                "status": "error",
                "error": f"Tool {tool_name!r} not found. Available: {list(self.tools.keys())}"
            }
        
        return tool.execute(params)
    
    def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self.tools.keys())
    
    def to_schema(self, format: str = "openai") -> List[Dict[str, Any]]:
        """
        Export all tools as schemas.
        
        Args:
            format: "openai" (with type/function wrapper) or "simple" (direct)
        
        Returns:
            List of tool schemas
        """
        if format == "openai":
            return [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters
                    }
                }
                for tool in self.tools.values()
            ]
        else:
            # Simple format (backward compatible)
            return [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
                for tool in self.tools.values()
            ]
    
    def __len__(self) -> int:
        return len(self.tools)
    
    def __repr__(self) -> str:
        return f"ToolRegistry(tools={len(self.tools)}, calls={self.call_count})"
