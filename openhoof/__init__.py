"""
OpenHoof — Local AI agent runtime library + FunctionGemma training.

A standalone, extensible library for running AI agents with:
- Agent event loop with heartbeat
- Context files (SOUL.md, MEMORY.md, USER.md, TOOLS.md)
- DDIL (store-and-forward for offline operation)
- LlamaFarm integration
- FunctionGemma training pipeline
- OpenAI-compatible tool schemas

Usage:
    from openhoof import Agent, Soul, Memory
    
    agent = Agent(
        soul="SOUL.md",
        memory="MEMORY.md",
        tools=my_tools,
        executor=my_executor
    )
    
    agent.on_exit("battery_low", lambda: battery < 20)
    agent.run()
"""

__version__ = "2.0.0"
__author__ = "LlamaFarm"

# Core agent runtime
from .agent import Agent
from .soul import Soul
from .memory import Memory
from .heartbeat import Heartbeat
from .events import EventQueue, Event
from .ddil import DDILBuffer
from .training import TrainingDataCapture
from .models import ModelLoader, LlamaFarmConfig, LlamaFarmClient

# Tool system (OpenAI-compatible schemas)
from .tools.base import Tool, ToolContext, ToolResult
from .tools.registry import ToolRegistry
from .tool_registry import ToolRegistry as SimpleToolRegistry  # Simpler version for basic use

__all__ = [
    # Agent runtime
    "Agent",
    "Soul",
    "Memory",
    "Heartbeat",
    "EventQueue",
    "Event",
    "DDILBuffer",
    "TrainingDataCapture",
    "ModelLoader",
    "LlamaFarmConfig",
    "LlamaFarmClient",
    
    # Tool system
    "Tool",
    "ToolContext",
    "ToolResult",
    "ToolRegistry",
    "SimpleToolRegistry",
]
