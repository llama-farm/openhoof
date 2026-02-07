"""Built-in tools for Atmosphere Agents."""

from .memory import MemoryWriteTool, MemoryReadTool
from .notify import NotifyTool
from .exec import ExecTool
from .spawn import SpawnAgentTool

__all__ = [
    "MemoryWriteTool",
    "MemoryReadTool", 
    "NotifyTool",
    "ExecTool",
    "SpawnAgentTool",
]


def register_builtin_tools(registry):
    """Register all built-in tools with a registry."""
    registry.register(MemoryWriteTool())
    registry.register(MemoryReadTool())
    registry.register(NotifyTool())
    registry.register(ExecTool())
    registry.register(SpawnAgentTool())
