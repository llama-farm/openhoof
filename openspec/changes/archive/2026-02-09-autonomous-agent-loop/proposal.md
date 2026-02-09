## Why

Openhoof agents are reactive today — they only do work when a user sends a chat message, an external webhook hits `/triggers`, or a heartbeat timer fires. There is no way for an agent to run autonomously, monitor incoming data, make decisions, and act on its own. This change introduces a brain-driven autonomous agent loop where the agent controls its own execution tempo, observes structured state, and decides when to act or wait.

## What Changes

- Add a **brain-driven agent loop** that runs continuously, where the LLM decides what to do next each turn (observe → think → act → yield)
- Add a **yield mechanism** (as a tool) that lets the agent control its own pacing — sleep for N seconds, continue immediately, or wait for a specific event
- Add **hot state** — a structured, typed, cached state object that is auto-injected into every LLM turn, with per-field TTLs and optional auto-refresh via tools
- Add **sensors** — async background tasks that poll or stream external data sources, update hot state, run lightweight ML models for pre-filtering, and push high-priority notifications to an alert queue
- Add a **pre-check gate** — a lightweight model pass before each full LLM turn to determine whether anything has materially changed, avoiding unnecessary reasoning cycles
- Add **autonomy guardrails** — token budgets, max consecutive turns, action rate limits, and idle timeouts to keep autonomous agents bounded
- Extend `agent.yaml` configuration with `autonomy`, `hot_state`, and `sensors` sections
- Extend `AgentHandle` to manage sensor tasks, hot state, and the autonomous loop runner
- Extend `AgentManager` to start/stop autonomous agent loops

## Capabilities

### New Capabilities

- `agent-loop`: The brain-driven observe/think/act/yield execution loop, including turn lifecycle, pre-check gating, and autonomy guardrails (token budgets, turn limits, idle timeout)
- `hot-state`: Structured typed state with schema definition, per-field TTLs, staleness tracking, auto-refresh via tools, and context injection into LLM turns
- `sensors`: Async background data collectors that poll/stream sources, update hot state, run lightweight ML models, and push priority notifications to an alert queue
- `yield-control`: The yield tool that lets agents control pacing — sleep duration, wake-early-if conditions, continue immediately, or shutdown

### Modified Capabilities

_(none — no existing specs to modify)_

## Impact

- **Code**: `openhoof/agents/` (lifecycle, heartbeat, new loop runner), `openhoof/tools/` (yield tool, hot state tools), `openhoof/core/` (hot state store, sensor framework), `openhoof/api/` (agent start/stop for autonomous mode)
- **Config**: `agent.yaml` schema gains `autonomy`, `hot_state`, and `sensors` sections
- **Dependencies**: No new external dependencies expected — sensors use async polling and the existing inference adapters for lightweight model calls
- **Future**: The heartbeat system becomes a degenerate case of a sensor (type: timer) and can eventually be unified into this framework
