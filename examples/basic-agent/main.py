#!/usr/bin/env python3
"""
basic-agent — Minimal OpenHoof agent example.

The simplest possible agent: SOUL.md + MEMORY.md + built-in tools.
No custom tools. No LlamaFarm required for the single-model fallback.

Usage:
    cd examples/basic-agent
    pip install openhoof
    python main.py

To use with LlamaFarm (two-model mode), copy llamafarm.yaml from
the repo root and adjust endpoints.
"""

import os
from pathlib import Path
from openhoof import Agent, get_builtin_tool_schemas, builtin_executor

HERE = Path(__file__).parent


def main():
    # All context files live next to this script
    agent = Agent(
        soul=str(HERE / "SOUL.md"),
        memory=str(HERE / "MEMORY.md"),
        tools=get_builtin_tool_schemas(),
        executor=lambda name, params: builtin_executor(agent, name, params),
        workspace=str(HERE),
    )

    print("🐴 Basic Agent ready. Type a message, or 'quit' to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        response = agent.reason(user_input)
        content = response.get("content", "")
        print(f"\nAgent: {content}\n")


if __name__ == "__main__":
    main()
