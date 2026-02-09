"""Built-in tools for OpenHoof."""

from .memory import MemoryWriteTool, MemoryReadTool
from .notify import NotifyTool
from .exec import ExecTool
from .spawn import SpawnAgentTool
from .shared import SharedWriteTool, SharedReadTool, SharedLogTool, SharedSearchTool, ListToolsTool
from .yield_tool import YieldTool
from .configure_agent import ConfigureAgentTool
from .list_agents import ListAgentsTool

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
    "YieldTool",
    "ConfigureAgentTool",
    "ListAgentsTool",
]


def register_builtin_tools(registry, agent_manager=None):
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

    # Yield tool (autonomous_only=True, filtered out of non-autonomous turns)
    registry.register(YieldTool())

    # Configure agent tool (needs agent_manager reference for stop/status)
    configure_tool = ConfigureAgentTool()
    configure_tool._agent_manager = agent_manager
    registry.register(configure_tool)

    # List agents tool (needs agent_manager reference for running status)
    list_agents_tool = ListAgentsTool()
    list_agents_tool._agent_manager = agent_manager
    registry.register(list_agents_tool)

    # ListToolsTool needs special wiring
    list_tool = ListToolsTool()
    list_tool._registry = registry
    registry.register(list_tool)
