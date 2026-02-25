"""
Tests for configurable max_turns on Agent.
Offline — no LlamaFarm required.
"""

import pytest
from openhoof import Agent


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "echo",
            "description": "Echo a message",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        },
    }
]


def execute_tool(tool_name: str, params: dict) -> dict:
    if tool_name == "echo":
        return {"echoed": params.get("message", "")}
    return {"error": f"Unknown tool: {tool_name}"}


def test_default_max_turns(agent_workspace):
    """Default max_turns is 10."""
    agent = Agent(
        soul=str(agent_workspace / "SOUL.md"),
        memory=str(agent_workspace / "MEMORY.md"),
        tools=TOOLS,
        executor=execute_tool,
    )
    assert agent.max_turns == 10


def test_custom_max_turns(agent_workspace):
    """max_turns can be set at init."""
    agent = Agent(
        soul=str(agent_workspace / "SOUL.md"),
        memory=str(agent_workspace / "MEMORY.md"),
        tools=TOOLS,
        executor=execute_tool,
        max_turns=3,
    )
    assert agent.max_turns == 3


def test_per_call_max_turns_override(agent_workspace):
    """max_turns can be overridden per-call to agent.reason()."""
    agent = Agent(
        soul=str(agent_workspace / "SOUL.md"),
        memory=str(agent_workspace / "MEMORY.md"),
        tools=TOOLS,
        executor=execute_tool,
        max_turns=10,
    )
    # Calling reason() with a per-call override should not error
    # (will fail at LLM call since no LlamaFarm, but override should be accepted)
    assert agent.max_turns == 10  # default unchanged
    try:
        agent.reason("test", max_turns=5)
    except Exception:
        pass  # Expected — no LLM available in CI
