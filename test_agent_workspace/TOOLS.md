# TOOLS.md - Tool Usage Guidance

## Built-in Tools

**Memory:**
- `memory_search(query)` - Search MEMORY.md + daily logs (returns top 3)
- `memory_append(content)` - Write to daily log or MEMORY.md
- `memory_read(path, from_line, lines)` - Read specific section

**Time:**
- `get_time()` - Current timestamp, date, time, day

**Logging:**
- `log(message, level)` - Write to daily log with timestamp
- `read_logs(date, limit)` - Read recent log entries

**State:**
- `save_state(key, value)` - Persist data across sessions
- `load_state(key)` - Restore saved data
- `list_state()` - List all saved keys

**Context Loading:**
- `read_user()` - USER.md (~50 tokens)
- `read_agents()` - AGENTS.md (~400 tokens)
- `read_heartbeat()` - HEARTBEAT.md (~50 tokens)
- `read_tool_guide(tool_name)` - Tool usage from this file

**Mission Lifecycle:**
- `mission_start(id, objective)` - Begin mission (clears history)
- `checkpoint(summary, clear)` - Save progress
- `mission_complete(summary, outcome)` - End + archive
- `get_context_stats()` - Check context usage
- `clear_history(keep_last)` - Emergency cleanup

## Custom Tool Notes

Drone operates in geofenced area, max altitude 120m AGL
