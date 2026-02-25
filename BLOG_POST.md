# OpenHoof 2.0: From Server Framework to Autonomous Agent Runtime

**Published:** February 2026  
**By:** LlamaFarm Team

---

When we built the first version of OpenHoof, the goal was straightforward: a server framework for routing AI tool calls, with a tight integration to FunctionGemma for fast, fine-tuned dispatch. It worked well as a backend — you'd fire a webhook, OpenHoof would spin up an agent session, route the call through FunctionGemma (<300ms), and return a result.

But we kept running into the same wall.

The drone team needed an agent that could fly a mission *autonomously* — no gateway, no server, no internet. Just a phone, a drone, and a model running on-device. OpenHoof v1.x couldn't do that. It was a server. It needed to be running somewhere, reachable, connected.

So we rebuilt it from the ground up.

---

## What's New in OpenHoof 2.0

OpenHoof 2.0 is no longer a server framework. It's a **standalone agent runtime library** — the missing piece between a raw LLM and a truly autonomous agent. It runs anywhere: a Python script on your laptop, an Android phone controlling a drone, a Rust daemon on an edge device.

The API is simple:

```python
from openhoof import Agent, bootstrap_agent, get_builtin_tool_schemas, create_tool_schema

# Bootstrap a complete agent workspace in one call
bootstrap_agent(
    workspace="~/.openhoof/agents/drone-agent",
    name="DroneBot",
    emoji="🚁",
    mission="Autonomous aerial patrol and reconnaissance",
    user_name="Rob",
    timezone="America/Chicago"
)

# Define tools with rich operational guidance
drone_takeoff = create_tool_schema(
    name="drone_takeoff",
    summary="Arm motors and take off to hover altitude (~1.2m AGL)",
    when_to_use="Mission start after telemetry check",
    prerequisites=["GPS lock >= 8 sats", "Battery > 40%"],
    best_practices=["Wait 3s after return before next command"],
    safety=["Abort if wind > 15 m/s", "Abort if battery < 40%"]
)

# Create agent — built-in tools + your tools
agent = Agent(
    soul="SOUL.md",
    memory="MEMORY.md",
    tools=get_builtin_tool_schemas() + [drone_takeoff, ...],
    executor=my_executor,
    workspace="~/.openhoof/agents/drone-agent",
    max_turns=10
)

# Give it a goal. It figures out the rest.
response = agent.reason("Execute patrol mission: 5 waypoints, capture images at each")
```

The agent will autonomously decide which tools to call, in what order, based on what the LLM reasons it needs. It chains tool calls across multiple turns — feeding results back into the model until the task is complete.

---

## The Core Problem We Solved

Most agent frameworks make a silent assumption: there's always a server somewhere, always a connection, always unlimited context to work with.

That assumption breaks completely on the edge.

A drone flying a patrol mission might lose connectivity mid-flight. An Android phone running a local model has 2,048 tokens of context — not 128k. A battery-powered edge device can't afford to wait two minutes for an LLM to summarize its own memory.

OpenHoof 2.0 was designed around these constraints from day one.

---

## Token Budget: 200 Tokens, Not 4,000

The first thing we threw out was the "inject everything into the system prompt" approach.

OpenClaw and most agent frameworks load all context files at session start: SOUL.md, AGENTS.md, USER.md, TOOLS.md, MEMORY.md, today's log, yesterday's log. On a desktop model with 128k context, this is fine. On a 1B parameter phone model with 2,048 tokens total, you've already spent 200% of your budget before the first user message.

OpenHoof 2.0 flips this model.

**System prompt = SOUL.md core only (~200 tokens):**

```markdown
You are DroneBot 🚁. Autonomous aerial patrol and reconnaissance.

Core rules:
- Be autonomous and efficient (limited battery/tokens)
- Log important decisions to memory
- Check exit conditions on heartbeat
- Buffer data when offline (DDIL)

Context tools (use when needed):
- memory_search(query) — search past events
- read_user() — user info  
- read_agents() — operating instructions
- read_tool_guide(tool) — tool usage guidance
```

Everything else loads **on demand** via built-in tools. The agent decides when it needs context, fetches exactly what's relevant, and moves on. Instead of injecting 2,000 tokens of MEMORY.md, the agent calls `memory_search("last waypoint altitude")` and gets back 3 relevant snippets (~80 tokens). 

**Result: 95% of the context window is available for actual work.**

---

## Built-in Tools: Self-Sufficient Agents

For an agent to operate autonomously on the edge, it needs to manage itself. We built a set of 10+ built-in tools that every OpenHoof agent gets out of the box — no network required, no external services.

**Memory:**
```python
memory_search("last known battery level")   # Returns top 3 snippets
memory_append("Waypoint 3 reached, 75% battery")  # Logs to daily file
```

**Mission lifecycle:**
```python
mission_start("patrol-001", "Inspect 5 turbines")   # Fresh context, mission logged
checkpoint("Turbines 1-3 done, battery 70%")        # Save progress
mission_complete("All turbines inspected", "success")  # Archive + clear
```

**State persistence:**
```python
save_state("last_position", {"lat": 45.52, "lon": -122.68, "alt_m": 15})
load_state("last_position")  # Survives session restarts
```

**Logging:**
```python
log("Pre-flight checks complete", level="info")   # → memory/2026-02-24.md
log("Wind speed 14 m/s, approaching limit", level="warn")
```

**Context loading (lazy):**
```python
read_user()       # USER.md — who am I helping? (~50 tokens)
read_agents()     # AGENTS.md — operating instructions (~400 tokens)
read_tool_guide("drone_goto")   # Tool-specific guidance (~100 tokens)
```

These tools also double as training data generators. Every call is logged in JSONL format — exactly the format the FunctionGemma training pipeline expects.

---

## Rich Tool Descriptions: Telling the Agent HOW to Use Tools

Tool schemas tell the LLM *what* a tool does. But for an autonomous agent with 23 drone tools, that's not enough. The agent needs to know *when* to use it, *how* to sequence it correctly, and *what safety constraints apply*.

OpenHoof 2.0 introduces `create_tool_schema()` — a helper that generates rich tool descriptions with embedded operational guidance:

```python
drone_goto = create_tool_schema(
    name="drone_goto",
    summary="Fly to GPS waypoint at specified altitude",
    when_to_use="Waypoint navigation (preferred over manual drone_move)",
    prerequisites=["Drone airborne", "GPS lock"],
    best_practices=[
        "Set arrived_m=3.0 for precision landings",
        "Check telemetry after arrival to confirm position"
    ],
    safety=[
        "Verify geofence allows target coordinates",
        "Check battery sufficient for distance"
    ],
    parameters={...}
)
```

The resulting description tells the LLM everything it needs for autonomous decision-making — without blowing the token budget, since tool schemas are sent once per session.

---

## Multi-Turn Reasoning Loop

When the agent calls `agent.reason(prompt)`, it doesn't just make one LLM call. It runs a full reasoning loop:

```
Turn 1: LLM receives task + 23 tool schemas
        → Decides: call get_battery()
        → Result: battery_percent=75

Turn 2: LLM sees battery=75 (above 40% threshold)
        → Decides: call mission_start("patrol-001", "Inspect turbines")
        → Result: mission started, context cleared

Turn 3: LLM decides: call drone_takeoff()
        → Result: airborne, altitude=1.2m

Turn 4: LLM decides: call drone_goto(lat=45.52, lon=-122.68, alt_m=15)
        → Result: arrived at waypoint 1

Turn 5: LLM decides: call drone_capture()
        → Result: image captured, 245KB JPEG

Turn 6: LLM decides: call memory_append("Turbine 1: No anomalies detected")
        → Continues to waypoint 2...

Turn N: LLM returns final response (no more tool calls)
        → "Patrol complete: 5 turbines inspected, no anomalies."
```

Each turn feeds tool results back into the conversation history. The LLM reasons about what to do next based on actual results, not assumptions. This is the loop that makes agents genuinely autonomous.

---

## DDIL: Designed for Denied Networks

One of the hardest problems in edge AI is what happens when the network drops.

DDIL — Denied, Degraded, Intermittent, Limited — is the reality of operating in the field. A drone flying over a forest. A sensor package in a remote facility. A phone in a basement.

OpenHoof 2.0 has DDIL support built in from the ground up:

- **Store-and-forward buffer**: Important data is buffered locally when offline, synced when connectivity returns
- **Offline operation**: The agent loop continues running with local models — no dependency on cloud APIs
- **Checkpoint system**: Mission progress is saved locally so the agent can resume after a crash or network loss
- **Graceful degradation**: Falls back from cloud models → local models → cached responses

---

## The FunctionGemma Pipeline: Still The Gold

The one thing we didn't touch: the FunctionGemma training pipeline.

OpenHoof v1.x achieved something remarkable — fine-tuning a 270M parameter model to route tool calls with >99% accuracy in under 300ms. That capability is too valuable to throw away.

In v2.0, the FunctionGemma pipeline is still fully intact:

```bash
# Check training data
python -m training.pipeline status

# Generate synthetic training samples
python -m training.pipeline generate

# Fine-tune FunctionGemma on your tools
python -m training.pipeline run
```

Every tool call the agent makes is automatically captured as training data. Run a few missions, generate a few hundred examples, fine-tune — and your router model learns the exact tool usage patterns for your domain.

For a drone agent with 23 tools, this means:
- Agent autonomously executes missions
- Every tool call captured in JSONL
- FunctionGemma fine-tuned on real mission data
- Router accuracy approaches 100% for your specific tools

---

## What's Next

OpenHoof 2.0 is the Python reference implementation. The architecture is deliberately designed to port cleanly:

**Phase 2: Kotlin (Android)**
Direct DJI SDK + ONNX Runtime. No React Native. No server. The drone agent runs entirely on the Android phone controlling the drone.

**Phase 3: Rust Core**
Cross-platform library with JNI bindings for Kotlin, C bridge for Swift/iOS, and PyO3 for Python. The same agent runtime, running on any device with a CPU.

---

## Get Started

```bash
git clone https://github.com/llama-farm/openhoof.git
cd openhoof
pip install -e .
```

```python
from openhoof import bootstrap_agent, Agent, get_builtin_tool_schemas

# Create workspace
bootstrap_agent(
    workspace="./my-agent",
    name="MyBot",
    emoji="🤖",
    mission="Your mission here"
)

# Run the agent
agent = Agent(
    soul="./my-agent/SOUL.md",
    memory="./my-agent/MEMORY.md",
    tools=get_builtin_tool_schemas(),
    executor=my_executor,
    workspace="./my-agent"
)

response = agent.reason("What should I do first?")
```

The full test suite is in `test_builtin_tools.py`. Run it to see a complete autonomous drone mission simulated end-to-end.

---

*OpenHoof is developed by LlamaFarm. The FunctionGemma training pipeline and tool schema format are open source at [github.com/llama-farm/openhoof](https://github.com/llama-farm/openhoof).*
