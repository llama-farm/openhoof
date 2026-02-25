# OpenHoof v2.0

**Standalone agent runtime library for autonomous LLM agents — runs on-device, no server required.**

[![PyPI version](https://img.shields.io/pypi/v/openhoof.svg)](https://pypi.org/project/openhoof/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)

---

**v1 was a FastAPI server.** WebSockets, session management, a CLI, a UI, a gateway. You needed it running somewhere reachable to use it.

**v2 is a library.** `pip install openhoof`. Import it. Your agent runs anywhere — laptop, phone, edge device, Rust daemon.

---

## Install

```bash
pip install openhoof
```

Or from source:

```bash
git clone https://github.com/llama-farm/openhoof.git
cd openhoof
pip install -e .
```

---

## Quick Start

```python
from openhoof import Agent, bootstrap_agent, get_builtin_tool_schemas, create_tool_schema

# 1. Create a complete agent workspace (SOUL.md, MEMORY.md, HEARTBEAT.md, etc.)
bootstrap_agent(
    workspace="./my-agent",
    name="MyBot",
    emoji="🤖",
    mission="Your mission here",
    user_name="Rob",
    timezone="America/Chicago"
)

# 2. Define your tools (OpenAI-compatible format)
my_tool = create_tool_schema(
    name="get_status",
    summary="Get current system status",
    parameters={"type": "object", "properties": {"system": {"type": "string"}}, "required": ["system"]}
)

def my_executor(tool_name: str, params: dict) -> dict:
    if tool_name == "get_status":
        return {"status": "operational", "uptime": "4h"}
    return {"error": "unknown tool"}

# 3. Run the agent — it chains tool calls autonomously until the task is done
agent = Agent(
    soul="./my-agent/SOUL.md",
    memory="./my-agent/MEMORY.md",
    tools=get_builtin_tool_schemas() + [my_tool],
    executor=my_executor,
    workspace="./my-agent",
    max_turns=10
)

response = agent.reason("Check system status and log the result")
print(response)
```

---

## How It Works

`agent.reason(prompt)` runs a multi-turn loop — the LLM decides which tools to call, executes them, feeds results back in, and repeats until the task is complete:

```
Turn 1: LLM → call get_status("server") → "operational, 4h uptime"
Turn 2: LLM → call log("Server operational") → logged to memory
Turn 3: LLM → no more tool calls → "Server is operational. Uptime: 4h. Logged."
```

`max_turns` is configurable at init or per-call:
```python
agent = Agent(..., max_turns=20)
response = agent.reason("complex task", max_turns=5)  # per-call override
```

---

## Built-in Tools

Every agent gets 10+ built-in tools automatically — no extra setup:

| Tool | What it does |
|------|-------------|
| `memory_search(query)` | Semantic search across MEMORY.md |
| `memory_append(text)` | Append to daily memory log |
| `memory_read()` | Read full MEMORY.md |
| `get_time()` | Current timestamp |
| `log(msg, level)` | Structured log with emoji levels |
| `save_state(key, value)` | Persist state across sessions |
| `load_state(key)` | Restore saved state |
| `mission_start(id, goal)` | Start mission with fresh context |
| `checkpoint(summary)` | Save progress mid-mission |
| `mission_complete(summary)` | Archive mission + clear context |
| `read_soul()` | Load SOUL.md on demand |
| `read_user()` | Load USER.md on demand |
| `read_agents()` | Load AGENTS.md on demand |
| `read_tool_guide(tool)` | Load tool-specific guidance |

### Token Budget Strategy

Mobile models have 2,048 tokens total. Loading all context upfront wastes most of it.

OpenHoof keeps the system prompt to **~200 tokens** (SOUL.md core only). Everything else lazy-loads via built-in tools when the agent actually needs it:

```python
memory_search("last waypoint altitude")   # 3 snippets, ~80 tokens
read_tool_guide("drone_goto")             # tool guidance on-demand
```

**Result: 95% of context window available for actual work.**

---

## LlamaFarm Integration

Configure your models in `llamafarm.yaml`:

```yaml
llamafarm:
  endpoint: "http://localhost:11540/v1"

models:
  router:
    model: "functiongemma"       # Fast tool routing (<300ms)
  reasoning:
    model: "unsloth/Qwen3-1.7B-GGUF"  # Agentic loop
  mobile:
    model: "llama3.2:1b"         # On-device (phone)
  fallback:
    model: "gpt-4o-mini"         # Cloud fallback
```

---

## DDIL Support

Built for offline-first operation — Denied, Degraded, Intermittent, Limited networks:

- **Store-and-forward**: Data buffers locally when offline, syncs when connectivity returns
- **Local model fallback**: Agent loop continues with on-device models during outages
- **Checkpoint/resume**: Mission progress saved so agents recover from crashes

```python
from openhoof import Agent, DDILBuffer

agent = Agent(..., ddil_enabled=True)
agent.run()  # Keeps running even when network drops
```

---

## FunctionGemma Training Pipeline

Fine-tune a 270M parameter model to route tool calls with >99% accuracy in <300ms.

Every tool call the agent makes is automatically captured as JSONL training data:

```bash
# Check captured training data
python -m training.pipeline status

# Fine-tune FunctionGemma on your captured data
python -m training.pipeline run

# Export for deployment
python -m training.pipeline export
```

Run missions → capture data → fine-tune → your router learns your exact domain.

---

## Repo Structure

```
openhoof/               # Library (pip install openhoof)
├── agent.py            # Core Agent class + reasoning loop
├── soul.py             # SOUL.md loading → system prompt
├── memory.py           # MEMORY.md + semantic search
├── heartbeat.py        # Heartbeat + exit conditions
├── events.py           # Event queue
├── ddil.py             # Store-and-forward buffer
├── training.py         # Training data capture (JSONL)
├── models.py           # LlamaFarm model integration
├── tool_registry.py    # Tool registration + execution
├── bootstrap.py        # Workspace bootstrapping
└── builtin_tools/      # 10+ built-in agent tools

training/               # FunctionGemma fine-tuning pipeline
├── pipeline.py         # Training orchestration
└── train_tool_router.py

examples/               # Example agent configs
├── basic-agent/
├── drone-agent/
├── fuel-analyst/
├── orchestrator/
└── customer-support/

docs/                   # Design docs
tests/                  # Test suite
```

---

## Roadmap

- **Phase 2 (now):** Pure Kotlin Android — direct DJI SDK + ONNX Runtime, no React Native
- **Phase 3:** Rust core with JNI/PyO3 bindings — same runtime, any platform

---

## License

Apache 2.0 — see [LICENSE](LICENSE)

Built by [LlamaFarm](https://github.com/llama-farm)
