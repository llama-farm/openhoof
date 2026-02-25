# Token Budget Strategy for Edge Agents

**Problem:** Edge models have limited context windows. Can't afford 10,000 token system prompts.

**Constraints:**
- llama3.2-1b (mobile): 2048 tokens total
- qwen2.5:8b (laptop): 8192 tokens total
- Need room for: system prompt + conversation + tool results

---

## Token Budget Allocation

**For mobile (2048 tokens total):**
```
System prompt:     300 tokens  (15%)
Conversation:      1200 tokens (60%)
Tool results:      400 tokens  (20%)
Buffer:            148 tokens  (7%)
```

**For laptop (8192 tokens total):**
```
System prompt:     800 tokens  (10%)
Conversation:      5000 tokens (61%)
Tool results:      2000 tokens (24%)
Buffer:            392 tokens  (5%)
```

---

## Minimal Context File Strategy

### What to ALWAYS inject (base system prompt)

**SOUL.md (core only) — 200 tokens max**
```markdown
You are {NAME} {EMOJI}. {ONE_LINE_MISSION}.

Core rules:
- Be autonomous and efficient
- Log important decisions
- Check exit conditions on heartbeat
- Buffer data when offline
```

**That's it.** Everything else is loaded **on demand via tools**.

---

## What to load ON DEMAND (via built-in tools)

### Instead of injecting MEMORY.md → Use memory_search()

**Old way (bad for edge):**
```
System prompt = SOUL + AGENTS + USER + MEMORY.md (1000+ tokens)
```

**New way (token-efficient):**
```python
# System prompt: Just SOUL.md (200 tokens)

# Agent needs context?
memory_search("what altitude did we fly last mission?")
# → Returns 3 relevant snippets (50-100 tokens)

# Agent needs user info?
read_user()  # Only when needed
# → Returns USER.md (50 tokens)

# Agent needs operating instructions?
read_agents()  # Only when needed
# → Returns AGENTS.md (400 tokens)
```

### Built-in tools for lazy loading

```python
# Context loading tools
read_soul()        # SOUL.md (200 tokens)
read_user()        # USER.md (50 tokens)
read_agents()      # AGENTS.md (400 tokens)
read_heartbeat()   # HEARTBEAT.md (50 tokens)

# Memory tools (semantic search, not full load)
memory_search(query, max_results=3)  # 50-100 tokens
memory_append(content)
read_logs(date="today", limit=5)     # Last 5 entries only

# Heartbeat tools
read_priorities()  # Current priorities only
check_exit_conditions()
```

---

## Ultra-Minimal Templates

### SOUL.md (200 tokens max)

```markdown
You are {NAME} {EMOJI}. {MISSION}.

Rules:
- Log decisions
- Check exit on heartbeat
- Buffer offline data
- Be efficient

If you need context: use memory_search(). If you need instructions: use read_agents().
```

**That's the ENTIRE system prompt for edge agents.**

### AGENTS.md (400 tokens, lazy-loaded)

```markdown
# Operating Instructions

Session start:
1. Check battery (exit if <20%)
2. Load last mission state
3. Review priorities

Memory:
- Log to memory/YYYY-MM-DD.md
- Search with memory_search()
- No "mental notes" - write to file

Heartbeat:
- Check exit conditions
- Sync DDIL if network up
- Execute scheduled wakeups

Context:
- Mission lifecycle: start → checkpoint → complete
- Max 30 turns, auto-prune at 15
- Use checkpoint() to save state

Safety:
- trash > rm
- Log before risky actions
```

### USER.md (50 tokens, lazy-loaded)

```markdown
Name: {NAME}
TZ: {TIMEZONE}
Notes: {ONE_LINE_CONTEXT}
```

### HEARTBEAT.md (50 tokens, lazy-loaded)

```markdown
Check: battery, exit conditions, wakeups, DDIL
If nothing: HEARTBEAT_OK
```

---

## Smart Loading Strategy

### Base system prompt (ALWAYS loaded)

```python
def build_base_prompt(soul: Soul) -> str:
    """Minimal base prompt - just SOUL.md core."""
    return f"""You are {soul.name} {soul.emoji}. {soul.mission}.

Core rules:
- Log decisions to memory
- Check exit conditions on heartbeat  
- Buffer data when offline (DDIL)
- Be efficient (limited tokens/battery)

Context tools (use when needed):
- memory_search(query) - search memory
- read_user() - user info
- read_agents() - operating instructions
- read_heartbeat() - heartbeat checklist

If you need to remember something, use memory_append().
If you need past context, use memory_search().
"""
```

**Token count:** ~150-200 tokens

### Dynamic context injection (only when needed)

```python
# Agent decides when to load more context
agent.reason("What should I do next?")

# LLM might call:
read_agents()  # "I need operating instructions"
# → Loads AGENTS.md (400 tokens) into conversation

memory_search("last mission altitude")  # "What happened before?"
# → Returns 3 snippets (50-100 tokens)

read_user()  # "Who am I helping?"
# → Loads USER.md (50 tokens)
```

---

## Token-Efficient Patterns

### Pattern 1: Just-in-time loading

```python
# Don't inject MEMORY.md (1000+ tokens)
# Instead, inject search capability

System prompt:
"To recall information, use memory_search(query)."

Agent calls:
memory_search("battery threshold") → Returns relevant snippet
```

### Pattern 2: Hierarchical memory

```
System prompt (200 tokens)
  ↓ if needed
Read operating instructions (400 tokens)
  ↓ if needed
Search memory (50-100 tokens per query)
  ↓ if needed
Read full context file (on demand)
```

### Pattern 3: Semantic compression

```python
# Old: Inject full MEMORY.md (2000 tokens)
# New: Index MEMORY.md, return only relevant snippets

memory_search("waypoint navigation") 
# → Returns 3 snippets (100 tokens) instead of full file
```

---

## Updated Agent Init

```python
agent = Agent(
    soul="SOUL.md",           # Loaded for base prompt (200 tokens)
    memory="MEMORY.md",       # Indexed for search (not injected!)
    workspace="~/.openhoof/agents/drone",
    max_system_tokens=200     # Hard limit on base prompt
)

# System prompt = just SOUL.md core (200 tokens)
# Everything else loaded on demand via tools
```

---

## Built-in Tools for Context Loading

```python
CONTEXT_TOOLS = [
    {
        "name": "read_user",
        "description": "Read USER.md (who you're helping). Only call when you need user context.",
        "parameters": {}
    },
    {
        "name": "read_agents", 
        "description": "Read AGENTS.md (operating instructions). Only call when you need guidance.",
        "parameters": {}
    },
    {
        "name": "read_heartbeat",
        "description": "Read HEARTBEAT.md (heartbeat checklist).",
        "parameters": {}
    },
    {
        "name": "memory_search",
        "description": "Search MEMORY.md + daily logs. Use this instead of loading full memory.",
        "parameters": {
            "query": "str",
            "max_results": "int (default 3)"
        }
    }
]
```

---

## Comparison: Old vs New

### Old approach (OpenClaw-style)

```
System prompt = 
  SOUL.md (500 tokens)
  + AGENTS.md (1000 tokens)
  + USER.md (100 tokens)
  + TOOLS.md (200 tokens)
  + HEARTBEAT.md (100 tokens)
  + MEMORY.md (2000 tokens)
  + memory/today.md (500 tokens)
  
Total: 4400 tokens
Remaining for conversation: 3792 tokens (8192 - 4400)
```

### New approach (edge-optimized)

```
System prompt =
  SOUL.md core (200 tokens)
  
Total: 200 tokens
Remaining for conversation: 7992 tokens (8192 - 200)

Context loaded on demand via tools:
- read_agents() → 400 tokens (only when needed)
- memory_search() → 50-100 tokens per query
- read_user() → 50 tokens (only when needed)
```

**Result:** 20x more room for conversation and tool results!

---

## Implementation Changes

### 1. Minimal SOUL.md template

```python
SOUL_TEMPLATE = """You are {name} {emoji}. {mission}.

Rules: Log decisions, check exit on heartbeat, buffer offline, be efficient.
Context tools: memory_search(), read_user(), read_agents().
"""
```

### 2. Built-in context loading tools

```python
# openhoof/builtin_tools/context.py

def read_user(agent) -> dict:
    """Read USER.md only when needed."""
    user_md = agent.workspace / "USER.md"
    if user_md.exists():
        return {"content": user_md.read_text()[:500]}  # Max 500 chars
    return {"content": "No user info available"}

def read_agents(agent) -> dict:
    """Read AGENTS.md only when needed."""
    agents_md = agent.workspace / "AGENTS.md"
    if agents_md.exists():
        return {"content": agents_md.read_text()[:2000]}  # Max 2000 chars
    return {"content": "No operating instructions"}
```

### 3. Memory search instead of full inject

```python
def memory_search(agent, query: str, max_results: int = 3) -> dict:
    """Semantic search instead of full MEMORY.md load."""
    # SQLite FTS search
    results = agent.memory.search(query, max_results)
    
    # Return only snippets (not full file)
    return {
        "results": [
            {
                "snippet": r.snippet,
                "source": f"{r.path}#{r.line}",
                "score": r.score
            }
            for r in results
        ]
    }
```

---

## Token Monitoring

```python
# Track token usage
agent.token_budget = TokenBudget(
    max_system=200,      # System prompt limit
    max_conversation=1200,  # Conversation history limit
    max_tools=400         # Tool results limit
)

# Auto-prune if exceeded
if agent.token_budget.exceeded():
    agent.prune_conversation()
```

---

## Questions for Rob

1. Should system prompt be literally just SOUL.md core (~200 tokens)?
2. Should AGENTS.md/USER.md/HEARTBEAT.md be tools, or injected?
3. Should we enforce hard token limits per file (SOUL.md max 200 tokens)?
4. Should memory_search() replace MEMORY.md injection entirely?
5. Do we need token counting (estimate) or just character limits?

---

## Recommended Approach

**Mobile (llama3.2-1b, 2048 tokens):**
- System prompt: SOUL.md core only (200 tokens)
- Everything else: loaded on demand via tools
- Aggressive pruning: keep last 10 turns max

**Laptop (qwen2.5:8b, 8192 tokens):**
- System prompt: SOUL.md core (200 tokens)
- Optional: Auto-load read_agents() on first turn (400 tokens)
- Standard pruning: keep last 30 turns

**Both:**
- MEMORY.md never injected, only searched
- Daily logs: last 5 entries max, not full file
- USER.md: loaded on demand, not by default

This keeps token usage under control while maintaining capability! 🚀
