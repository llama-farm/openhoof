## Context

Openhoof agents currently operate in a request-response pattern. The `AgentManager._run_agent_turn()` method executes a single turn: it takes a user message, builds context (system prompt from workspace + conversation history), calls the LLM with tools, runs a tool-calling loop (up to `max_tool_rounds`), saves the transcript, and returns.

The only autonomous behavior today is `HeartbeatRunner` — an `asyncio.Task` that periodically calls `_run_agent_turn` with a fixed prompt. It's a timer-based poke with no data awareness.

This design introduces a brain-driven autonomous loop where the agent controls its own execution tempo, sees structured state every turn, and decides when to act, wait, or stop. Local inference via LlamaFarm makes continuous LLM calls practical.

## Goals / Non-Goals

**Goals:**
- Agents can run autonomously in a continuous observe/think/act/yield loop
- The agent (LLM) controls its own pacing — it decides how long to sleep between turns
- Agents see structured, cached hot state every turn without needing to call tools to get basic context
- Background sensors keep hot state fresh by polling/streaming external data sources
- Sensors can run lightweight ML models (FunctionGemma, Qwen3-1.7B) for pre-filtering
- A pre-check gate avoids wasting full LLM turns when nothing has changed
- Guardrails prevent runaway agents (token budgets, turn limits, rate limits)
- The existing chat and heartbeat flows continue to work unchanged

**Non-Goals:**
- Replacing the existing request-response chat flow (it stays as-is)
- Multi-agent coordination or shared state between autonomous agents (future work)
- A general-purpose sensor marketplace or plugin system
- UI for configuring autonomous agents (can be added later)
- Replacing HeartbeatRunner now (future unification, not this change)

## Decisions

### 1. Agent loop as an asyncio.Task on AgentHandle

**Decision**: The autonomous loop is a long-running `asyncio.Task` stored on `AgentHandle`, similar to how `HeartbeatRunner` works today. When an agent with `autonomy.enabled: true` starts, the loop task starts alongside it.

**Why not a separate process/thread**: Everything in openhoof is async already. An asyncio task is lightweight, shares the event loop, and has direct access to the agent's handle, tool registry, and inference adapter. No IPC needed.

**Why on AgentHandle**: The loop is agent-scoped. It starts and stops with the agent. Putting it on AgentHandle keeps lifecycle management in one place — `start_agent()` starts the loop, `stop_agent()` stops it.

**Structure**:
```
AgentHandle
  ├── heartbeat: HeartbeatRunner          (existing)
  ├── autonomy_loop: AutonomyLoop         (new)
  ├── hot_state: HotState                 (new)
  └── sensors: List[Sensor]               (new)
```

### 2. Yield as a tool, not a response convention

**Decision**: The agent controls pacing by calling a `yield` tool. The tool accepts `sleep` (seconds), `wake_early_if` (list of event names), `reason` (string), and `mode` ("continue" | "sleep" | "shutdown").

**Alternatives considered**:
- *Response parsing* (agent ends response with `YIELD: sleep=30s`): Fragile, requires regex parsing, mixes control flow with content.
- *Special finish_reason*: Would require modifying the inference adapter, not portable across models.

**Why a tool**: It's consistent with how agents already express intent (tool calls). It produces structured data the runtime can act on. The LLM naturally understands tool calling. The runtime just looks for a `yield` tool call in the response and acts on it.

**If the agent doesn't call yield**: The loop treats this as `yield(mode="continue")` — immediate next turn. The `max_consecutive_turns` guardrail prevents infinite continuation.

### 3. Hot state as an in-memory typed store with TTLs

**Decision**: Hot state is a `HotState` object on the `AgentHandle`. It holds a `Dict[str, HotStateField]` where each field has a value, a timestamp, a TTL, and an optional `refresh_tool` name. The entire hot state is serialized and injected into the system prompt as a structured block before each LLM turn.

**Schema defined in agent.yaml**:
```yaml
hot_state:
  fields:
    positions:
      type: object
      ttl: 30
      refresh_tool: get_positions
    cash:
      type: number
      ttl: 30
      refresh_tool: get_account_balance
    signals_log:
      type: array
      max_items: 20
```

**Why in-memory, not persisted**: Hot state is ephemeral working memory. It's rebuilt from tools/sensors every time the agent starts. Persisting it adds complexity for no benefit — the data would be stale on restart anyway.

**Why TTL-based**: The LLM needs to know if data might be stale. Fields past their TTL are rendered with a staleness marker (e.g., `positions: {...} (stale: 2m ago)`). The agent can then decide to refresh via a tool call, or proceed with stale data.

**Auto-refresh option**: If a field has `refresh_tool` set and is past its TTL, the runtime *can* auto-refresh it before the LLM turn. This is optional per-field — some data is cheap to refresh, some isn't.

### 4. Sensors as async background tasks that update hot state

**Decision**: Each sensor is an `asyncio.Task` that runs a poll/stream loop and writes results into the agent's `HotState`. Sensors are defined in `agent.yaml` and instantiated when the agent starts.

**Sensor types**:
- `poll`: Call a URL or tool at a fixed interval, write result to hot state field
- `watch`: Monitor a file or directory for changes
- `stream`: Connect to a streaming source (WebSocket, SSE), process incoming data

**ML pre-filtering**: A sensor can specify a `model` that runs on each data point. The model produces a score, and the sensor only updates hot state (or pushes a notification) if the score exceeds a threshold. This uses the existing `InferenceAdapter` with lightweight models.

**Notifications**: Sensors can push high-priority alerts to a notification queue on the `HotState`. These appear at the top of the agent's context on the next turn and are cleared after the agent sees them.

**Sensor config**:
```yaml
sensors:
  - name: price_feed
    type: poll
    interval: 5
    source:
      tool: get_market_data
      params: {symbols: [AAPL, TSLA, SPY]}
    updates:
      - field: last_prices
      - field: indicators
    signals:
      - name: anomaly
        model: qwen3-1.7b
        prompt: "Is this price action anomalous? Score 0-1."
        threshold: 0.8
        notify: true
```

### 5. Pre-check gate using a lightweight model

**Decision**: Before each full LLM turn, the loop runs a cheap pre-check: a small model (FunctionGemma or Qwen3-1.7B) receives a diff of what changed in hot state since the last turn. If nothing material changed, the turn is skipped and the loop extends the sleep.

**Why a model and not just code**: Simple threshold checks could miss context-dependent importance. A small model can understand "RSI went from 31 to 30 — that crossed a threshold" vs. "RSI went from 55 to 54 — irrelevant." But the pre-check prompt should be kept minimal for speed.

**Fallback**: If no pre-check model is configured, or if notifications are pending, the gate is always open (every turn runs the full LLM).

### 6. Turn lifecycle within the loop

**Decision**: Each autonomous turn follows this sequence:

```
1. Collect hot state snapshot (including staleness markers)
2. Collect pending notifications
3. Run pre-check gate (skip turn if nothing changed, no notifications)
4. Auto-refresh stale fields with refresh_tool (if configured)
5. Build context: system prompt + hot state + notifications + recent history
6. Call _run_agent_turn() with a synthetic "observe" message
7. Parse response for yield tool call
8. Record turn in transcript (with hot state summary)
9. Act on yield: sleep, continue, or shutdown
10. Check guardrails: token budget, consecutive turns, idle timeout
```

The existing `_run_agent_turn()` is reused for step 6. The autonomous loop wraps it with pre-check, state injection, and yield handling.

### 7. Guardrails as hard limits on the loop

**Decision**: Guardrails are enforced by the loop runner, not by the LLM. The agent cannot override them.

```yaml
autonomy:
  enabled: true
  max_consecutive_turns: 50      # hard cap on turns without sleeping
  token_budget_per_hour: 100000  # pause agent if exceeded
  max_actions_per_minute: 10     # rate limit on tool calls that have side effects
  idle_timeout: 600              # shutdown after 10m of no meaningful activity
  active_hours:                  # optional, inherited from heartbeat concept
    start: "08:00"
    end: "23:00"
```

When a guardrail triggers, the loop emits an event and either forces a sleep or stops the agent.

### 8. Configuration extension to agent.yaml

**Decision**: Three new top-level sections in `agent.yaml`: `autonomy`, `hot_state`, and `sensors`. All are optional — agents without them behave exactly as they do today.

`AgentConfig` gets new optional fields parsed from these sections. `AgentConfig.from_yaml()` is extended to read them. Agents with `autonomy.enabled: false` (or omitted) are purely reactive.

### 9. Event bus integration

**Decision**: The autonomous loop emits events for observability:

- `autonomy:turn_started` — with turn number, hot state summary
- `autonomy:turn_completed` — with action taken, yield decision
- `autonomy:precheck_skipped` — when pre-check gate blocks a turn
- `autonomy:guardrail_triggered` — when a limit is hit
- `autonomy:sensor_updated` — when a sensor writes to hot state
- `autonomy:notification_pushed` — when a sensor pushes an alert

These flow through the existing event bus to WebSocket clients and the UI.

## Risks / Trade-offs

**[Token consumption]** → Brain-driven means LLM runs every turn even during quiet periods. Mitigated by: pre-check gate skipping idle turns, adaptive sleep durations chosen by the agent, token budget guardrail, local inference making cost practical.

**[Runaway agent]** → An agent in a tight loop could burn resources or take many actions quickly. Mitigated by: `max_consecutive_turns`, `max_actions_per_minute`, `token_budget_per_hour`, and `idle_timeout` guardrails enforced at the loop level.

**[Hot state memory growth]** → Arrays in hot state (like signal logs) could grow unbounded. Mitigated by: `max_items` config per array field, enforced on write.

**[Sensor failures]** → A sensor that can't reach its data source could error repeatedly. Mitigated by: exponential backoff on sensor errors, error events emitted for observability, sensor does not crash the agent loop.

**[Context window pressure]** → Hot state + notifications + history could exceed the model's context. Mitigated by: hot state schema limits what's injected, `max_items` on arrays, existing transcript auto-compaction, and the pre-check gate reducing unnecessary turns.

**[Complexity of two execution modes]** → Agents can now be reactive (chat) or autonomous (loop), and potentially both at the same time. Mitigated by: autonomous loop uses the same `_run_agent_turn()` as chat, just with a synthetic message. Concurrent chat messages during autonomous operation use separate session keys to avoid transcript collisions.

## Open Questions

- **Should chat messages interrupt the autonomous loop?** If a user sends a chat while the agent is in an autonomous sleep, should it wake immediately? Leaning yes — the chat response would use the main session, and the autonomous loop would resume after.
- **How to handle tool calls that require approval during autonomous mode?** The approval queue exists, but autonomous agents might need to pause their loop while waiting for approval rather than continuing.
