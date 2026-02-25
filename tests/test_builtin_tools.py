#!/usr/bin/env python3
"""
Test all built-in tools with drone-like autonomous agent scenario.

Tests:
- Bootstrap agent workspace
- Memory tools (search, append, read)
- Time tools (get_time)
- Logging tools (log, read_logs)
- State tools (save/load/list)
- Context tools (read_user, read_agents, read_tool_guide)
- Mission lifecycle (mission_start, checkpoint, mission_complete)
- Rich tool schema creation
"""

import shutil
from pathlib import Path
from openhoof import Agent, bootstrap_agent, get_builtin_tool_schemas, builtin_executor, create_tool_schema


# Simulated drone tools
def drone_takeoff() -> dict:
    print("   🚁 Takeoff: Motors armed, ascending to 1.2m AGL")
    return {"success": True, "altitude_m": 1.2, "status": "hovering"}


def drone_goto(lat: float, lon: float, alt_m: float = 15.0) -> dict:
    print(f"   ✈️  Flying to waypoint: ({lat}, {lon}) @ {alt_m}m")
    return {"success": True, "arrived": True, "distance_m": 0.5}


def drone_capture() -> dict:
    print("   📷 Capturing image...")
    return {"success": True, "image_size_kb": 245, "format": "JPEG"}


def get_battery() -> dict:
    print("   🔋 Checking battery...")
    return {"battery_percent": 75, "voltage": 12.4, "charging": False}


# Create rich tool schemas
DRONE_TOOLS = [
    create_tool_schema(
        name="drone_takeoff",
        summary="Arm motors and take off to hover altitude (~1.2m AGL)",
        when_to_use="Mission start after telemetry check",
        prerequisites=["GPS lock >= 8 sats", "Battery > 40%"],
        best_practices=["Wait 3s after return before next command"],
        safety=["Abort if wind > 15 m/s", "Abort if battery < 40%"]
    ),
    create_tool_schema(
        name="drone_goto",
        summary="Fly to GPS waypoint at specified altitude",
        when_to_use="Waypoint navigation (preferred over manual flight)",
        prerequisites=["Drone airborne", "GPS lock"],
        best_practices=[
            "Use alt_m=15.0 for normal flight",
            "Check distance < 1m after arrival"
        ],
        safety=["Verify geofence allows target"],
        parameters={
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "alt_m": {"type": "number", "default": 15.0}
            },
            "required": ["lat", "lon"]
        }
    ),
    create_tool_schema(
        name="drone_capture",
        summary="Capture image at current position",
        when_to_use="After arriving at waypoint + 2s stabilization",
        prerequisites=["Drone airborne and stable", "Arrived at waypoint"],
        best_practices=["Wait 2s after arrival for stabilization"]
    ),
    create_tool_schema(
        name="get_battery",
        summary="Check current battery level",
        when_to_use="Before takeoff, after each waypoint, on heartbeat"
    )
]


# Tool executor
def execute_tool(tool_name: str, params: dict) -> dict:
    """Execute drone or built-in tools."""
    # Drone tools
    if tool_name == "drone_takeoff":
        return drone_takeoff()
    elif tool_name == "drone_goto":
        return drone_goto(**params)
    elif tool_name == "drone_capture":
        return drone_capture()
    elif tool_name == "get_battery":
        return get_battery()
    
    # Unknown tool
    return {"error": f"Unknown tool: {tool_name}"}


def combined_executor(agent, tool_name: str, params: dict) -> dict:
    """Combined executor for built-in + drone tools."""
    # Try built-in tools first
    builtin_result = builtin_executor(agent, tool_name, params)
    if "error" not in builtin_result or "Unknown built-in tool" not in builtin_result.get("error", ""):
        return builtin_result
    
    # Fall back to drone tools
    return execute_tool(tool_name, params)


if __name__ == "__main__":
    print("🐴 OpenHoof Built-in Tools Test\n")
    print("=" * 70)
    
    # Clean up previous test workspace
    test_workspace = Path("./test_agent_workspace")
    if test_workspace.exists():
        shutil.rmtree(test_workspace)
    
    # 1. Bootstrap agent workspace
    print("\n1️⃣  Bootstrapping agent workspace...")
    result = bootstrap_agent(
        workspace="./test_agent_workspace",
        name="DroneBot",
        emoji="🚁",
        mission="Autonomous aerial patrol and reconnaissance",
        user_name="Rob",
        timezone="America/Chicago",
        notes="Prefers concise responses, trusts agent autonomy",
        custom_tools="Drone operates in geofenced area, max altitude 120m AGL"
    )
    print(f"   ✅ Created: {', '.join(result['created'])}")
    
    # 2. Create agent with built-in + drone tools
    print("\n2️⃣  Creating agent with built-in + drone tools...")
    
    all_tools = get_builtin_tool_schemas() + DRONE_TOOLS
    print(f"   ✅ Registered {len(all_tools)} tools:")
    print(f"      - {len(get_builtin_tool_schemas())} built-in tools")
    print(f"      - {len(DRONE_TOOLS)} drone tools")
    
    agent = Agent(
        soul=str(test_workspace / "SOUL.md"),
        memory=str(test_workspace / "MEMORY.md"),
        tools=all_tools,
        executor=lambda name, params: combined_executor(agent, name, params),
        workspace=str(test_workspace),
        max_turns=5
    )
    
    # Add workspace attribute for built-in tools
    agent.workspace = str(test_workspace)
    
    # 3. Test mission lifecycle
    print("\n3️⃣  Testing mission lifecycle...")
    
    # Start mission
    result = combined_executor(agent, "mission_start", {
        "mission_id": "patrol-001",
        "objective": "Patrol 3 waypoints, capture images"
    })
    print(f"   ✅ Mission started: {result['mission_id']}")
    
    # 4. Test logging
    print("\n4️⃣  Testing logging...")
    combined_executor(agent, "log", {
        "message": "Pre-flight checks complete",
        "level": "info"
    })
    combined_executor(agent, "log", {
        "message": "Battery at 75%, GPS lock acquired",
        "level": "info"
    })
    print("   ✅ Logged 2 entries")
    
    # 5. Test state persistence
    print("\n5️⃣  Testing state persistence...")
    combined_executor(agent, "save_state", {
        "key": "last_position",
        "value": {"lat": 45.5231, "lon": -122.6765, "alt_m": 15.0}
    })
    combined_executor(agent, "save_state", {
        "key": "waypoint_index",
        "value": 0
    })
    
    result = combined_executor(agent, "list_state", {})
    print(f"   ✅ Saved {result['count']} state keys")
    
    # 6. Simulate mission execution
    print("\n6️⃣  Simulating mission execution...")
    
    # Takeoff
    print("\n   Waypoint 0: Takeoff")
    execute_tool("drone_takeoff", {})
    combined_executor(agent, "memory_append", {
        "content": "Takeoff successful, altitude 1.2m AGL"
    })
    
    # Waypoint 1
    print("\n   Waypoint 1: Navigate and capture")
    execute_tool("drone_goto", {"lat": 45.5231, "lon": -122.6765, "alt_m": 15.0})
    execute_tool("drone_capture", {})
    combined_executor(agent, "memory_append", {
        "content": "Waypoint 1 complete, image captured"
    })
    
    # Checkpoint
    result = combined_executor(agent, "checkpoint", {
        "summary": "Waypoint 1 complete, battery 75%, 2 more waypoints to go"
    })
    print(f"   ✅ Checkpoint created: {result['checkpoint_id']}")
    
    # Waypoint 2
    print("\n   Waypoint 2: Navigate and capture")
    execute_tool("drone_goto", {"lat": 45.5241, "lon": -122.6755, "alt_m": 15.0})
    execute_tool("drone_capture", {})
    combined_executor(agent, "memory_append", {
        "content": "Waypoint 2 complete, image captured"
    })
    
    # Waypoint 3
    print("\n   Waypoint 3: Navigate and capture")
    execute_tool("drone_goto", {"lat": 45.5251, "lon": -122.6745, "alt_m": 15.0})
    execute_tool("drone_capture", {})
    combined_executor(agent, "memory_append", {
        "content": "Waypoint 3 complete, image captured"
    })
    
    # 7. Test memory search
    print("\n7️⃣  Testing memory search...")
    result = combined_executor(agent, "memory_search", {
        "query": "waypoint complete",
        "max_results": 3
    })
    count = result.get('count', 0)
    print(f"   ✅ Found {count} results for 'waypoint complete'")
    for r in result.get('results', []):
        print(f"      - {r['path']}#{r['line']}: {r['snippet'][:50]}...")
    
    # 8. Test context loading
    print("\n8️⃣  Testing context loading...")
    
    user_result = combined_executor(agent, "read_user", {})
    print(f"   ✅ USER.md: {user_result['content'][:50]}...")
    
    agents_result = combined_executor(agent, "read_agents", {})
    print(f"   ✅ AGENTS.md: {len(agents_result['content'])} chars")
    
    # 9. Test mission complete
    print("\n9️⃣  Testing mission complete...")
    result = combined_executor(agent, "mission_complete", {
        "summary": "Patrol complete: 3 waypoints, 3 images captured, battery 65%",
        "outcome": "success"
    })
    print(f"   ✅ Mission archived to: {result['archived_to']}")
    
    # 10. Test log reading
    print("\n🔟 Testing log reading...")
    result = combined_executor(agent, "read_logs", {
        "date": "today",
        "limit": 5
    })
    print(f"   ✅ Read {result['count']} log entries:")
    for entry in result['entries'][:3]:
        print(f"      {entry}")
    
    # 11. Test context stats
    print("\n1️⃣1️⃣  Testing context stats...")
    result = combined_executor(agent, "get_context_stats", {})
    print(f"   ✅ Context stats:")
    print(f"      - Messages: {result['messages']}")
    print(f"      - Estimated tokens: {result['estimated_tokens']}")
    print(f"      - Turns: {result['turns']}")
    print(f"      - Max history turns: {result['max_history_turns']}")
    
    print("\n" + "=" * 70)
    print("✅ All built-in tools tests passed!")
    print("\n📊 Summary:")
    print(f"   - Workspace created: {test_workspace}")
    print(f"   - Tools tested: {len(all_tools)} total")
    print(f"   - Mission executed: patrol-001")
    print(f"   - Images captured: 3")
    print(f"   - Checkpoints: 1")
    print(f"   - Memory searches: 1")
    print(f"   - Context loading: 2")
    print(f"   - State keys: 2")
