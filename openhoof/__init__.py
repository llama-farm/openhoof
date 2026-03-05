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

__version__ = "2.2.0"
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

# Router — model-agnostic tool routing and param validation
from .router import (
    ToolRouter,
    FunctionGemmaRouter,        # backward-compat alias for ToolRouter
    RouterResult,
    OutputParser,
    ToolCallTagParser,
    FunctionGemmaOutputParser,
    ConfidenceExtractor,
)

# Fine-tuning — convert captured data to LlamaFarm SFT jobs
from .finetune import (
    FinetuneManager,
    JobStatus,
    RouterDatasetBuilder,
    ReasonerDatasetBuilder,
)

# Synthetic data generation
from .synth import (
    SyntheticDataGenerator,
    SchemaValidator,
    TeacherModel,
    RouterExampleGenerator,
    ReasonerExampleGenerator,
    GenerationStats,
)

# Tool system (OpenAI-compatible schemas)
from .tools.base import Tool, ToolContext, ToolResult
from .tools.registry import ToolRegistry
from .tool_registry import ToolRegistry as SimpleToolRegistry

# Built-in tools
from .builtin_tools import (
    get_builtin_tool_schemas,
    builtin_executor,
    create_tool_schema,
)

# Bootstrap
from .bootstrap import bootstrap_agent

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

    # Router
    "ToolRouter",
    "FunctionGemmaRouter",          # backward-compat alias
    "RouterResult",
    "OutputParser",
    "ToolCallTagParser",
    "FunctionGemmaOutputParser",
    "ConfidenceExtractor",

    # Fine-tuning
    "FinetuneManager",
    "JobStatus",
    "RouterDatasetBuilder",
    "ReasonerDatasetBuilder",

    # Synthetic data
    "SyntheticDataGenerator",
    "SchemaValidator",
    "TeacherModel",
    "RouterExampleGenerator",
    "ReasonerExampleGenerator",
    "GenerationStats",

    # Tool system
    "Tool",
    "ToolContext",
    "ToolResult",
    "ToolRegistry",
    "SimpleToolRegistry",

    # Built-in tools
    "get_builtin_tool_schemas",
    "builtin_executor",
    "create_tool_schema",

    # Bootstrap
    "bootstrap_agent",
]
