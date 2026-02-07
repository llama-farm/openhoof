# OpenHoof Architecture

<p align="center">
  <img src="openhoof-logo.png" alt="OpenHoof Logo" width="150">
</p>

This document explains how OpenHoof works under the hood.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EXTERNAL SYSTEMS                                   │
│                    (HORIZON, Medical Wing, Your App)                         │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ HTTP/WebSocket
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            OPENHOOF API                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   /agents    │  │    /chat     │  │  /triggers   │  │  /activity   │    │
│  │    CRUD      │  │   Messages   │  │   Events     │  │    Feed      │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
├─────────────────────────────────────────────────────────────────────────────┤
│                            CORE SERVICES                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   Session    │  │    Event     │  │   Workspace  │  │    Tool      │    │
│  │   Manager    │  │     Bus      │  │   Manager    │  │   Registry   │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
├─────────────────────────────────────────────────────────────────────────────┤
│                            AGENT LAYER                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        Agent Lifecycle                               │    │
│  │   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐         │    │
│  │   │  Agent  │    │  Agent  │    │  Agent  │    │  Agent  │         │    │
│  │   │    A    │    │    B    │    │    C    │    │   ...   │         │    │
│  │   └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘         │    │
│  │        │              │              │              │               │    │
│  │        └──────────────┴──────┬───────┴──────────────┘               │    │
│  └──────────────────────────────┼──────────────────────────────────────┘    │
├─────────────────────────────────┼───────────────────────────────────────────┤
│                                 ▼                                            │
│                         INFERENCE ADAPTER                                    │
│                    (LlamaFarm / OpenAI / etc.)                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. API Layer (`api/`)

FastAPI-based REST API that handles:

| Endpoint | Purpose |
|----------|---------|
| `GET/POST /agents` | List, create, update, delete agents |
| `POST /agents/{id}/chat` | Send messages to agents |
| `POST /triggers` | Receive events from external systems |
| `GET /activity` | Real-time activity feed |
| `WS /events` | WebSocket for live updates |

### 2. Core Services (`core/`)

#### Session Manager
Tracks conversation state across interactions:
```python
session = session_manager.get_or_create(
    session_key="agent:fuel-analyst:session:abc123",
    agent_id="fuel-analyst"
)
```

Sessions persist to `~/.openhoof/data/sessions.json` for restart recovery.

#### Event Bus
Pub/sub system for real-time notifications:
```python
# Emit an event
await event_bus.emit("agent:message", {
    "agent_id": "fuel-analyst",
    "content": "Analysis complete"
})

# Subscribe to events
event_bus.subscribe("agent:*", my_callback)
```

Events are broadcast to WebSocket clients for UI updates.

#### Workspace Manager
Manages agent file workspaces (`~/.openhoof/agents/{agent_id}/`):
```
fuel-analyst/
├── SOUL.md           # Agent identity and personality
├── AGENTS.md         # Workspace rules (optional)
├── MEMORY.md         # Long-term memory
├── TOOLS.md          # Local tool notes
├── USER.md           # User context
├── HEARTBEAT.md      # Periodic task config
└── memory/           # Daily memory files
    ├── 2026-02-05.md
    └── 2026-02-06.md
```

#### Tool Registry
Central registry for agent capabilities:
```python
registry = ToolRegistry()
registry.register(SearchTool())
registry.register(NotifyTool())

# Agents can call tools
result = await registry.execute("search", query="fuel efficiency")
```

### 3. Agent Layer (`agents/`)

#### Agent Lifecycle
Manages agent startup, execution, and shutdown:
```
STOPPED → STARTING → RUNNING → STOPPING → STOPPED
```

#### Workspace Files
Agents read these files at session start:

| File | Purpose | When Read |
|------|---------|-----------|
| `SOUL.md` | Core identity and instructions | Every session |
| `AGENTS.md` | Workspace rules | Every session |
| `USER.md` | User-specific context | Main sessions only |
| `MEMORY.md` | Long-term memory | Main sessions only |
| `memory/YYYY-MM-DD.md` | Daily notes | Recent days |

#### Sub-agents
Agents can spawn other agents:
```python
# Orchestrator spawns specialist
result = await spawn_agent(
    agent_id="fuel-analyst",
    task="Analyze this fuel anomaly",
    context=anomaly_data
)
```

### 4. Inference Adapter (`inference/`)

Abstraction layer for LLM backends:

```python
class LlamaFarmAdapter:
    async def chat(self, messages: List[Message]) -> Response:
        # Calls LlamaFarm API
        response = await self.client.post(
            f"{self.base_url}/v1/projects/{ns}/{proj}/chat/completions",
            json={"messages": messages}
        )
        return response
```

Currently supports:
- **LlamaFarm** (default) — Local inference
- Easy to add: OpenAI, Anthropic, Ollama, etc.

### 5. Trigger System (`api/routes/triggers.py`)

Event-driven agent activation:

```
External Event → Trigger API → Rule Matching → Agent Spawn
```

Rules map events to agents:
```yaml
rules:
  - name: fuel-anomaly
    source: horizon
    event_type: anomaly
    category: fuel
    min_severity: warning
    agent_id: fuel-analyst
```

## Data Flow

### Chat Request Flow
```
1. Client sends POST /agents/{id}/chat
2. Session Manager loads/creates session
3. Workspace Manager reads agent files (SOUL.md, etc.)
4. Messages + context sent to Inference Adapter
5. LlamaFarm generates response
6. Tool calls executed if needed
7. Response returned to client
8. Event Bus notifies WebSocket clients
```

### Trigger Flow
```
1. External system POSTs to /triggers
2. Trigger Engine matches rules
3. Best matching agent identified
4. Session created with trigger context
5. Agent "wakes up" with full event data
6. Agent processes and responds
7. Results available via API/WebSocket
```

## Configuration

`~/.openhoof/config.yaml`:
```yaml
api:
  host: 0.0.0.0
  port: 18765
  cors_origins:
    - http://localhost:13456

inference:
  base_url: http://localhost:14345
  namespace: default
  project: openhoof
  default_model: null  # Use project default

autostart_agents:
  - orchestrator

logging:
  level: INFO
  file: ~/.openhoof/data/logs/openhoof.log
```

## Security Considerations

1. **No auth by default** — Add authentication for production
2. **CORS configured** — Whitelist your domains
3. **Tool execution** — Some tools may have side effects
4. **Memory persistence** — Sensitive data may be stored

## Extending OpenHoof

| Extension Point | How |
|-----------------|-----|
| New tools | Implement `Tool` base class |
| New inference backends | Implement `InferenceAdapter` |
| Custom trigger rules | POST to `/triggers/rules` |
| Agent templates | Add to `templates/` directory |

See [TOOLS.md](TOOLS.md) for extending agent capabilities.
