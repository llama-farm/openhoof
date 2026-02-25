# Tool Guidance for Autonomous Agents

**Question:** With 10+ tools, how does the agent know which tool to use and how to use it correctly?

**Answer:** Tool schemas provide WHAT, but agents need guidance on WHEN and HOW.

---

## What Tool Schemas Provide

**OpenAI-compatible tool schema:**
```json
{
  "type": "function",
  "function": {
    "name": "drone_takeoff",
    "description": "Command the DJI Mini 4 Pro drone to arm motors and take off, ascending to the default hover altitude (~1.2m AGL). The drone must be on level ground with GPS lock. Returns when takeoff is acknowledged; use drone_get_telemetry to confirm airborne.",
    "parameters": {
      "type": "object",
      "properties": {},
      "required": []
    }
  }
}
```

**This tells the LLM:**
- ✅ WHAT the tool does ("take off and hover")
- ✅ WHAT it needs ("must be on level ground with GPS lock")
- ✅ WHAT to expect ("returns when takeoff acknowledged")
- ❌ WHEN to use it (mission context)
- ❌ HOW to sequence it (before move, after waypoint check)
- ❌ SAFETY constraints (wind limits, battery minimums)

---

## What's Missing: Contextual Guidance

**Problem:** LLM sees 23 drone tools, each with detailed descriptions. How does it know:
1. "Always check battery before takeoff"
2. "Never land without checking ground clearance"
3. "Use drone_goto for waypoints, not manual drone_move"
4. "Capture image AFTER arriving at waypoint"
5. "Return to home if battery < 30%"

**Answer:** TOOLS.md + per-tool usage notes.

---

## How OpenClaw Solves This

### 1. TOOLS.md (workspace-level guidance)

Located at `~/.openclaw/workspace/TOOLS.md`:

```markdown
# TOOLS.md - Tool Usage Notes

## Drone Operations

**Pre-flight checklist:**
1. Check battery > 50% (use get_telemetry)
2. Verify GPS lock (satellites >= 8)
3. Check wind speed < 10 m/s
4. Confirm geofence active

**Flight sequence:**
1. takeoff → wait 3 seconds
2. Check altitude reached (telemetry)
3. Execute waypoints (use drone_goto, not manual moves)
4. Capture images AFTER arrival at each waypoint
5. Return to home when mission complete OR battery < 30%

**Safety rules:**
- NEVER takeoff if battery < 40%
- NEVER fly if wind > 15 m/s
- ALWAYS check altitude before landing
- ALWAYS use geofence constraints

## Tool-Specific Notes

**drone_goto:**
- Use for waypoint navigation (not drone_move)
- Set arrived_m=3.0 for precision waypoints
- Set speed_mps=4.0 for normal flight, 2.0 for precision
- Check telemetry after arrival to confirm position

**drone_capture:**
- Only call after arriving at waypoint
- Wait 2 seconds after arrival for stabilization
- Returns base64 image, check file size > 10KB

**drone_land:**
- Check ground clearance first (use get_telemetry altitude)
- Never land if altitude > 2m (could be over obstacle)
- Wait until motors stop before next action
```

**This tells the agent:**
- ✅ WHEN to use each tool (sequence, conditions)
- ✅ HOW to use tools correctly (parameters, timing)
- ✅ SAFETY constraints (battery, wind, altitude)
- ✅ OPERATIONAL patterns (pre-flight, waypoint sequence)

### 2. Skills (per-tool deep guidance)

OpenClaw has per-skill `SKILL.md` files:

```
~/.openclaw/skills/camsnap/SKILL.md
~/.openclaw/skills/peekaboo/SKILL.md
~/.openclaw/skills/eightctl/SKILL.md
```

Each skill provides:
- Tool installation/setup
- Usage examples
- Parameter explanations
- Common patterns
- Error handling

**But for edge:** Too heavy. Skills are for gateway-based agents with internet access.

---

## What OpenHoof Should Do (Edge-Optimized)

### Strategy 1: Lightweight TOOLS.md (Token-Efficient)

**Instead of auto-injecting TOOLS.md (1000+ tokens), provide a tool to read it:**

```python
# Built-in tool
def read_tool_guide(tool_name: str = None) -> dict:
    """
    Read tool usage guidance from TOOLS.md.
    
    Args:
        tool_name: Specific tool to get guidance for (optional)
    
    Returns:
        {content: str, section: str}
    """
    tools_md = workspace / "TOOLS.md"
    
    if not tools_md.exists():
        return {"content": "No tool guidance available"}
    
    content = tools_md.read_text()
    
    if tool_name:
        # Extract section for specific tool
        section = extract_section(content, tool_name)
        return {"content": section, "section": tool_name}
    
    # Return full guide (truncated if too long)
    return {"content": content[:2000]}  # Max 2KB
```

**Usage:**
```python
# Agent needs to know how to use drone_goto
agent.call_tool("read_tool_guide", {"tool_name": "drone_goto"})
# → Returns just the drone_goto section (50-100 tokens)
```

### Strategy 2: Embed Usage Notes in Tool Schema

**Old schema (minimal):**
```json
{
  "name": "drone_goto",
  "description": "Fly to GPS waypoint",
  "parameters": {...}
}
```

**New schema (with usage notes):**
```json
{
  "name": "drone_goto",
  "description": "Fly to GPS waypoint at specified altitude. Use this for waypoint navigation (preferred over drone_move). Set arrived_m=3.0 for precision. Check telemetry after arrival to confirm position.",
  "parameters": {...},
  "usage_notes": {
    "when_to_use": "Waypoint navigation, not manual flight",
    "prerequisites": ["GPS lock", "Battery > 30%"],
    "best_practices": [
      "Use arrived_m=3.0 for precision waypoints",
      "Set speed_mps=4.0 for normal, 2.0 for precision",
      "Check telemetry after arrival"
    ],
    "safety": [
      "Check battery before long-distance waypoints",
      "Verify geofence allows target coordinates"
    ]
  }
}
```

**Pros:**
- Usage guidance travels with tool schema
- LLM sees it during tool selection
- No extra token cost (only sent to LLM once)

**Cons:**
- Inflates tool schema size
- Not flexible (can't update without re-registering tools)

### Strategy 3: System Prompt Injection (Minimal)

**Add to base system prompt:**
```markdown
You are DroneBot 🚁. Autonomous aerial patrol.

Tool usage rules:
- Check battery before takeoff (> 40%)
- Use drone_goto for waypoints (not drone_move)
- Capture images AFTER arriving at waypoint
- Return home if battery < 30%

For detailed tool guidance, call read_tool_guide(tool_name).
```

**Token cost:** ~50 tokens (acceptable for critical rules)

---

## Recommended Hybrid Approach

### 1. Rich Tool Descriptions (in schema)

```python
DRONE_TOOLS = [
    {
        "name": "drone_takeoff",
        "description": (
            "Arm motors and take off to hover altitude (~1.2m AGL). "
            "Prerequisites: Level ground, GPS lock (satellites >= 8), battery > 40%. "
            "Usage: Call at mission start after checking telemetry. "
            "Wait 3 seconds after return before next command. "
            "Safety: Abort if wind > 15 m/s or battery < 40%."
        ),
        "parameters": {...}
    },
    {
        "name": "drone_goto",
        "description": (
            "Fly to GPS waypoint (lat/lon/alt). "
            "When to use: Waypoint navigation (preferred over drone_move). "
            "Best practice: Set arrived_m=3.0 for precision, speed_mps=4.0 for normal flight. "
            "After arrival: Check telemetry to confirm position within arrived_m. "
            "Safety: Verify geofence allows target before calling."
        ),
        "parameters": {...}
    }
]
```

**Token cost:** ~100-150 tokens per tool (one-time, when tools sent to LLM)

### 2. Minimal System Prompt Rules (~50 tokens)

```markdown
Mission rules:
- Check battery before takeoff (> 40%)
- Use drone_goto for waypoints
- Capture after arrival + 2s stabilization
- RTH if battery < 30%
```

### 3. Optional Deep Guidance (on-demand)

```python
# Built-in tool
read_tool_guide(tool_name="drone_goto")
# → Returns 50-100 token section from TOOLS.md (only when needed)
```

---

## Implementation Plan

### Phase 1: Rich Tool Descriptions

```python
# openhoof/builtin_tools/__init__.py

def create_tool_schema(
    name: str,
    summary: str,
    when_to_use: str = None,
    prerequisites: list = None,
    best_practices: list = None,
    safety: list = None,
    parameters: dict = None
) -> dict:
    """
    Create rich tool schema with embedded usage guidance.
    
    Args:
        name: Tool name
        summary: One-line summary
        when_to_use: When to use this tool (vs alternatives)
        prerequisites: List of prerequisites
        best_practices: List of best practices
        safety: List of safety constraints
        parameters: Parameter schema
    
    Returns:
        OpenAI-compatible tool schema with rich description
    """
    parts = [summary]
    
    if when_to_use:
        parts.append(f"When to use: {when_to_use}.")
    
    if prerequisites:
        parts.append(f"Prerequisites: {', '.join(prerequisites)}.")
    
    if best_practices:
        parts.append(f"Best practice: {' '.join(best_practices)}.")
    
    if safety:
        parts.append(f"Safety: {' '.join(safety)}.")
    
    description = " ".join(parts)
    
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters or {"type": "object", "properties": {}}
        }
    }
```

**Usage:**
```python
drone_takeoff = create_tool_schema(
    name="drone_takeoff",
    summary="Arm motors and take off to hover altitude (~1.2m AGL)",
    when_to_use="Mission start after telemetry check",
    prerequisites=["Level ground", "GPS lock >= 8 sats", "Battery > 40%"],
    best_practices=["Wait 3s after return before next command"],
    safety=["Abort if wind > 15 m/s", "Abort if battery < 40%"]
)
```

### Phase 2: read_tool_guide() Built-in Tool

```python
# openhoof/builtin_tools/context.py

def read_tool_guide(agent, tool_name: str = None) -> dict:
    """
    Read tool usage guidance from TOOLS.md.
    
    Args:
        tool_name: Specific tool section to read (optional)
    
    Returns:
        {content: str, tool: str}
    """
    tools_md = agent.workspace / "TOOLS.md"
    
    if not tools_md.exists():
        return {"content": "No tool guidance file (TOOLS.md) found"}
    
    content = tools_md.read_text()
    
    if tool_name:
        # Extract section for specific tool (## tool_name)
        import re
        pattern = f"## {tool_name}.*?(?=##|$)"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        
        if match:
            section = match.group(0).strip()
            return {"content": section, "tool": tool_name}
        else:
            return {"content": f"No guidance found for {tool_name}"}
    
    # Return full guide (truncated)
    return {"content": content[:2000]}  # Max 2KB
```

### Phase 3: TOOLS.md Template

```markdown
# TOOLS.md - Tool Usage Guidance

## Drone Mission Workflow

1. **Pre-flight**
   - Check battery > 40%: `get_telemetry()`
   - Verify GPS lock >= 8 satellites
   - Check wind speed < 10 m/s
   - Confirm geofence loaded

2. **Takeoff**
   - Call `drone_takeoff()`
   - Wait 3 seconds
   - Verify altitude via telemetry

3. **Waypoint Navigation**
   - Use `drone_goto(lat, lon, alt_m, speed_mps, arrived_m)`
   - Set arrived_m=3.0 for precision
   - Check telemetry after arrival

4. **Image Capture**
   - Arrive at waypoint
   - Wait 2 seconds for stabilization
   - Call `drone_capture()`
   - Verify image size > 10KB

5. **Return to Home**
   - If battery < 30%: `drone_return_to_home()`
   - If mission complete: `drone_land()`

## drone_goto

**When to use:** Waypoint navigation (preferred over manual drone_move)

**Parameters:**
- lat/lon: Target GPS coordinates
- alt_m: Target altitude AGL (default 15m)
- speed_mps: Flight speed (4.0 normal, 2.0 precision)
- arrived_m: Arrival threshold (3.0 for precision)

**Best practices:**
- Check telemetry after arrival
- Verify position within arrived_m
- Use higher alt_m for obstacle clearance

**Safety:**
- Verify geofence allows target
- Check battery sufficient for distance
- Abort if wind > 15 m/s

## drone_capture

**When to use:** After arriving at waypoint + 2s stabilization

**Prerequisites:**
- Drone airborne and stable
- Arrived at target waypoint
- Gimbal initialized

**Returns:** Base64 JPEG image

**Validation:**
- Check file size > 10KB
- Verify image not corrupted
```

---

## Token Cost Analysis

**Approach 1: Auto-inject TOOLS.md**
- System prompt: +1000 tokens
- Total context: 1200 tokens (60% of mobile budget!)
- ❌ Too expensive for edge

**Approach 2: Rich tool descriptions**
- Per tool: +50-100 tokens
- 10 tools: +500-1000 tokens (one-time when tools sent)
- ✅ Acceptable (only sent once per session)

**Approach 3: Minimal prompt + on-demand**
- System prompt: +50 tokens (core rules)
- read_tool_guide(): +50-100 tokens (only when called)
- ✅ Best for edge

**Recommended:** Approach 2 + 3 hybrid
- Rich descriptions in tool schemas (500-1000 tokens one-time)
- Minimal core rules in system prompt (50 tokens)
- read_tool_guide() for deep dives (50-100 tokens on-demand)

---

## Questions for Rob

1. Should tool schemas include rich descriptions (100+ tokens each)?
2. Should we have read_tool_guide() built-in tool, or skip TOOLS.md entirely?
3. Should safety rules be in system prompt (always visible) or tool descriptions (per-tool)?
4. For FunctionGemma routing, are rich descriptions helpful or noise?
5. Should we generate TOOLS.md from tool schemas (DRY), or keep separate?

---

## Summary

**Tool schemas provide:**
- ✅ WHAT the tool does
- ✅ WHAT parameters it needs

**Agents also need:**
- ✅ WHEN to use each tool (mission context)
- ✅ HOW to sequence tools (workflows)
- ✅ SAFETY constraints (battery, wind, altitude)

**Solution:**
1. **Rich tool descriptions** (in schema, 50-100 tokens each)
2. **Core rules in system prompt** (50 tokens)
3. **Deep guidance on-demand** (read_tool_guide() when needed)

This gives autonomous agents the context they need without blowing the token budget! 🚁
