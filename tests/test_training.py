"""
Tests for training data capture — router vs reasoner split.
Offline — no LlamaFarm required.
"""

import json
import pytest
from openhoof.training import TrainingDataCapture


@pytest.fixture
def capture(tmp_path):
    return TrainingDataCapture(output_dir=str(tmp_path / "training"))


# ── capture_router ─────────────────────────────────────────────────────────────

def test_router_sample_written(capture, tmp_path):
    capture.capture_router(
        user_intent="scan for person",
        tool_name="drone_scan",
        tool_params={"lock_on_class": "person"},
        confidence=0.95,
        agreed=True,
    )
    samples = capture.load(model="router")
    assert len(samples) == 1
    s = samples[0]
    assert s["model"] == "router"
    assert s["tool_call"]["name"] == "drone_scan"
    assert s["tool_call"]["arguments"]["lock_on_class"] == "person"
    assert s["confidence"] == 0.95
    assert s["agreed"] is True


def test_router_sample_single_turn(capture):
    """Router samples must be single-turn — no multi-step context."""
    capture.capture_router(
        user_intent="get battery level",
        tool_name="get_battery",
        tool_params={},
    )
    samples = capture.load(model="router")
    messages = samples[0]["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


def test_router_sample_no_confidence_when_not_provided(capture):
    capture.capture_router("fly north", "drone_move", {"direction": "N"})
    samples = capture.load(model="router")
    assert "confidence" not in samples[0]


# ── capture_reasoner ───────────────────────────────────────────────────────────

def test_reasoner_sample_written(capture):
    messages = [
        {"role": "user", "content": "find horses and follow them"},
        {"role": "assistant", "tool_calls": [{"function": {"name": "scan_area"}}]},
        {"role": "tool", "content": '{"targets": ["horse1", "horse2"]}'},
        {"role": "assistant", "tool_calls": [{"function": {"name": "drone_follow"}}]},
        {"role": "tool", "content": '{"status": "following"}'},
        {"role": "assistant", "content": "Locked on 2 horses. Following."},
    ]
    capture.capture_reasoner(messages=messages, system_prompt="You are DroneBot.")

    samples = capture.load(model="reasoner")
    assert len(samples) == 1
    s = samples[0]
    assert s["model"] == "reasoner"
    assert s["turn_count"] == 2   # 2 assistant messages with tool_calls
    assert s["messages"][0]["role"] == "system"   # system prompt prepended


def test_reasoner_sample_turn_count(capture):
    """turn_count = number of tool-calling turns, not total messages."""
    messages = [
        {"role": "user", "content": "do three things"},
        {"role": "assistant", "tool_calls": [{}]},
        {"role": "tool", "content": "r1"},
        {"role": "assistant", "tool_calls": [{}]},
        {"role": "tool", "content": "r2"},
        {"role": "assistant", "tool_calls": [{}]},
        {"role": "tool", "content": "r3"},
        {"role": "assistant", "content": "done"},
    ]
    capture.capture_reasoner(messages=messages)
    assert capture.load(model="reasoner")[0]["turn_count"] == 3


# ── separation ─────────────────────────────────────────────────────────────────

def test_router_and_reasoner_go_to_separate_files(capture):
    capture.capture_router("scan", "drone_scan", {})
    capture.capture_reasoner([{"role": "user", "content": "task"}])

    router = capture.load(model="router")
    reasoner = capture.load(model="reasoner")

    assert len(router) == 1
    assert len(reasoner) == 1
    assert router[0]["model"] == "router"
    assert reasoner[0]["model"] == "reasoner"


def test_load_all_returns_both(capture):
    capture.capture_router("scan", "drone_scan", {})
    capture.capture_reasoner([{"role": "user", "content": "task"}])
    all_samples = capture.load(model="all")
    assert len(all_samples) == 2


# ── stats ──────────────────────────────────────────────────────────────────────

def test_stats_counts_correctly(capture):
    capture.capture_router("a", "tool_a", {})
    capture.capture_router("b", "tool_b", {})
    capture.capture_reasoner([{"role": "user", "content": "chain"}])

    stats = capture.stats()
    assert stats["router_samples"] == 2
    assert stats["reasoner_samples"] == 1
    assert stats["total"] == 3


def test_stats_empty(capture):
    stats = capture.stats()
    assert stats["router_samples"] == 0
    assert stats["reasoner_samples"] == 0
    assert stats["total"] == 0
