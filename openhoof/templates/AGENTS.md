# AGENTS.md - Operating Instructions

## Every Session

Before responding:
1. Check current mission state (`load_state("mission")`)
2. Search memory for relevant context (`memory_search(query)`)
3. Review priorities if available (`read_heartbeat()`)

## Memory System

**Daily logs:** `memory/YYYY-MM-DD.md`
- Use `log(message, level)` for timestamped events
- Use `memory_append(content)` for important decisions

**Long-term:** `MEMORY.md`
- Search with `memory_search(query)` (returns top 3 snippets)
- Append important learnings with `memory_append(content, "MEMORY.md")`

**State:** `.microclaw/state.json`
- Use `save_state(key, value)` to persist data
- Use `load_state(key)` to restore

## Mission Lifecycle

1. **Start mission:**
   ```
   mission_start("patrol-001", "Patrol 5 waypoints")
   ```
   Clears conversation history, logs to MEMORY.md

2. **During mission:**
   ```
   checkpoint("Waypoint 3 complete, battery 70%")
   ```
   Saves progress, optionally clears history with `clear=True`

3. **End mission:**
   ```
   mission_complete("Patrol successful", "success")
   ```
   Archives conversation, clears working memory

## Context Management

**Hard limits:**
- Max 30 conversation turns in memory
- Auto-checkpoint every 15 turns
- Use `checkpoint(summary, clear=True)` to manually clear

**Emergency cleanup:**
```
clear_history(keep_last=5)
```

## Heartbeat Checks

Every heartbeat:
1. Check exit conditions (battery, time limits)
2. Check scheduled wakeups
3. Sync DDIL buffer if network available
4. Execute any pending tasks

If nothing needs attention: `HEARTBEAT_OK`

## Safety

- `trash` > `rm`
- Log before risky actions
- Check prerequisites before tool calls
- Always verify results
