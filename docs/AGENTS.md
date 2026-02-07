# Creating and Managing Agents

<p align="center">
  <img src="openhoof-logo.png" alt="OpenHoof Logo" width="120">
</p>

Agents are AI assistants with persistent identity, memory, and specialized capabilities.

## What is an Agent?

An agent is defined by its **workspace** — a folder containing files that shape its behavior:

```
~/.openhoof/agents/fuel-analyst/
├── SOUL.md           # Who the agent IS (required)
├── AGENTS.md         # Workspace rules
├── MEMORY.md         # Long-term memory
├── TOOLS.md          # Tool usage notes
├── USER.md           # User context
├── HEARTBEAT.md      # Periodic tasks
└── memory/           # Daily notes
    └── 2026-02-06.md
```

## Creating an Agent

### Via CLI
```bash
openhoof agents create fuel-analyst \
  --name "Fuel Analyst" \
  --description "Analyzes fuel consumption and anomalies"
```

### Via API
```bash
curl -X POST http://localhost:18765/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "fuel-analyst",
    "name": "Fuel Analyst",
    "description": "Analyzes fuel consumption and anomalies"
  }'
```

### Via Web UI
1. Navigate to http://localhost:13456/agents
2. Click "New Agent"
3. Fill in the form

## The SOUL.md File

This is the most important file — it defines who the agent IS.

```markdown
# SOUL.md - Fuel Analyst

You are a Fuel Analyst AI supporting military airlift operations.

## Your Mission
Monitor and analyze fuel consumption for C-17 aircraft.
Detect anomalies early. Recommend corrective actions.

## Your Personality
- Precise and data-driven
- Safety-first mindset
- Clear, actionable recommendations

## Your Capabilities
- Calculate fuel burn rates and projections
- Identify deviation from planned consumption
- Recommend altitude/speed adjustments
- Calculate divert options when needed

## Your Limitations
- You cannot directly control aircraft systems
- Always recommend human verification for critical decisions
- If uncertain, say so and request more data

## Response Format
When analyzing fuel issues:
1. **Current Status**: What's happening now
2. **Trend Analysis**: Is it getting better/worse?
3. **Projection**: Where will we be if unchanged?
4. **Recommendations**: Specific actions to take
5. **Confidence**: How sure are you?
```

## Workspace Files Reference

### SOUL.md (Required)
Core identity and instructions. Read every session.

### AGENTS.md (Optional)
Workspace rules and conventions. Useful for complex agents.

```markdown
# AGENTS.md

## Session Protocol
1. Read SOUL.md first
2. Check memory/ for recent context
3. Review any pending tasks in HEARTBEAT.md

## Memory Guidelines
- Log significant events to memory/YYYY-MM-DD.md
- Update MEMORY.md with long-term learnings
- Never store secrets in files
```

### MEMORY.md (Optional)
Long-term memory. Agent reads and writes this to remember across sessions.

```markdown
# MEMORY.md - Fuel Analyst

## Learned Patterns
- REACH flights typically burn 3-5% above planned in summer
- Kuwait approach often requires extra fuel margin for holds

## Previous Incidents
- 2026-01-15: REACH 419 diverted to OBBI due to fuel miscalculation
  - Root cause: Incorrect winds aloft data
  - Lesson: Always verify winds at waypoints
```

### USER.md (Optional)
User-specific context. Only read in "main" sessions (not sub-agent calls).

```markdown
# USER.md

## Current Mission
- Callsign: REACH 421
- Route: KDOV → OKBK
- Aircraft: C-17A, Tail 05-5142

## Crew Preferences
- Pilot prefers conservative fuel margins
- Loadmaster experienced with hazmat
```

### HEARTBEAT.md (Optional)
Tasks to run on heartbeat (periodic check-ins).

```markdown
# HEARTBEAT.md

## Periodic Checks
- [ ] Review any pending fuel alerts
- [ ] Check weather at destination
- [ ] Update fuel consumption log

## If idle for >2 hours
- Generate status summary
```

### memory/YYYY-MM-DD.md
Daily notes. Automatically created by date.

```markdown
# 2026-02-06

## 14:30 - Fuel Alert
REACH 421 showing +8% burn deviation
- Recommended: Descend to FL340
- Pilot acknowledged

## 15:45 - Follow-up
Burn rate normalized after descent
```

## Managing Agents

### List Agents
```bash
# CLI
openhoof agents list

# API
curl http://localhost:18765/api/agents
```

### Get Agent Details
```bash
# CLI
openhoof agents show fuel-analyst

# API
curl http://localhost:18765/api/agents/fuel-analyst
```

### Update Agent
```bash
# API
curl -X PUT http://localhost:18765/api/agents/fuel-analyst \
  -H "Content-Type: application/json" \
  -d '{"name": "Senior Fuel Analyst"}'
```

### Delete Agent
```bash
# CLI
openhoof agents delete fuel-analyst

# API
curl -X DELETE http://localhost:18765/api/agents/fuel-analyst
```

### Read Agent Files
```bash
curl http://localhost:18765/api/agents/fuel-analyst/files/SOUL.md
```

### Update Agent Files
```bash
curl -X PUT http://localhost:18765/api/agents/fuel-analyst/files/SOUL.md \
  -H "Content-Type: text/markdown" \
  -d '# Updated SOUL.md content...'
```

## Multi-Agent Coordination

Agents can spawn other agents for specialized tasks:

```markdown
# In orchestrator's SOUL.md

When handling complex situations:
1. Spawn fuel-analyst for fuel issues
2. Spawn intel-analyst for threat assessment
3. Spawn mx-specialist for equipment problems

Use the spawn_agent tool:
- spawn_agent(agent_id="fuel-analyst", task="Analyze this anomaly", context={...})
```

### Orchestrator Pattern

Create an orchestrator that delegates:

```markdown
# SOUL.md - Mission Orchestrator

You coordinate responses to mission events by delegating to specialists.

## Your Team
- **fuel-analyst**: Fuel consumption and efficiency
- **intel-analyst**: Threat assessment and intel
- **mx-specialist**: Equipment and maintenance

## Coordination Protocol
1. Assess incoming event
2. Identify which specialists needed
3. Spawn them with specific tasks
4. Synthesize their responses
5. Present unified recommendation
```

## Agent Templates

Create reusable templates:

```bash
# templates/analyst.yaml
metadata:
  name: "{{domain}}-analyst"
  description: "Analyzes {{domain}} data"

files:
  SOUL.md: |
    # SOUL.md - {{domain}} Analyst
    
    You are a {{domain}} analyst AI.
    Your job is to analyze {{domain}} data and provide insights.
    
    ## Capabilities
    - Detect anomalies in {{domain}} metrics
    - Forecast trends
    - Recommend actions

  AGENTS.md: |
    # Standard analyst workspace rules
    ...
```

Use template:
```bash
openhoof agents create --template analyst --var domain=fuel
```

## Best Practices

1. **Keep SOUL.md focused** — One clear purpose per agent
2. **Use memory/ for daily logs** — Keep MEMORY.md for distilled insights
3. **Define clear response formats** — Makes outputs predictable
4. **State limitations explicitly** — Prevents hallucination
5. **Test with simple cases first** — Build complexity gradually
