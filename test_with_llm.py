#!/usr/bin/env python3
"""
Test OpenHoof v2.0 agent WITH LLM reasoning.
This actually calls LlamaFarm to decide which tools to call.
"""

import time
from openhoof import Agent


# Simple tools
def get_weather(location: str) -> dict:
    """Get current weather for a location."""
    # Mock response
    weather_data = {
        "Portland": {"temp": 45, "condition": "rainy"},
        "Miami": {"temp": 78, "condition": "sunny"},
        "Chicago": {"temp": 32, "condition": "snowy"}
    }
    result = weather_data.get(location, {"temp": 65, "condition": "unknown"})
    print(f"   ➤ get_weather({location!r}) = {result}")
    return result


def add_numbers(a: int, b: int) -> dict:
    """Add two numbers."""
    result = a + b
    print(f"   ➤ add_numbers({a}, {b}) = {result}")
    return {"result": result}


# Tool schemas (OpenAI format)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name (e.g. 'Portland', 'Miami')"
                    }
                },
                "required": ["location"]
            }
        }
    },
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
    }
]


# Tool executor
def execute_tool(tool_name: str, params: dict) -> dict:
    """Execute a tool by name."""
    if tool_name == "get_weather":
        return get_weather(**params)
    elif tool_name == "add_numbers":
        return add_numbers(**params)
    else:
        return {"error": f"Unknown tool: {tool_name}"}


# Minimal context files
SOUL_CONTENT = """# SOUL.md
- **Name:** WeatherBot
- **Emoji:** 🌤️
- **Mission:** Help users check weather and do simple math
"""

MEMORY_CONTENT = """# MEMORY.md
WeatherBot created 2026-02-20. Knows weather in Portland, Miami, Chicago.
"""


if __name__ == "__main__":
    print("🐴 OpenHoof v2.0 LLM Integration Test\n")
    
    # Write context files
    with open("SOUL.md", "w") as f:
        f.write(SOUL_CONTENT)
    with open("MEMORY.md", "w") as f:
        f.write(MEMORY_CONTENT)
    
    # Create agent
    agent = Agent(
        soul="SOUL.md",
        memory="MEMORY.md",
        tools=TOOLS,
        executor=execute_tool,
        heartbeat_interval=5.0
    )
    
    print("\n🧠 Testing LLM reasoning...\n")
    
    # Test 1: Ask about weather (should call get_weather tool)
    print("=" * 60)
    print("Q: What's the weather in Portland?")
    print("=" * 60)
    response = agent.reason("What's the weather in Portland?")
    print(f"\n📤 LLM Response:\n{response}\n")
    
    # Test 2: Ask for math (should call add_numbers tool)
    print("=" * 60)
    print("Q: What is 42 + 17?")
    print("=" * 60)
    response = agent.reason("What is 42 + 17?")
    print(f"\n📤 LLM Response:\n{response}\n")
    
    print("\n✅ LLM tests complete!")
    print(f"   Tools called: {agent.tools_called}")
    print(f"   Training samples captured: {agent.training.captured_count}")
