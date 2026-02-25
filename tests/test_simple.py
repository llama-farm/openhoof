"""
Tests for OpenHoof v2.0 core agent functionality.
Offline — no LlamaFarm required.
Tests: Agent init, tool registry, heartbeat, event loop, graceful shutdown.
"""

import time
import pytest
from openhoof import Agent


# --- Tools ---

def add_numbers(a: int, b: int) -> dict:
    return {"result": a + b}


def get_time_tool() -> dict:
    return {"timestamp": time.time()}


SIMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_numbers",
            "description": "Add two numbers",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_time_tool",
            "description": "Get current Unix timestamp",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def execute_tool(tool_name: str, params: dict) -> dict:
    if tool_name == "add_numbers":
        return add_numbers(**params)
    elif tool_name == "get_time_tool":
        return get_time_tool()
    return {"error": f"Unknown tool: {tool_name}"}


# --- Tests ---

def test_agent_initializes(agent_workspace):
    """Agent initializes with soul, memory, tools."""
    agent = Agent(
        soul=str(agent_workspace / "SOUL.md"),
        memory=str(agent_workspace / "MEMORY.md"),
        tools=SIMPLE_TOOLS,
        executor=execute_tool,
    )
    assert agent is not None
    assert agent.max_turns == 10  # default


def test_tool_registry(agent_workspace):
    """Tool registry registers and can list tools."""
    agent = Agent(
        soul=str(agent_workspace / "SOUL.md"),
        memory=str(agent_workspace / "MEMORY.md"),
        tools=SIMPLE_TOOLS,
        executor=execute_tool,
    )
    schemas = agent.tools.to_schema()
    names = [s["function"]["name"] for s in schemas]
    assert "add_numbers" in names
    assert "get_time_tool" in names


def test_tool_execution(agent_workspace):
    """Tools execute and return correct results."""
    agent = Agent(
        soul=str(agent_workspace / "SOUL.md"),
        memory=str(agent_workspace / "MEMORY.md"),
        tools=SIMPLE_TOOLS,
        executor=execute_tool,
    )
    result = agent.call_tool("add_numbers", {"a": 5, "b": 3})
    assert result["result"] == 8


def test_heartbeat_system(agent_workspace):
    """Heartbeat initializes and tracks beat count."""
    agent = Agent(
        soul=str(agent_workspace / "SOUL.md"),
        memory=str(agent_workspace / "MEMORY.md"),
        tools=SIMPLE_TOOLS,
        executor=execute_tool,
        heartbeat_interval=0.1,
    )
    assert agent.heartbeat is not None
    assert agent.heartbeat.beat_count == 0


def test_exit_condition_stops_loop(agent_workspace):
    """Agent stops when exit condition is met."""
    agent = Agent(
        soul=str(agent_workspace / "SOUL.md"),
        memory=str(agent_workspace / "MEMORY.md"),
        tools=SIMPLE_TOOLS,
        executor=execute_tool,
        heartbeat_interval=0.05,
    )
    agent.on_exit("immediate", lambda: True)  # Exit immediately
    agent.run()  # Should return quickly
    assert True  # If we get here, exit worked


def test_event_queue(agent_workspace):
    """Events can be pushed to the queue."""
    agent = Agent(
        soul=str(agent_workspace / "SOUL.md"),
        memory=str(agent_workspace / "MEMORY.md"),
        tools=SIMPLE_TOOLS,
        executor=execute_tool,
    )
    agent.push_event("test_event", {"data": "hello"}, priority=0.9)
    assert agent.events.size() > 0
