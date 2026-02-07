# 🦙 OpenHoof

**Agentic AI that kicks into action.**

<p align="center">
  <img src="docs/openhoof-logo.png" alt="OpenHoof - A cool llama with sunglasses and a bedazzled hoof" width="300">
</p>

> *"Why have claws when you can have hooves?"*  
> — Ancient LlamaFarm Proverb

OpenHoof is a standalone, extensible platform for running AI agents that persist across sessions, respond to events, and coordinate with each other. Built to work with [LlamaFarm](https://github.com/llama-farm/llamafarm) for local inference, but adaptable to any LLM backend.

Some say it was inspired by a certain [claw-based project](https://github.com/anthropics/claude-code)... but we believe hooves are simply more elegant. Plus, llamas don't scratch — they *kick*.

```
┌─────────────────────────────────────────────────────────────┐
│                     YOUR APPLICATION                        │
│              (HORIZON, Medical Wing, etc.)                  │
├─────────────────────────────────────────────────────────────┤
│                          │                                  │
│                    Trigger API                              │
│                     (webhook)                               │
│                          ▼                                  │
├─────────────────────────────────────────────────────────────┤
│                      O P E N H O O F                        │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │  Fuel   │  │  Intel  │  │   MX    │  │ Orchestr│        │
│  │ Analyst │  │ Analyst │  │Specialist│ │  -ator  │        │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘        │
│       │            │            │            │              │
│       └────────────┴─────┬──────┴────────────┘              │
│                          │                                  │
│                    LlamaFarm                                │
│                  (local inference)                          │
└─────────────────────────────────────────────────────────────┘
```

## ✨ Key Features

- **🎯 Event-Driven Agents** — External systems fire webhooks, agents wake up with full context
- **🧠 Persistent Memory** — Agents remember across sessions via workspace files (SOUL.md, MEMORY.md)
- **👥 Multi-Agent Coordination** — Orchestrator agents spawn specialists as needed
- **🔧 Extensible Tools** — Plugin architecture for custom capabilities
- **🖥️ Web Dashboard** — Monitor agents, review activity, approve actions
- **🔌 LlamaFarm Integration** — Works with any LlamaFarm project for inference
- **📡 Real-time Events** — WebSocket streaming for live updates
- **🦙 100% More Llama** — No claws required

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+ (for web UI)
- [LlamaFarm](https://github.com/llama-farm/llamafarm) running on `localhost:14345`

### Installation

```bash
# Clone the repo
git clone https://github.com/llama-farm/openhoof.git
cd openhoof

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# Initialize workspace
openhoof init
```

### Start the Server

```bash
# Start OpenHoof API (default: port 18765)
openhoof start

# In another terminal, start the web UI (default: port 13456)
cd ui && npm install && npm run dev
```

### Verify It's Running

```bash
curl http://localhost:18765/api/health
# {"status":"healthy","components":{"api":true,"inference":true}}
```

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/GETTING_STARTED.md) | First steps with OpenHoof |
| [Architecture](docs/ARCHITECTURE.md) | How the system works |
| [Triggers](docs/TRIGGERS.md) | Event-driven agent spawning |
| [Agents](docs/AGENTS.md) | Creating and managing agents |
| [Tools](docs/TOOLS.md) | Extending agent capabilities |
| [LlamaFarm Integration](docs/LLAMAFARM.md) | Connecting to local LLMs |
| [API Reference](docs/API.md) | REST API documentation |

## 🎯 Example: Event-Driven Agent

When your application detects an anomaly, fire a webhook to OpenHoof:

```bash
curl -X POST http://localhost:18765/api/triggers \
  -H "Content-Type: application/json" \
  -d '{
    "source": "horizon",
    "event_type": "anomaly",
    "category": "fuel",
    "severity": "warning",
    "title": "Fuel Burn Rate Deviation",
    "description": "Current burn rate is 15% above planned",
    "data": {
      "burn_ratio": 1.15,
      "current_fuel_lbs": 145000
    }
  }'
```

Response:
```json
{
  "trigger_id": "TRG-20260206-0001",
  "status": "spawned",
  "agent_id": "fuel-analyst",
  "session_id": "abc123..."
}
```

The `fuel-analyst` agent wakes up, analyzes the situation, and can:
- Query its knowledge base
- Spawn sub-agents for specialized analysis
- Queue notifications for human approval
- Update its memory for future reference

## 🏗️ Project Structure

```
openhoof/
├── openhoof/                 # Python package
│   ├── api/                  # FastAPI routes
│   │   └── routes/
│   │       ├── agents.py     # Agent CRUD
│   │       ├── chat.py       # Chat interface
│   │       └── triggers.py   # Event triggers
│   ├── agents/               # Agent lifecycle
│   ├── core/                 # Sessions, events, workspace
│   ├── inference/            # LlamaFarm adapter
│   └── tools/                # Built-in tools
├── ui/                       # Next.js web dashboard
├── integrations/             # Drop-in clients for apps
│   ├── atmosphere_client.py  # Python SDK
│   ├── horizon_integration.py
│   └── medical_wing_integration.py
├── docs/                     # Documentation
└── examples/                 # Example agents and configs
```

## 🔧 Configuration

OpenHoof uses `~/.openhoof/config.yaml`:

```yaml
# API settings
api:
  host: 0.0.0.0
  port: 18765
  cors_origins:
    - http://localhost:13456

# LlamaFarm connection
inference:
  base_url: http://localhost:14345
  namespace: default
  project: openhoof

# Auto-start these agents on boot
autostart_agents:
  - orchestrator
```

## 🤝 Integration Examples

### Python (Async)
```python
from openhoof import OpenHoofClient

client = OpenHoofClient("http://localhost:18765")

# Fire a trigger
response = await client.trigger(
    source="my-app",
    event_type="alert",
    severity="warning",
    title="Something happened",
    data={"details": "..."}
)

print(f"Agent {response.agent_id} is handling it")
```

### Python (Callback for Anomaly Detectors)
```python
from openhoof import AnomalyTriggerCallback

# Register with your anomaly engine
callback = AnomalyTriggerCallback(source="my-app")
my_detector.register_callback(callback)

# Now anomalies automatically trigger agents!
```

### cURL / Any HTTP Client
```bash
curl -X POST http://localhost:18765/api/triggers \
  -H "Content-Type: application/json" \
  -d '{"source":"my-app","event_type":"alert","title":"Help!"}'
```

## 🧩 Extending OpenHoof

### Custom Tools

Create tools that agents can use:

```python
# tools/my_tool.py
from openhoof.tools import Tool, ToolResult

class WeatherTool(Tool):
    name = "get_weather"
    description = "Get current weather for a location"
    
    async def execute(self, location: str) -> ToolResult:
        # Your implementation
        return ToolResult(success=True, data={"temp": 72})
```

### Custom Trigger Rules

Add routing rules for your application:

```bash
curl -X POST http://localhost:18765/api/triggers/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-critical-handler",
    "source": "my-app",
    "event_type": "*",
    "min_severity": "critical",
    "agent_id": "emergency-responder"
  }'
```

### Agent Templates

Create agent templates for quick deployment:

```yaml
# templates/analyst.yaml
name: "{{domain}}-analyst"
soul: |
  You are a {{domain}} analyst AI.
  Your job is to analyze {{domain}} data and provide insights.
tools:
  - search
  - calculate
  - notify
```

## 🌟 Why "OpenHoof"?

- **Open** — Open source, extensible, integrates with anything
- **Hoof** — Agents that "kick" into action (llamas kick, they don't claw 🦙)
- Part of the [LlamaFarm](https://github.com/llama-farm) ecosystem

### A Note on Claws vs Hooves

You may have heard of [Claude Code](https://github.com/anthropics/claude-code) (née OpenClaw), Anthropic's excellent coding agent. Great project! Sharp claws! Very pointy!

But consider: **claws scratch**. They're for climbing trees and looking threatening.

**Hooves**, on the other hand, are for *getting things done*. Llamas carry cargo across mountains. They kick predators into next week. They look fabulous doing it.

Plus, our hooves are *bedazzled*. ✨

## 📜 License

Apache 2.0

## 🙏 Acknowledgments

- [Claude Code](https://github.com/anthropics/claude-code) — The workspace/agent patterns that inspired this (we come in peace 🦙🤝🐻)
- [LlamaFarm](https://github.com/llama-farm/llamafarm) — Local LLM inference
- Built with ❤️ for the Air Force and anyone who needs reliable local AI agents

---

**Ready to let your agents kick into action?** [Get Started →](docs/GETTING_STARTED.md)

*No llamas were harmed in the making of this framework. Several were bedazzled.*
