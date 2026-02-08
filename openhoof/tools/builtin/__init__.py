"""Built-in tools for OpenHoof."""

from .memory import MemoryWriteTool, MemoryReadTool
from .notify import NotifyTool
from .exec import ExecTool
from .spawn import SpawnAgentTool
from .shared import SharedWriteTool, SharedReadTool, SharedLogTool, SharedSearchTool, ListToolsTool

__all__ = [
    "MemoryWriteTool",
    "MemoryReadTool",
    "NotifyTool",
    "ExecTool",
    "SpawnAgentTool",
    "SharedWriteTool",
    "SharedReadTool",
    "SharedLogTool",
    "SharedSearchTool",
    "ListToolsTool",
]


def register_builtin_tools(registry):
    """Register all built-in tools with a registry."""
    registry.register(MemoryWriteTool())
    registry.register(MemoryReadTool())
    registry.register(NotifyTool())
    registry.register(ExecTool())
    registry.register(SpawnAgentTool())
    registry.register(SharedWriteTool())
    registry.register(SharedReadTool())
    registry.register(SharedLogTool())
    registry.register(SharedSearchTool())

    # ListToolsTool needs special wiring
    list_tool = ListToolsTool()
    list_tool._registry = registry
    registry.register(list_tool)
