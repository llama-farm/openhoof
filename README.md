# 🦙 OpenHoof v2.0

**Local AI agent runtime library with FunctionGemma training**

OpenHoof is a standalone, extensible library for running AI agents that persist across sessions, respond to events, and coordinate with each other. Built to work with [LlamaFarm](https://github.com/llama-farm/llamafarm) for local inference.

```
┌─────────────────────────────────────────────────────────────┐
│                     YOUR APPLICATION                        │
│              (Drone Control, Medical, etc.)                 │
├─────────────────────────────────────────────────────────────┤
│                          │                                  │
│                    Agent Runtime                            │
│                          ▼                                  │
├─────────────────────────────────────────────────────────────┤
│                      O P E N H O O F                        │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │  Agent  │  │  Soul   │  │ Memory  │  │ Tools   │        │
│  │  Loop   │  │ Loading │  │ Recall  │  │Registry │        │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘        │
│       │            │            │            │              │
│       └────────────┴─────┬──────┴────────────┘              │
│                          │                                  │
│                    LlamaFarm                                │
│                  (local inference)                          │
└─────────────────────────────────────────────────────────────┘
```

---

## ✨ What's New in v2.0

**Complete rebuild** as a standalone library (was a server framework in v1.x):

- **🎯 Agent Runtime** — Event loop, heartbeat, exit conditions
- **🧠 Context Files** — SOUL.md, MEMORY.md, USER.md, TOOLS.md as first-class citizens
- **💾 DDIL** — Store-and-forward for offline operation (Denied/Degraded/Intermittent/Limited networks)
- **🔌 LlamaFarm Integration** — Tools + prompts passed through in API calls
- **📡 Training Data Capture** — Every tool call logged for fine-tuning
- **🎓 FunctionGemma Pipeline** — Auto-generate training data, fine-tune tool routing model (GOLD!)
- **📱 Runs Anywhere** — Python (now) → Kotlin (Android) → Rust (cross-platform)

---

## 🚀 Quick Start

### Installation

```bash
pip install -e git+https://github.com/llama-farm/openhoof.git@feat/microclaw-rebuild#egg=openhoof
```

### Basic Usage

```python
from openhoof import Agent, Soul, Memory

# Define your tools (OpenAI-compatible format)
tools = [
    {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string"}
            },
            "required": ["location"]
        }
    }
]

# Tool executor (your implementation)
def execute_tool(tool_name: str, params: dict) -> dict:
    if tool_name == "get_weather":
        return {"temp": 72, "condition": "sunny"}
    return {"error": "Unknown tool"}

# Create agent
agent = Agent(
    soul="SOUL.md",  # Your agent's identity + mission
    memory="MEMORY.md",  # Long-term recall
    tools=tools,
    executor=execute_tool,
    llamafarm_config="llamafarm.yaml",  # LlamaFarm models
    heartbeat_interval=30.0
)

# Exit conditions
agent.on_exit("timeout", lambda: time.time() - agent.start_time > 1800)

# Heartbeat callbacks
agent.on_heartbeat(lambda: print(f"💓 Still alive"))

# Run agent
agent.run()
```

---

## 📖 Core Concepts

### Context Files

OpenHoof agents are defined by markdown files:

```
my-agent/
├── SOUL.md          # Identity, mission, style, constraints
├── MEMORY.md        # Long-term recall, persistent context
├── USER.md          # Who the agent serves, preferences
└── TOOLS.md         # Available capabilities, tool docs
```

**SOUL.md example:**
```markdown
# SOUL.md - Weather Agent

You are a helpful weather assistant AI.

**Name:** WeatherBot
**Emoji:** ☀️

## Mission
Provide accurate, timely weather information to users.

## Style
- Be concise and factual
- Always include units (°F, mph, etc.)
- Warn about severe weather
```

### Tool Schema Format

OpenHoof uses **OpenAI-compatible tool schemas** (same format Ace uses):

```python
{
    "name": "drone_takeoff",
    "description": "Take off and hover at specified altitude",
    "parameters": {
        "type": "object",
        "properties": {
            "alt_m": {"type": "number", "description": "Altitude in meters"},
        },
        "required": ["alt_m"]
    }
}
```

### Heartbeat System

Agents run a heartbeat loop every N seconds:

```python
# Check exit conditions
agent.on_exit("battery_low", lambda: agent.custom.get("battery") < 20)
agent.on_exit("timeout", lambda: runtime > 1800)

# Custom heartbeat actions
def heartbeat():
    battery = get_battery()
    agent.custom["battery"] = battery
    if battery < 30:
        print("⚠️ Low battery!")

agent.on_heartbeat(heartbeat)
```

### DDIL (Store-and-Forward)

When network is unavailable, agents buffer data locally:

```python
# Store data when offline
agent.ddil.store("telemetry", {
    "lat": 41.8781,
    "lon": -87.6298,
    "battery": 85
})

# Sync when network returns
agent.ddil.sync_to_server("http://gateway.local")
```

### LlamaFarm Integration

Configure models in `llamafarm.yaml`:

```yaml
endpoint: "http://localhost:8765/v1"

models:
  router:
    model: "functiongemma:270m"  # Fast tool routing
    temperature: 0.1
  
  reasoning:
    model: "qwen2.5:8b"  # Agent reasoning
    temperature: 0.7
  
  fallback:
    model: "gpt-4o-mini"  # Cloud fallback
```

Use in agent:

```python
# Reason about a situation (can trigger tool calls)
response = agent.reason("Should I continue if battery is 25%?")
print(response['content'])
```

---

## 🎓 FunctionGemma Training Pipeline (THE GOLD!)

OpenHoof includes an **automated training pipeline** for fine-tuning FunctionGemma on your tool calling patterns.

### How It Works

1. **Data Collection** — Every tool call (input → tool selection → result) logged as training data
2. **Synthetic Generation** — Auto-generate diverse examples for each tool
3. **LoRA Fine-tuning** — Train FunctionGemma-270M on your tools (<300ms routing)
4. **GGUF Export** — Export trained model for deployment
5. **Hot-swap** — Update LlamaFarm with new model

### Usage

```bash
# Check training data status
python -m openhoof.training.pipeline status

# Generate synthetic training data
python -m openhoof.training.pipeline generate --count 100

# Run full training pipeline
python -m openhoof.training.pipeline run

# Export data for inspection
python -m openhoof.training.pipeline export
```

### Training Data Format

```json
{
  "input": {
    "user_message": "Check the weather in Chicago",
    "tools": ["get_weather", "set_reminder", "search_web"]
  },
  "output": {
    "tool_calls": [
      {"name": "get_weather", "arguments": {"location": "Chicago"}}
    ]
  },
  "metadata": {
    "source": "live_usage",
    "timestamp": "2026-02-20T15:00:00"
  }
}
```

This is logged automatically by `TrainingDataCapture` on every tool call.

---

## 🏗️ Project Structure

```
openhoof/
├── openhoof/                 # Python library
│   ├── agent.py              # Core Agent class
│   ├── soul.py               # SOUL.md loading
│   ├── memory.py             # MEMORY.md + semantic search
│   ├── heartbeat.py          # Heartbeat + exit conditions
│   ├── events.py             # Event queue
│   ├── ddil.py               # Store-and-forward buffer
│   ├── training.py           # Training data capture
│   ├── models.py             # LlamaFarm integration
│   ├── tools/                # Tool base classes + registry
│   │   ├── base.py           # Tool base class
│   │   ├── registry.py       # ToolRegistry
│   │   └── builtin/          # Built-in tools
│   └── tool_registry.py      # Simple registry (for basic use)
├── training/                 # FunctionGemma pipeline (THE GOLD!)
│   ├── pipeline.py           # Training pipeline orchestration
│   └── train_tool_router.py # LoRA fine-tuning script
├── examples/                 # Example agents
├── tests/                    # Unit tests
└── llamafarm.yaml            # LlamaFarm config
```

---

## 🔧 Tool Schema (What Ace Uses)

OpenHoof defines a **tool schema format** that's 100% OpenAI-compatible. This is what Ace uses (not the library itself, just the format):

```python
DRONE_TOOLS = [
    {
        "name": "drone_takeoff",
        "description": "Take off and hover at specified altitude",
        "parameters": {
            "type": "object",
            "properties": {
                "alt_m": {"type": "number", "default": 15.0}
            },
            "required": []
        }
    },
    {
        "name": "drone_move",
        "description": "Move relative to current position",
        "parameters": {
            "type": "object",
            "properties": {
                "north_m": {"type": "number", "default": 0.0},
                "east_m": {"type": "number", "default": 0.0},
                "up_m": {"type": "number", "default": 0.0},
                "yaw_deg": {"type": "number", "default": 0.0}
            },
            "required": []
        }
    }
]
```

This format works with:
- FunctionGemma fine-tuning
- LlamaFarm tool calling
- OpenAI API (if using cloud fallback)

---

## 📦 Installation & Development

```bash
# Clone the repo
git clone https://github.com/llama-farm/openhoof.git
cd openhoof

# Install in development mode
pip install -e .

# Run tests
pytest tests/

# Generate synthetic training data
python -m openhoof.training.pipeline generate --count 100

# Train FunctionGemma
python -m openhoof.training.pipeline run
```

---

## 🎯 Example: Drone Agent

```python
from openhoof import Agent
from my_drone_tools import DRONE_TOOLS, DroneToolExecutor

agent = Agent(
    soul="SOUL.md",
    memory="MEMORY.md",
    tools=DRONE_TOOLS,
    executor=DroneToolExecutor(),
    heartbeat_interval=30.0
)

# Exit on battery low or geofence breach
agent.on_exit("battery_low", lambda: agent.custom.get("battery") < 20)
agent.on_exit("geofence", lambda: not agent.custom.get("in_bounds"))

# Sync telemetry on heartbeat
def heartbeat():
    telemetry = get_telemetry()
    agent.custom["battery"] = telemetry.battery
    agent.custom["in_bounds"] = telemetry.in_geofence
    
    # Buffer telemetry for DDIL
    agent.ddil.store("telemetry", telemetry.to_dict())

agent.on_heartbeat(heartbeat)

# Run agent
agent.run()
```

---

## 🔄 Migration from v1.x

**v1.x was a server** (FastAPI + WebSockets + UI)  
**v2.0 is a library** (standalone agent runtime)

If you were using v1.x:
- **Server features** → Moved to separate project (TBD)
- **Agent runtime** → Now a library you import
- **Tool schemas** → 100% compatible, no changes needed
- **Training pipeline** → Still here, improved!

---

## 📜 License

Apache 2.0

---

## 🙏 Acknowledgments

- [LlamaFarm](https://github.com/llama-farm/llamafarm) — Local LLM inference
- Built with ❤️ for anyone who needs reliable local AI agents
- Special thanks to Ace (drone agent) for validating the architecture

---

**Ready to build agents that kick into action?** 🦙

*No llamas were harmed in the making of this library. Several were bedazzled.*
