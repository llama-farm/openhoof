# Context Management for Edge Agents

**Problem:** Context window grows during long missions. Can't afford 2-minute LLM compaction on mobile.

**Solution:** Fast, rule-based cleanup + mission lifecycle pattern.

---

## Core Principles

1. **No LLM summarization** — Too slow for edge (2+ minutes blocked)
2. **Fast pruning** — Simple rules, instant execution (<100ms)
3. **Mission lifecycle** — Clear start/end boundaries
4. **Explicit checkpoints** — Agent decides what to save
5. **Hierarchical memory** — Working memory vs. long-term storage

---

## Memory Hierarchy

```
Working Memory (in-RAM)
  ↓ (every N turns)
Short-term (MEMORY.md)
  ↓ (daily or mission end)
Long-term (memory/YYYY-MM-DD.md or memory/missions/*.json)
  ↓ (training data)
Archive (.microclaw/training/*.jsonl)
```

---

## Strategy 1: Sliding Window (Fastest)

**Concept:** Keep only last N conversation turns.

```python
agent = Agent(
    soul="SOUL.md",
    memory="MEMORY.md",
    max_turns=10,
    max_history_turns=20  # ← Keep last 20 turns max
)

# Every turn:
if len(messages) > max_history_turns:
    # Drop oldest turns (keep system prompt + last N)
    messages = [messages[0]] + messages[-max_history_turns:]
```

**Pros:** Instant, simple  
**Cons:** Loses history  
**Mitigation:** Important stuff already saved in MEMORY.md via built-in tools

---

## Strategy 2: Mission Lifecycle (Best for Drones)

**Concept:** Clear boundaries — start fresh, checkpoint, archive.

```python
# Mission start
agent.mission_start(
    mission_id="patrol-2026-02-20-14:30",
    objective="Patrol 5 waypoints, capture images"
)
# → Clears conversation history
# → Logs mission start to MEMORY.md
# → Creates mission context file

# During mission (agent decides what's important)
agent.reason("Execute waypoint 1")
# ... many tool calls ...
agent.checkpoint("Waypoint 1 complete, battery 85%")
# → Saves key state, prunes verbose tool results

# Mission end
agent.mission_complete(
    summary="Patrol complete, 5 waypoints, 23 images",
    outcome="success"
)
# → Archives full conversation to memory/missions/patrol-2026-02-20-14:30.json
# → Clears working memory
# → Appends summary to MEMORY.md
```

**Pros:** Clean lifecycle, preserves important context  
**Cons:** Requires agent/user to trigger start/end  
**Speed:** <100ms (just file I/O)

---

## Strategy 3: Importance-Based Pruning

**Concept:** Keep tool calls + results, drop verbose model reasoning.

```python
def prune_conversation(messages, max_tokens=8000):
    """Fast rule-based pruning."""
    important = []
    
    # Always keep system prompt
    important.append(messages[0])
    
    # Keep last user message
    important.append(messages[-1])
    
    # Keep tool calls + results (compact format)
    for msg in messages[1:-1]:
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            # Keep tool calls but drop long reasoning
            important.append({
                "role": "assistant",
                "tool_calls": msg["tool_calls"],
                "content": None  # Drop verbose reasoning
            })
        elif msg["role"] == "tool":
            # Keep tool results (maybe truncate)
            important.append(msg)
    
    return important
```

**Pros:** Keeps key actions, drops fluff  
**Cons:** More complex than sliding window  
**Speed:** <50ms (just list filtering)

---

## Strategy 4: Explicit Checkpoints

**Concept:** Agent calls `checkpoint(summary)` when it wants to save context.

```python
# Built-in tool
def checkpoint(summary: str, clear: bool = False) -> dict:
    """
    Save current context + summary to MEMORY.md.
    Optionally clear working memory.
    
    Args:
        summary: Human-readable summary of progress
        clear: If True, clear conversation history after saving
    
    Returns:
        {saved: bool, checkpoint_id: str}
    """
    checkpoint_id = f"checkpoint-{int(time.time())}"
    
    # Save to MEMORY.md
    agent.memory.append(f"## {checkpoint_id}\n{summary}\n")
    
    # Optionally archive conversation
    if clear:
        # Save full conversation to memory/checkpoints/{id}.json
        save_checkpoint(checkpoint_id, agent.messages)
        
        # Clear working memory (keep system prompt only)
        agent.messages = [agent.messages[0]]
    
    return {"saved": True, "checkpoint_id": checkpoint_id}
```

**Usage:**
```python
# Agent decides when to checkpoint
agent.reason("Patrol waypoints 1-3")
# ... many turns ...
agent.call_tool("checkpoint", {
    "summary": "Waypoints 1-3 complete. Battery 70%, no anomalies.",
    "clear": True  # Fresh start for next phase
})
```

**Pros:** Agent has explicit control  
**Cons:** Agent must remember to checkpoint  
**Speed:** <100ms

---

## Recommended Hybrid Approach

Combine all strategies:

```python
agent = Agent(
    soul="SOUL.md",
    memory="MEMORY.md",
    max_turns=10,              # Max reasoning loops per task
    max_history_turns=30,       # Hard limit on conversation length
    auto_checkpoint_turns=15    # Auto-checkpoint every N turns
)

# Mission lifecycle
agent.mission_start("patrol-001")

# Auto-checkpoint every 15 turns (background, non-blocking)
# → Saves summary to MEMORY.md
# → Prunes old turns (keeps last 10)

# Explicit checkpoint when needed
agent.call_tool("checkpoint", {
    "summary": "Phase 1 complete",
    "clear": True
})

# Mission end
agent.mission_complete("Patrol successful")
# → Full archive
# → Clear working memory
```

---

## Built-in Tools Needed

```python
# Mission lifecycle
mission_start(mission_id: str, objective: str)
mission_complete(summary: str, outcome: str)
checkpoint(summary: str, clear: bool = False)

# Manual cleanup
clear_history(keep_last: int = 5)  # Emergency cleanup
get_context_stats()  # {turns: 23, tokens: ~8500, messages: 47}
```

---

## Implementation (Phase 1 - Python)

```python
# openhoof/context.py

class ContextManager:
    def __init__(self, agent, max_history_turns=30, auto_checkpoint_turns=15):
        self.agent = agent
        self.max_history_turns = max_history_turns
        self.auto_checkpoint_turns = auto_checkpoint_turns
        self.turn_count = 0
    
    def should_prune(self):
        """Check if pruning needed."""
        return len(self.agent.messages) > self.max_history_turns
    
    def prune(self):
        """Fast pruning (keep system + last N turns)."""
        if not self.should_prune():
            return
        
        system = self.agent.messages[0]
        recent = self.agent.messages[-self.max_history_turns:]
        
        self.agent.messages = [system] + recent
        self.agent.memory.append(f"[Context pruned, kept last {self.max_history_turns} turns]")
    
    def auto_checkpoint(self):
        """Auto-checkpoint if needed."""
        self.turn_count += 1
        
        if self.turn_count >= self.auto_checkpoint_turns:
            summary = f"Auto-checkpoint after {self.turn_count} turns"
            self.checkpoint(summary, clear=False)
            self.turn_count = 0
    
    def checkpoint(self, summary, clear=False):
        """Save checkpoint."""
        checkpoint_id = f"checkpoint-{int(time.time())}"
        self.agent.memory.append(f"## {checkpoint_id}\n{summary}\n")
        
        if clear:
            # Keep only system prompt
            self.agent.messages = [self.agent.messages[0]]
            self.turn_count = 0
        
        return checkpoint_id
```

---

## Performance Targets

- **Sliding window prune:** <10ms
- **Checkpoint (no LLM):** <100ms
- **Mission archive:** <200ms (file I/O)
- **NEVER block for minutes** ✅

---

## Questions for Rob

1. Should `mission_start()` be a built-in tool, or part of Agent API?
2. Auto-checkpoint every N turns, or only explicit?
3. Should we keep a "hot context" (last 5 turns) always available?
4. Do we need token counting (estimate), or just message count?
5. Should archived missions be queryable later ("what happened on Feb 15 patrol?")?

---

## Phase 1 MVP

**Must-have:**
1. `max_history_turns` (sliding window)
2. `checkpoint(summary, clear)` tool
3. Manual `clear_history()` tool

**Nice-to-have:**
4. `mission_start()` / `mission_complete()`
5. Auto-checkpoint every N turns

**Later:**
6. Mission archive queries
7. Context stats / token estimation
