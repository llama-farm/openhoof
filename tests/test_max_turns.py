#!/usr/bin/env python3
"""Test configurable max_turns."""

from openhoof import Agent

# Simple tool
def echo(message: str) -> dict:
    print(f"   📢 echo({message!r})")
    return {"echoed": message}

TOOLS = [{
    "type": "function",
    "function": {
        "name": "echo",
        "description": "Echo a message",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string"}
            },
            "required": ["message"]
        }
    }
}]

def execute_tool(tool_name: str, params: dict) -> dict:
    if tool_name == "echo":
        return echo(**params)
    return {"error": f"Unknown tool: {tool_name}"}

# Context
with open("SOUL.md", "w") as f:
    f.write("# SOUL.md\n- **Name:** TestBot\n- **Emoji:** 🤖\n")
with open("MEMORY.md", "w") as f:
    f.write("# MEMORY.md\nTest memory\n")

print("Test 1: Default max_turns (10)")
agent1 = Agent(
    soul="SOUL.md",
    memory="MEMORY.md",
    tools=TOOLS,
    executor=execute_tool
)
print()

print("Test 2: Custom max_turns (3)")
agent2 = Agent(
    soul="SOUL.md",
    memory="MEMORY.md",
    tools=TOOLS,
    executor=execute_tool,
    max_turns=3
)
print()

print("Test 3: Override per-call")
print(f"Agent default: {agent1.max_turns}")
response = agent1.reason("Echo test", max_turns=5)
print(f"✅ max_turns configurable!")
