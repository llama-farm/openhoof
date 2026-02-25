# Agent Templates & Context Injection

**Question:** Should OpenHoof have templated agents with CORE building blocks?

**Answer:** YES! Based on OpenClaw's proven pattern.

---

## What OpenClaw Does

**Context files loaded into every session:**

```
Session Start
  ↓
Load context files → Build system prompt
  ↓
├─ SOUL.md       (who you are, mission, tone, hard rules)
├─ AGENTS.md     (operating instructions, memory system)
├─ USER.md       (who you're helping, preferences)
├─ TOOLS.md      (local tool notes, environment-specific config)
├─ HEARTBEAT.md  (optional: checklist for heartbeat polls)
├─ IDENTITY.md   (name, emoji, avatar - for UI display)
├─ BOOTSTRAP.md  (one-time first-run ritual, then deleted)
└─ memory/       (today + yesterday + MEMORY.md for main sessions)
  ↓
Inject into system prompt
  ↓
Agent runs with full context
```

**System prompt structure:**
```
{SOUL.md content}

---

You are {name} {emoji}.

Follow the mission and principles above.
{Additional injected context from AGENTS.md, USER.md, etc.}
```

---

## What OpenHoof Should Do

**Same pattern, optimized for edge:**

1. **Template files** for quick agent scaffolding
2. **Context file loader** (soul.py, memory.py already exist)
3. **System prompt builder** that combines all context
4. **Bootstrap command** to create new agent workspace

---

## Proposed File Structure

```
openhoof/
├── templates/              # Default templates
│   ├── SOUL.md            # Identity, mission, tone
│   ├── AGENTS.md          # Operating instructions
│   ├── USER.md            # User profile
│   ├── TOOLS.md           # Tool notes
│   ├── HEARTBEAT.md       # Heartbeat checklist
│   ├── IDENTITY.md        # Name, emoji (for UI)
│   └── BOOTSTRAP.md       # First-run ritual
└── builtin_tools/         # Built-in tools (memory, time, logging, etc.)
```

**Agent workspace:**
```
~/.openhoof/agents/<agent-id>/
├── SOUL.md               # Copied from template, customized
├── AGENTS.md
├── USER.md
├── TOOLS.md
├── HEARTBEAT.md
├── IDENTITY.md
├── BOOTSTRAP.md          # Deleted after first run
├── MEMORY.md             # Long-term curated memory
├── memory/
│   ├── 2026-02-20.md    # Daily logs
│   ├── 2026-02-21.md
│   └── missions/
│       └── patrol-001.json  # Archived mission conversations
└── .microclaw/
    ├── state.json        # Persistent state (save_state/load_state)
    ├── wakeups.json      # Scheduled wakeups
    ├── training/         # Training data capture
    └── ddil/             # Store-and-forward buffer
```

---

## Bootstrap Command

```bash
# Create new agent from templates
openhoof init drone-agent

# Prompt for:
# - Agent name: "DroneBot"
# - Emoji: "🚁"
# - Mission: "Autonomous aerial patrol and reconnaissance"
# - User name: "Rob"

# Creates ~/.openhoof/agents/drone-agent/ with populated templates
```

**Python API:**
```python
from openhoof import bootstrap_agent

bootstrap_agent(
    agent_id="drone-agent",
    name="DroneBot",
    emoji="🚁",
    mission="Autonomous aerial patrol and reconnaissance",
    workspace="~/.openhoof/agents/drone-agent"
)
```

---

## Template Files (Minimal for Edge)

### SOUL.md (Edge Template)

```markdown
# SOUL.md - Who You Are

- **Name:** {AGENT_NAME}
- **Emoji:** {EMOJI}
- **Mission:** {MISSION}

## Core Principles

**Be autonomous.** You run offline on edge devices. Make decisions independently.

**Be efficient.** You have limited battery, memory, and CPU. Don't waste resources.

**Be reliable.** Log everything. Capture training data. Handle failures gracefully.

**Be safe.** Don't execute unsafe commands. Ask before risky actions.

## Boundaries

- Log decisions to MEMORY.md
- Check exit conditions on every heartbeat
- Buffer data when offline (DDIL)
- Never block for > 1 second on edge operations

## Continuity

You wake up fresh each session. Your memory lives in:
- MEMORY.md (long-term)
- memory/YYYY-MM-DD.md (daily logs)
- .microclaw/state.json (persistent state)

Read them before acting.
```

### AGENTS.md (Edge Template)

```markdown
# AGENTS.md - Operating Instructions

## Every Session

Before responding:
1. Read SOUL.md (your identity)
2. Read USER.md (your human)
3. Read MEMORY.md (long-term memory)
4. Read memory/{today}.md (recent context)

## Memory System

**Daily logs:** memory/YYYY-MM-DD.md
- Raw timestamped events
- Tool calls, decisions, observations

**Long-term:** MEMORY.md
- Curated knowledge
- Important decisions
- Learned patterns
- Exit conditions

**State:** .microclaw/state.json
- Mission checkpoints
- Last known position
- Configuration

## Heartbeat Checks

Every 30 seconds:
1. Check battery (exit if < 20%)
2. Check exit conditions
3. Check scheduled wakeups
4. Sync DDIL buffer if network available

## Context Management

**Mission lifecycle:**
- `mission_start()` → Clear context, fresh start
- `checkpoint()` every 15 turns → Prune old messages
- `mission_complete()` → Archive + clear

**Hard limits:**
- Max 30 conversation turns in memory
- Auto-checkpoint every 15 turns
- Keep only last 5 turns after checkpoint

## Safety

- `trash` > `rm`
- Log before risky actions
- Ask before network operations
- Check exit conditions on every heartbeat
```

### USER.md (Edge Template)

```markdown
# USER.md - About Your Human

- **Name:** {USER_NAME}
- **What to call them:** {USER_NAME}
- **Timezone:** {TIMEZONE}

## Context

{CONTEXT}

## Preferences

- Prefers concise responses
- Wants autonomous operation
- Trusts agent to make tactical decisions
```

### HEARTBEAT.md (Edge Template)

```markdown
# HEARTBEAT.md - Heartbeat Checklist

Keep this SHORT to avoid token burn.

## Every Heartbeat

1. Check battery level → Exit if < 20%
2. Check scheduled wakeups → Execute if due
3. Check DDIL buffer → Sync if network available
4. Review exit conditions → Trigger if met

## State to Track

```json
{
  "last_heartbeat": 1708470000,
  "battery_percent": 85,
  "network_available": false,
  "ddil_pending": 3,
  "mission_active": true
}
```

If nothing needs attention: `HEARTBEAT_OK`
```

### IDENTITY.md (Edge Template)

```markdown
# IDENTITY.md

- **name:** {AGENT_NAME}
- **emoji:** {EMOJI}
- **theme:** edge autonomous agent
```

### TOOLS.md (Edge Template)

```markdown
# TOOLS.md - Local Tool Notes

## Built-in Tools

- `memory_search(query)` — Search MEMORY.md + daily logs
- `memory_append(content)` — Write to MEMORY.md or daily log
- `get_time()` — Current timestamp
- `log(message, level)` — Write to daily log
- `save_state(key, value)` — Persist state
- `load_state(key)` — Restore state
- `checkpoint(summary, clear)` — Save context + optional clear
- `mission_start(id, objective)` — Begin mission
- `mission_complete(summary, outcome)` — End + archive
- `get_health()` — Battery, disk, memory, network, GPS

## Custom Tools

{CUSTOM_TOOL_NOTES}
```

---

## System Prompt Builder

```python
# openhoof/prompt.py

class PromptBuilder:
    """Build system prompt from context files."""
    
    def __init__(self, workspace: str):
        self.workspace = Path(workspace)
    
    def build_system_prompt(self, session_type: str = "main") -> str:
        """
        Build system prompt from context files.
        
        Args:
            session_type: "main" (load MEMORY.md) or "group" (skip MEMORY.md)
        """
        parts = []
        
        # Always load core context
        parts.append(self._load_file("SOUL.md"))
        parts.append(self._load_file("AGENTS.md"))
        parts.append(self._load_file("USER.md"))
        parts.append(self._load_file("TOOLS.md"))
        
        # Load MEMORY.md only in main sessions (not shared contexts)
        if session_type == "main":
            if (self.workspace / "MEMORY.md").exists():
                parts.append("# Long-Term Memory\n")
                parts.append(self._load_file("MEMORY.md"))
        
        # Load recent daily logs (today + yesterday)
        parts.append(self._load_recent_logs())
        
        # Combine all parts
        return "\n\n---\n\n".join(filter(None, parts))
    
    def _load_file(self, filename: str) -> str:
        """Load file from workspace."""
        path = self.workspace / filename
        if path.exists():
            return path.read_text()
        return ""
    
    def _load_recent_logs(self) -> str:
        """Load today + yesterday from memory/."""
        from datetime import datetime, timedelta
        
        logs = []
        memory_dir = self.workspace / "memory"
        
        if not memory_dir.exists():
            return ""
        
        # Today + yesterday
        for i in range(2):
            date = datetime.now() - timedelta(days=i)
            log_file = memory_dir / f"{date.strftime('%Y-%m-%d')}.md"
            if log_file.exists():
                logs.append(f"# {date.strftime('%Y-%m-%d')}\n{log_file.read_text()}")
        
        if logs:
            return "# Recent Memory\n\n" + "\n\n".join(logs)
        return ""
```

**Usage:**
```python
from openhoof import Agent, PromptBuilder

builder = PromptBuilder("~/.openhoof/agents/drone-agent")
system_prompt = builder.build_system_prompt(session_type="main")

agent = Agent(
    soul="SOUL.md",  # Loaded separately for metadata
    memory="MEMORY.md",
    tools=tools,
    executor=executor
)

# Agent.soul.to_system_prompt() already builds this
# But we can override:
agent.system_prompt = builder.build_system_prompt()
```

---

## Implementation Plan

**Phase 1: Templates + Bootstrap**
1. Create `openhoof/templates/` with all 7 template files
2. Implement `bootstrap_agent()` function
3. Add CLI: `openhoof init <agent-id>`
4. Test: Create new agent, verify all files present

**Phase 2: Context Loading**
5. Implement `PromptBuilder` class
6. Update `Agent.__init__()` to use PromptBuilder
7. Add session_type support ("main" vs "group")
8. Test: Agent loads full context correctly

**Phase 3: Built-in Tools**
9. Implement memory tools (search, append, read)
10. Implement time tools (get_time, schedule_wakeup)
11. Implement logging tools (log, read_logs)
12. Implement state tools (save/load/list_state)
13. Implement context tools (checkpoint, mission_start/complete)
14. Test: All built-in tools work with drone scenario

---

## Questions for Rob

1. Should templates be embedded in Python (importlib.resources) or external files?
2. Should `openhoof init` be a Python CLI or bash script?
3. Do we need BOOTSTRAP.md for edge agents, or skip it?
4. Should IDENTITY.md be separate, or merge into SOUL.md?
5. Should we support multiple agent profiles in one workspace?

---

## Benefits

✅ **Fast agent creation** — `openhoof init drone-agent` → ready workspace  
✅ **Consistent structure** — All agents use same file layout  
✅ **OpenClaw-compatible** — Same patterns, proven in production  
✅ **Training-ready** — Daily logs + training data capture built-in  
✅ **Edge-optimized** — Minimal, offline-first templates  

This gives new users **instant scaffolding** instead of starting from scratch!
