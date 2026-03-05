#!/usr/bin/env python3
"""
orchestrator — Multi-specialist coordinator.

Demonstrates:
- Triage → delegate → synthesize pattern
- Sequential specialist tool calls based on event type
- spawn_agent / get_agent_result for sub-agent coordination

In this example, specialists are simulated locally.
In production, replace with real Agent instances or http_request to agent APIs.

Usage:
    cd examples/orchestrator
    pip install openhoof
    python main.py
"""

import json
import time
from pathlib import Path
from openhoof import Agent, get_builtin_tool_schemas, builtin_executor, create_tool_schema

HERE = Path(__file__).parent

# ── Simulated specialist agents ────────────────────────────────────────────────

_TASK_RESULTS: dict = {}


def _simulate_fuel_analyst(task: str, context: dict) -> dict:
    """Stub — replace with real fuel-analyst agent call."""
    burn_ratio = context.get("burn_ratio", 1.0)
    if burn_ratio > 1.12:
        return {
            "status": "RED",
            "summary": f"Burn ratio {burn_ratio:.2f} — 12% above planned. Recommend divert to LPPD (180nm). Reserve margin: 8%.",
            "action": "DIVERT",
            "alternates": ["LPPD", "LPMA"],
        }
    elif burn_ratio > 1.05:
        return {
            "status": "AMBER",
            "summary": f"Burn ratio {burn_ratio:.2f} — 5% above planned. Reduce power setting FL+2000 or reduce speed 10kt.",
            "action": "REDUCE_POWER",
        }
    return {"status": "GREEN", "summary": "Fuel state nominal.", "action": "CONTINUE"}


def _simulate_intel_analyst(task: str, context: dict) -> dict:
    """Stub — replace with real intel-analyst agent call."""
    route = context.get("route", "unknown")
    return {
        "threat_level": "LOW",
        "summary": f"Route {route}: no known threats. SIGINT clear. Recommend continue.",
        "action": "CONTINUE",
    }


def _simulate_mx_specialist(task: str, context: dict) -> dict:
    """Stub — replace with real mx-specialist agent call."""
    system = context.get("system", "unknown")
    return {
        "assessment": "MONITOR",
        "summary": f"{system}: degraded but mission-capable. Log discrepancy post-flight.",
        "action": "CONTINUE_WITH_MONITORING",
    }


_SPECIALISTS = {
    "fuel-analyst":   _simulate_fuel_analyst,
    "intel-analyst":  _simulate_intel_analyst,
    "mx-specialist":  _simulate_mx_specialist,
}


def spawn_agent(agent_id: str, task: str, context: dict | None = None) -> dict:
    if agent_id not in _SPECIALISTS:
        return {"error": f"Unknown specialist: {agent_id}. Available: {list(_SPECIALISTS)}"}
    task_id = f"{agent_id}-{int(time.time())}"
    result = _SPECIALISTS[agent_id](task, context or {})
    _TASK_RESULTS[task_id] = result
    return {"task_id": task_id, "status": "complete", "result": result}


def get_agent_result(task_id: str) -> dict:
    result = _TASK_RESULTS.get(task_id)
    if not result:
        return {"error": f"Task {task_id} not found or not yet complete"}
    return {"task_id": task_id, "result": result}


# ── Tool schemas ──────────────────────────────────────────────────────────────

ORCH_TOOLS = [
    create_tool_schema(
        name="spawn_agent",
        summary="Spawn a specialist agent with a task and context",
        when_to_use="After triage identifies which domain(s) are affected",
        parameters={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Specialist ID",
                    "enum": ["fuel-analyst", "intel-analyst", "mx-specialist"],
                },
                "task":    {"type": "string", "description": "Clear, specific task description"},
                "context": {"type": "object", "description": "Relevant data from the event"},
            },
            "required": ["agent_id", "task"],
        },
    ),
    create_tool_schema(
        name="get_agent_result",
        summary="Retrieve the result from a previously spawned specialist",
        when_to_use="After spawn_agent if result was not returned inline",
        parameters={
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    ),
]

ALL_TOOLS = get_builtin_tool_schemas() + ORCH_TOOLS
TOOL_FNS = {"spawn_agent": spawn_agent, "get_agent_result": get_agent_result}


def executor(agent, tool_name, params):
    if tool_name in TOOL_FNS:
        return TOOL_FNS[tool_name](**params)
    return builtin_executor(agent, tool_name, params)


# ── Demo events ────────────────────────────────────────────────────────────────

DEMO_EVENTS = [
    {
        "label": "Fuel anomaly — single domain",
        "event": "MAY101 reporting fuel burn ratio 1.15 for past 45 minutes. Current fuel 145,000 lbs, destination OKBK 3,200nm.",
    },
    {
        "label": "Multi-domain — fuel + comms",
        "event": "MAY101: SATCOM degraded (backup HF available), fuel burn ratio 1.08, en route OKBK.",
    },
    {
        "label": "Equipment issue",
        "event": "MAY102: #3 engine anti-ice light illuminated intermittently. No performance impact observed.",
    },
]


def main():
    agent = Agent(
        soul=str(HERE / "SOUL.md"),
        memory=str(HERE / "MEMORY.md"),
        tools=ALL_TOOLS,
        executor=lambda name, params: executor(agent, name, params),
        workspace=str(HERE),
        max_turns=12,
    )

    print("🎯 Mission Orchestrator ready.\n")
    print("Demo events:")
    for i, e in enumerate(DEMO_EVENTS):
        print(f"  {i+1}. {e['label']}")
    print("  Or type a custom event.\n")

    while True:
        try:
            user_input = input("Event: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession ended.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            break

        # Allow selecting demo events by number
        if user_input.isdigit():
            idx = int(user_input) - 1
            if 0 <= idx < len(DEMO_EVENTS):
                user_input = DEMO_EVENTS[idx]["event"]
                print(f"→ {user_input}\n")

        response = agent.reason(user_input)
        print(f"\n🎯 {response.get('content', '')}\n")


if __name__ == "__main__":
    main()
