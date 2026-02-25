# Reddit Post — r/LocalLLaMA

---

**TITLE:**
We rebuilt our LLM agent framework from a server into a pip library that runs on-device — `pip install openhoof`

---

**BODY:**

TL;DR: OpenHoof started as a server framework for routing tool calls via a fine-tuned FunctionGemma model. The drone team needed it to run on an Android phone with no internet. So we tore it down and rebuilt it as a standalone library. Now `pip install openhoof` and your agent runs anywhere — phone, laptop, edge device, Rust daemon.

---

We had a working v1: fire a webhook → OpenHoof spins up a session → FunctionGemma routes the call (<300ms) → returns result. Fast, accurate, worked great as a backend.

Then the drone team said: "we need the agent to fly a mission autonomously. No gateway. No server. No internet. Just a phone and a model."

v1 couldn't do that. It was a server. So we rebuilt it.

---

**The two problems we actually had to solve:**

**1. Token budget on mobile is brutal**

Most agent frameworks load everything into the system prompt at session start: SOUL.md, AGENTS.md, USER.md, TOOLS.md, MEMORY.md. On a 128k context desktop model, fine. On a 1B phone model with 2,048 tokens total, you've blown the budget before the first message.

Our fix: system prompt is ~200 tokens (just the agent's core identity). Everything else is lazy-loaded via built-in tools when the agent actually needs it.

```python
# Instead of injecting 2000 tokens of memory upfront:
memory_search("last waypoint altitude")  # Returns 3 relevant snippets (~80 tokens)
read_agents()    # Load AGENTS.md only when the agent needs to check instructions
read_tool_guide("drone_goto")  # Load tool guidance only when planning navigation
```

95% of context window available for actual work instead of overhead.

**2. No network ≠ broken agent**

DDIL (Denied, Degraded, Intermittent, Limited) is real. Drone over a forest. Sensor in a basement. We built store-and-forward buffering in from the start — data buffers locally when offline, syncs when connectivity returns. The agent loop keeps running on local models the whole time.

---

**The multi-turn loop:**

```python
agent = Agent(
    soul="SOUL.md",      # ~200 token system prompt
    memory="MEMORY.md",
    tools=get_builtin_tool_schemas() + drone_tools,
    executor=drone_executor,
    max_turns=10
)

response = agent.reason("Execute patrol: 5 waypoints, capture images at each")
```

What actually happens:

```
Turn 1: → get_battery() → 75%
Turn 2: → mission_start("patrol-001")
Turn 3: → drone_takeoff() → airborne
Turn 4: → drone_goto(waypoint_1) → arrived
Turn 5: → drone_capture() → image saved
Turn 6: → memory_append("Turbine 1: no anomalies")
... continues autonomously until all 5 turbines done
Turn N: "Patrol complete. 5 turbines inspected, no anomalies detected."
```

Each turn feeds results back in. The LLM reasons about what to do next based on actual results.

---

**The FunctionGemma pipeline is still intact**

The piece we didn't touch: a fine-tuned 270M param model that routes tool calls with >99% accuracy in <300ms. Every tool call the agent makes is auto-captured as JSONL training data. Run some missions → fine-tune → your router learns your exact domain.

```bash
python -m training.pipeline run   # Fine-tune on captured mission data
```

---

**What's next:**

- Phase 2: Pure Kotlin on Android (direct DJI SDK + ONNX Runtime, no React Native)
- Phase 3: Rust core with JNI/PyO3 bindings — same runtime, any language

---

**Install:**
```bash
pip install openhoof
```

Repo: https://github.com/llama-farm/openhoof

Happy to answer questions on the architecture, the token budget strategy, or the FunctionGemma training pipeline.
