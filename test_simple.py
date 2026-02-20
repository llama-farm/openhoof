#!/usr/bin/env python3
"""
Simple test to prove OpenHoof v2.0 agent actually works.
Tests: agent loop, tool calling, heartbeat, graceful shutdown.
"""

import time
from openhoof import Agent, Soul, Memory


# 1. Simple tools (just functions)
def add_numbers(a: int, b: int) -> dict:
    """Add two numbers."""
    result = a + b
    print(f"   ➤ add_numbers({a}, {b}) = {result}")
    return {"result": result}


def get_time() -> dict:
    """Get current timestamp."""
    now = time.time()
    print(f"   ➤ get_time() = {now}")
    return {"timestamp": now}


# 2. Tool schemas (OpenAI format)
SIMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_numbers",
            "description": "Add two numbers",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer", "description": "First number"},
                    "b": {"type": "integer", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Get current Unix timestamp",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]


# 3. Tool executor (maps tool names to functions)
def execute_tool(tool_name: str, params: dict) -> dict:
    """Execute a tool by name."""
    if tool_name == "add_numbers":
        return add_numbers(**params)
    elif tool_name == "get_time":
        return get_time()
    else:
        return {"error": f"Unknown tool: {tool_name}"}


# 4. Create minimal context files
SOUL_CONTENT = """# SOUL.md
- **Name:** TestBot
- **Emoji:** 🤖
- **Mission:** Test OpenHoof v2.0 agent runtime
"""

MEMORY_CONTENT = """# MEMORY.md
Test agent memory — created during simple test.
"""


if __name__ == "__main__":
    print("🐴 OpenHoof v2.0 Simple Test\n")
    
    # Write context files
    with open("SOUL.md", "w") as f:
        f.write(SOUL_CONTENT)
    with open("MEMORY.md", "w") as f:
        f.write(MEMORY_CONTENT)
    
    # Create agent
    agent = Agent(
        soul="SOUL.md",
        memory="MEMORY.md",
        tools=SIMPLE_TOOLS,
        executor=execute_tool,
        heartbeat_interval=2.0  # Beat every 2 seconds for quick test
    )
    
    # Add exit condition (stop after 3 heartbeats)
    agent.on_exit("max_heartbeats", lambda: agent.heartbeat.beat_count >= 3)
    
    # Push some test events
    print("\n📤 Pushing test events...")
    agent.push_event("tool_call", {"tool": "get_time", "params": {}}, priority=0.8)
    agent.push_event("tool_call", {"tool": "add_numbers", "params": {"a": 5, "b": 3}}, priority=0.9)
    agent.push_event("tool_call", {"tool": "add_numbers", "params": {"a": 100, "b": 42}}, priority=0.5)
    
    # Run agent (blocks until exit condition)
    print("\n▶️  Starting agent loop...\n")
    agent.run()
    
    print("\n✅ Test complete!")
    print(f"   Events processed: {agent.events_processed}")
    print(f"   Tools called: {agent.tools_called}")
    print(f"   Heartbeats: {agent.heartbeat.beat_count}")
