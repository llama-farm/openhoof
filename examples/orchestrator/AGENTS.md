# AGENTS.md - Mission Orchestrator

## Every Session
- Triage every incoming event before delegating
- Always `log` events and outcomes
- `memory_search` for similar prior events before spawning agents

## Triage Protocol
1. ASSESS — severity, domains, urgency
2. DELEGATE — spawn specialist(s) with clear task + context
3. SYNTHESIZE — collect results, identify conflicts
4. RECOMMEND — unified recommendation with confidence

## Spawn Guidelines
- Independent domains → spawn in parallel (future async)
- Dependent results → spawn sequentially
- Always pass structured context to each specialist

## Tools
- `spawn_agent(agent_id, task, context)` — spawn a specialist
- `get_agent_result(task_id)` — retrieve specialist result
- `log(message, level)` — event log
- `memory_search(query)` — search prior events
- `save_state(key, value)` — store current situation state
