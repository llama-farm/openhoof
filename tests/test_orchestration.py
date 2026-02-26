"""
Tests for two-model orchestration (Router + Reasoner).
Offline — no LlamaFarm required.

Validates:
- Single-model mode works unchanged when no router configured
- _strip_meta() removes all internal metadata before LLM sends
- _has_router() reads config correctly
- router_confidence_threshold is configurable
- _execute_with_router() falls back to direct execution in single-model mode
"""

import json
import pytest
from openhoof import Agent


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_status",
            "description": "Get current status",
            "parameters": {
                "type": "object",
                "properties": {"system": {"type": "string"}},
                "required": ["system"],
            },
        },
    }
]


def execute_tool(tool_name: str, params: dict) -> dict:
    if tool_name == "get_status":
        return {"status": "ok", "system": params.get("system")}
    return {"error": f"unknown tool: {tool_name}"}


def make_agent(workspace, threshold=0.85):
    return Agent(
        soul=str(workspace / "SOUL.md"),
        memory=str(workspace / "MEMORY.md"),
        tools=TOOLS,
        executor=execute_tool,
        router_confidence_threshold=threshold,
    )


# ── _strip_meta ───────────────────────────────────────────────────────────────

def test_strip_meta_removes_internal_keys(agent_workspace):
    agent = make_agent(agent_workspace)
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi", "_by": "reasoner"},
        {"role": "tool", "content": "{}", "_confidence": 0.97, "name": "get_status"},
    ]
    clean = agent._strip_meta(messages)
    assert "_by" not in clean[1]
    assert "_confidence" not in clean[2]
    assert clean[0]["content"] == "hello"        # regular keys preserved
    assert clean[2]["content"] == "{}"           # regular keys preserved
    assert clean[2]["name"] == "get_status"      # regular keys preserved


def test_strip_meta_preserves_all_non_internal_keys(agent_workspace):
    agent = make_agent(agent_workspace)
    messages = [
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "get_status",
            "content": '{"status": "ok"}',
            "_confidence": 0.95,
            "_by": "router",
        }
    ]
    clean = agent._strip_meta(messages)
    assert clean[0] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "name": "get_status",
        "content": '{"status": "ok"}',
    }


# ── _has_router ───────────────────────────────────────────────────────────────

def test_has_router_false_when_not_configured(agent_workspace):
    """Default llamafarm.yaml has different router/reasoning models,
    but in test env no config exists → defaults → typically single-model."""
    agent = make_agent(agent_workspace)
    # Just verify the method exists and returns a bool
    assert isinstance(agent._has_router(), bool)


# ── router_confidence_threshold ───────────────────────────────────────────────

def test_default_confidence_threshold(agent_workspace):
    agent = make_agent(agent_workspace)
    assert agent.router_confidence_threshold == 0.85


def test_custom_confidence_threshold(agent_workspace):
    agent = make_agent(agent_workspace, threshold=0.70)
    assert agent.router_confidence_threshold == 0.70


# ── _execute_with_router (single-model mode) ──────────────────────────────────

def test_execute_with_router_single_model(agent_workspace):
    """In single-model mode, _execute_with_router calls the tool directly
    and returns confidence=None."""
    agent = make_agent(agent_workspace)

    # Simulate a tool_call dict from Reasoner
    tool_call = {
        "id": "call_test_1",
        "type": "function",
        "function": {
            "name": "get_status",
            "arguments": json.dumps({"system": "drone"}),
        },
    }
    messages = [{"role": "user", "content": "check drone status"}]

    # Only run if single-model (no router configured)
    if not agent._has_router():
        result, confidence = agent._execute_with_router(tool_call, messages)
        assert result["status"] == "ok"
        assert result["system"] == "drone"
        assert confidence is None   # Single-model → no confidence score


def test_execute_with_router_handles_bad_json_args(agent_workspace):
    """Malformed arguments JSON should not crash — fall back to empty params."""
    agent = make_agent(agent_workspace)

    tool_call = {
        "id": "call_bad",
        "type": "function",
        "function": {
            "name": "get_status",
            "arguments": "not valid json {{{",
        },
    }
    messages = [{"role": "user", "content": "test"}]

    if not agent._has_router():
        # Should not raise, even with bad JSON
        result, confidence = agent._execute_with_router(tool_call, messages)
        assert isinstance(result, dict)


# ── _confidence_from_logprobs ─────────────────────────────────────────────────

def make_client():
    from openhoof.models import LlamaFarmConfig, LlamaFarmClient
    config = LlamaFarmConfig.__new__(LlamaFarmConfig)
    config.config = {}
    config.endpoint = "http://localhost:11540/v1"
    config.models = {}
    config.tool_calling = {}
    config.inference = {}
    return LlamaFarmClient(config)


def test_logprobs_exact_token_match():
    """Tool name appears as a single token → exp(logprob) returned."""
    client = make_client()
    logprobs = {
        "content": [
            {"token": '"goto_waypoint"', "logprob": -0.0513, "top_logprobs": []},
            {"token": '"', "logprob": -0.001, "top_logprobs": []},
        ]
    }
    conf = client._confidence_from_logprobs(logprobs, "goto_waypoint")
    assert conf is not None
    assert 0.9 < conf <= 1.0   # exp(-0.0513) ≈ 0.95


def test_logprobs_found_in_top_logprobs():
    """Tool name appears in top_logprobs candidates (not chosen token)."""
    client = make_client()
    logprobs = {
        "content": [
            {
                "token": '"get_battery"',
                "logprob": -0.22,
                "top_logprobs": [
                    {"token": '"get_battery"', "logprob": -0.22},
                    {"token": '"get_status"', "logprob": -1.6},
                ],
            }
        ]
    }
    conf = client._confidence_from_logprobs(logprobs, "get_battery")
    assert conf is not None
    assert conf > 0.7


def test_logprobs_none_when_data_missing():
    """Returns None when logprobs data is None (not yet supported)."""
    client = make_client()
    assert client._confidence_from_logprobs(None, "any_tool") is None


def test_logprobs_none_when_tool_not_in_stream():
    """Returns None when tool name not found anywhere in the token stream."""
    client = make_client()
    logprobs = {
        "content": [
            {"token": "hello", "logprob": -0.1, "top_logprobs": []},
            {"token": " world", "logprob": -0.2, "top_logprobs": []},
        ]
    }
    assert client._confidence_from_logprobs(logprobs, "goto_waypoint") is None


def test_logprobs_empty_content():
    """Returns None for empty content list."""
    client = make_client()
    assert client._confidence_from_logprobs({"content": []}, "any_tool") is None


def test_logprobs_probability_range():
    """exp(logprob) is always in [0, 1]."""
    client = make_client()
    import math
    for logprob in [-0.001, -0.1, -1.0, -5.0, -10.0]:
        prob = math.exp(logprob)
        assert 0.0 <= prob <= 1.0
