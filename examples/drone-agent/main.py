#!/usr/bin/env python3
"""
drone-agent — Autonomous drone agent example.

Demonstrates:
- Two-model orchestration (Qwen3 Reasoner + FunctionGemma router)
- HTTP direct to drone API (not CLI) — the real execution path
- Mission lifecycle: start → waypoints → checkpoint → complete
- DDIL: continues when network drops, syncs when it returns
- Training data capture: router_YYYY.jsonl + reasoner_YYYY.jsonl

Architecture:
    User task → Reasoner (chains tool calls)
                    ↓ (each step)
               FunctionGemma (validates params, normalizes, <300ms)
                    ↓
               http_request to drone API

Usage:
    cd examples/drone-agent
    pip install openhoof requests
    # Edit DRONE_API_BASE below to point at your drone controller
    python main.py
"""

from pathlib import Path
from openhoof import Agent, get_builtin_tool_schemas, builtin_executor, create_tool_schema

HERE = Path(__file__).parent

# ── Drone API endpoint ────────────────────────────────────────────────────────
# Point this at your drone controller (DJI MSDK, ArduPilot, etc.)
DRONE_API_BASE = "http://drone.local:8080/api/v1"


# ── Drone tools — HTTP direct (not shell) ─────────────────────────────────────

def drone_executor(agent, tool_name: str, params: dict) -> dict:
    """Route drone tool calls to the HTTP API directly."""
    from openhoof.builtin_tools.http_tools import http_request

    # Map tool names to HTTP endpoints
    routes = {
        "drone_takeoff":        ("POST", "/takeoff"),
        "drone_land":           ("POST", "/land"),
        "drone_hover":          ("POST", "/hover"),
        "drone_goto":           ("POST", "/goto"),
        "drone_move_relative":  ("POST", "/move"),
        "drone_scan":           ("POST", "/scan"),
        "drone_capture":        ("POST", "/capture"),
        "drone_get_telemetry":  ("GET",  "/telemetry"),
        "drone_get_battery":    ("GET",  "/battery"),
        "drone_set_gimbal":     ("POST", "/gimbal"),
        "drone_start_video":    ("POST", "/video/start"),
        "drone_stop_video":     ("POST", "/video/stop"),
    }

    if tool_name not in routes:
        # Not a drone tool — fall back to built-in executor
        return builtin_executor(agent, tool_name, params)

    method, path = routes[tool_name]
    return http_request(
        agent,
        url=f"{DRONE_API_BASE}{path}",
        method=method,
        body=params if method != "GET" else None,
        params=params if method == "GET" else None,
        timeout=10,
    )


# ── Tool schemas ──────────────────────────────────────────────────────────────

DRONE_TOOLS = [
    create_tool_schema(
        name="drone_takeoff",
        summary="Arm motors and take off to hover altitude (~1.5m AGL)",
        when_to_use="Start of every mission after preflight checks pass",
        safety=["Abort if battery < 25%", "Abort if GPS sats < 6", "Clear area of people"],
    ),
    create_tool_schema(
        name="drone_land",
        summary="Land at current position",
        when_to_use="Mission complete, low battery, or operator abort",
        safety=["Verify landing zone is clear"],
    ),
    create_tool_schema(
        name="drone_hover",
        summary="Hold current position and altitude",
        when_to_use="Pause before maneuver, waiting for scan result, stabilization",
    ),
    create_tool_schema(
        name="drone_goto",
        summary="Fly to GPS waypoint at specified altitude",
        when_to_use="Waypoint navigation",
        prerequisites=["Drone airborne", "GPS lock"],
        parameters={
            "type": "object",
            "properties": {
                "lat":   {"type": "number", "description": "Latitude"},
                "lon":   {"type": "number", "description": "Longitude"},
                "alt_m": {"type": "number", "description": "Altitude MSL in meters", "default": 30},
            },
            "required": ["lat", "lon"],
        },
    ),
    create_tool_schema(
        name="drone_move_relative",
        summary="Move relative to current position (forward/back/left/right/up/down)",
        when_to_use="Fine positioning, altitude adjustment, obstacle avoidance",
        parameters={
            "type": "object",
            "properties": {
                "x_m":   {"type": "number", "description": "Forward(+)/back(-) meters"},
                "y_m":   {"type": "number", "description": "Right(+)/left(-) meters"},
                "z_m":   {"type": "number", "description": "Up(+)/down(-) meters"},
            },
            "required": [],
        },
    ),
    create_tool_schema(
        name="drone_scan",
        summary="Scan area using onboard detector — returns detected objects",
        when_to_use="Searching for targets, object detection, area survey",
        parameters={
            "type": "object",
            "properties": {
                "lock_on_class": {"type": "string", "description": "Object class to detect (person, vehicle, horse, etc.)"},
                "confidence":    {"type": "number", "description": "Min detection confidence 0-1", "default": 0.7},
            },
            "required": [],
        },
    ),
    create_tool_schema(
        name="drone_capture",
        summary="Capture image at current position and altitude",
        when_to_use="After arriving at waypoint and 2s stabilization",
        prerequisites=["Hovering and stable for ≥2s"],
    ),
    create_tool_schema(
        name="drone_get_telemetry",
        summary="Get current position, altitude, heading, speed",
        when_to_use="Heartbeat, before navigation decisions, after maneuvers",
    ),
    create_tool_schema(
        name="drone_get_battery",
        summary="Get battery percentage and voltage",
        when_to_use="Preflight, heartbeat, before long-distance waypoints",
    ),
    create_tool_schema(
        name="drone_set_gimbal",
        summary="Set camera gimbal pitch angle",
        when_to_use="Before capture — nadir for survey, angled for follow",
        parameters={
            "type": "object",
            "properties": {
                "pitch_deg": {"type": "number", "description": "-90 (nadir/straight down) to 0 (forward)"},
            },
            "required": ["pitch_deg"],
        },
    ),
    create_tool_schema(
        name="drone_start_video",
        summary="Start video recording",
        when_to_use="Beginning of follow mission or video survey",
    ),
    create_tool_schema(
        name="drone_stop_video",
        summary="Stop video recording",
        when_to_use="End of follow mission or when storage < 10% free",
    ),
]

ALL_TOOLS = get_builtin_tool_schemas() + DRONE_TOOLS


def main():
    agent = Agent(
        soul=str(HERE / "SOUL.md"),
        memory=str(HERE / "MEMORY.md"),
        tools=ALL_TOOLS,
        executor=lambda name, params: drone_executor(agent, name, params),
        workspace=str(HERE),
        max_turns=15,  # multi-step missions need room
    )

    print("🚁 DroneBot ready.\n")
    print("Example commands:")
    print("  take off and hover at 30m")
    print("  fly to 45.5231, -122.6765 and capture an image")
    print("  scan for horses and follow them")
    print("  land now\n")

    while True:
        try:
            user_input = input("Mission: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nOperator disconnected. Drone holding position.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        response = agent.reason(user_input)
        content = response.get("content", "")
        print(f"\n🚁 {content}\n")


if __name__ == "__main__":
    main()
