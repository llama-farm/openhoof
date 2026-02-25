# Built-in Tools for OpenHoof (Edge Runtime)

**Scope:** Minimal toolset for autonomous edge agents (Android phones, embedded devices, offline operation).

**NOT included:** Browser, web search, gateway/cron, messaging, canvas, sub-agents (too heavy/network-dependent).

---

## Core Philosophy

Edge agents need **self-sufficiency**:
- Memory recall (semantic search in MEMORY.md)
- Time awareness (schedule wakeups, check timestamps)
- State persistence (save/restore across restarts)
- Health monitoring (battery, disk, network status)
- Logging (capture decisions/events for later sync)

---

## Proposed Built-in Tools

### 1. Memory Tools

**`memory_search(query: str, max_results: int = 5)`**
- Semantic search across MEMORY.md + memory/*.md
- Returns: `[{path, line_start, line_end, snippet, score}]`
- Use case: "What altitude did we fly last mission?"

**`memory_append(content: str, path: str = "MEMORY.md")`**
- Append to MEMORY.md or daily log
- Timestamp automatically added
- Use case: Log decisions, observations, outcomes

**`memory_read(path: str, from_line: int = None, lines: int = None)`**
- Read specific section from memory file
- Use case: Pull full context after search hit

---

### 2. Time & Scheduling

**`get_time()`**
- Returns: `{timestamp, iso, timezone, date, time, day_of_week}`
- Use case: Timestamping events, checking time-based conditions

**`schedule_wakeup(when: str, reason: str)`**
- Schedule future agent wake (stored in .microclaw/wakeups.json)
- `when`: ISO timestamp or relative ("in 5 minutes", "at 14:00")
- Use case: "Wake me when battery > 80%" or "Check weather in 1 hour"

**`list_wakeups()`**
- List all pending wakeups
- Returns: `[{id, when, reason, created}]`

**`cancel_wakeup(id: str)`**
- Cancel a scheduled wakeup

---

### 3. State Persistence

**`save_state(key: str, value: any)`**
- Save agent state to .microclaw/state.json
- Use case: Checkpoint mission progress, remember last waypoint

**`load_state(key: str)`**
- Load saved state
- Returns: value or null

**`list_state()`**
- List all saved state keys
- Returns: `[{key, updated, size}]`

---

### 4. Health & System

**`get_health()`**
- Returns system health metrics:
  - `battery_percent`, `charging`
  - `disk_free_mb`, `disk_total_mb`
  - `memory_free_mb`, `memory_total_mb`
  - `network_available`, `network_type` (wifi/cellular/none)
  - `gps_available`, `location` (if available)
- Use case: Exit conditions, DDIL decisions

**`set_exit_condition(name: str, check: str)`**
- Register exit condition (JSON-serializable check)
- Example: `{"battery_percent": {"<": 20}}`
- Checked on every heartbeat

**`list_exit_conditions()`**
- List all active exit conditions

---

### 5. Logging

**`log(message: str, level: str = "info")`**
- Write to daily log (memory/YYYY-MM-DD.md)
- Levels: debug, info, warn, error
- Auto-timestamps

**`read_logs(date: str = "today", limit: int = 100)`**
- Read recent log entries
- Use case: Review what happened today

---

### 6. File I/O (Context Files Only)

**`read_soul()`**
- Returns current SOUL.md content
- Use case: Self-reflection, check mission

**`read_user()`**
- Returns USER.md content
- Use case: Check user preferences

**`read_file(path: str)`**
- Read file (restricted to workspace)
- Security: No path traversal, workspace-only

**`write_file(path: str, content: str)`**
- Write file (restricted to workspace)
- Use case: Generate reports, save telemetry

---

## What's NOT Included (by design)

❌ **Browser automation** — Too heavy for edge  
❌ **Web search/fetch** — Requires internet  
❌ **Gateway/cron** — No gateway on edge  
❌ **Messaging** — Buffered via DDIL, synced later  
❌ **Canvas** — Display not available on headless edge  
❌ **Sub-agents** — Too resource-intensive  
❌ **Shell exec** — Security risk on mobile  

---

## Implementation Plan

1. **Phase 1 (Python):** Implement all tools as simple functions
2. **Phase 2 (Kotlin):** Port to Android-compatible Kotlin
3. **Phase 3 (Rust):** FFI bindings for cross-platform core

**File structure:**
```
openhoof/
├── builtin_tools/
│   ├── __init__.py
│   ├── memory.py      # memory_search, memory_append, memory_read
│   ├── time.py        # get_time, schedule_wakeup, list_wakeups
│   ├── state.py       # save_state, load_state, list_state
│   ├── health.py      # get_health, set_exit_condition
│   ├── logging.py     # log, read_logs
│   └── files.py       # read_soul, read_user, read/write_file
```

**Usage:**
```python
from openhoof import Agent
from openhoof.builtin_tools import BUILTIN_TOOLS, builtin_executor

agent = Agent(
    soul="SOUL.md",
    memory="MEMORY.md",
    tools=BUILTIN_TOOLS + drone_tools,  # Merge with custom tools
    executor=builtin_executor  # Handles routing
)

# Agent can now:
# - Search memory: memory_search("last waypoint")
# - Log events: log("Battery at 45%, landing soon")
# - Schedule: schedule_wakeup("in 30 minutes", "Check weather")
# - Check health: get_health() -> {battery_percent: 45, ...}
```

---

## Design Principles

1. **No network dependencies** — Everything works offline
2. **Minimal resource usage** — Small memory footprint
3. **JSON-serializable** — All params/results can be logged for training
4. **Idempotent** — Safe to call multiple times
5. **Workspace-scoped** — File operations stay in bounds
6. **Training-ready** — Every call captured for fine-tuning

---

## Questions for Rob

1. Should `memory_search` use FAISS (requires numpy) or lightweight SQLite FTS?
2. Should `schedule_wakeup` trigger actual Android alarms, or just set metadata?
3. Should `get_health` query Android APIs directly (Kotlin) or via shell?
4. Do we need `send_notification(title, body)` for local Android notifications?
5. Do we need `get_location()` as a separate tool, or part of `get_health()`?

---

## Priority Order (MVP)

**Must-have (Phase 1):**
1. `memory_search`, `memory_append`, `memory_read`
2. `get_time`
3. `log`, `read_logs`
4. `save_state`, `load_state`

**Nice-to-have (Phase 2):**
5. `schedule_wakeup`, `list_wakeups`, `cancel_wakeup`
6. `get_health`
7. `set_exit_condition`, `list_exit_conditions`

**Optional (Phase 3):**
8. `read_soul`, `read_user`
9. `read_file`, `write_file` (if needed)
