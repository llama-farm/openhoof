# Event-Driven Triggers

<p align="center">
  <img src="openhoof-logo.png" alt="OpenHoof Logo" width="120">
</p>

Triggers let external systems wake up agents automatically when events occur. This is the key to integrating OpenHoof with your applications.

## How It Works

```
Your App detects anomaly → POST /triggers → OpenHoof matches rules → Agent spawns with context
```

## Quick Example

When your monitoring system detects a fuel anomaly:

```bash
curl -X POST http://localhost:18765/api/triggers \
  -H "Content-Type: application/json" \
  -d '{
    "source": "horizon",
    "event_type": "anomaly",
    "category": "fuel",
    "severity": "warning",
    "title": "Fuel Burn Rate Deviation",
    "description": "Current burn rate is 15% above planned",
    "data": {
      "burn_ratio": 1.15,
      "current_fuel_lbs": 145000,
      "hours_remaining": 4.2
    }
  }'
```

Response:
```json
{
  "trigger_id": "TRG-20260206-0001",
  "status": "spawned",
  "agent_id": "fuel-analyst",
  "session_id": "abc-123-def"
}
```

## Trigger Event Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | string | ✅ | Your system identifier (e.g., "horizon", "medical-wing") |
| `event_type` | string | ✅ | Type of event (e.g., "anomaly", "alert", "request") |
| `category` | string | | Event category for routing (e.g., "fuel", "equipment") |
| `severity` | string | | Level: "info", "caution", "warning", "critical" |
| `title` | string | ✅ | Brief description |
| `description` | string | | Detailed description |
| `data` | object | | Event-specific data (passed to agent) |
| `context` | object | | Additional context |
| `target_agent` | string | | Force routing to specific agent |

## Routing Rules

OpenHoof uses rules to decide which agent handles each event.

### Default Rules

```json
[
  {
    "name": "horizon-fuel-anomaly",
    "source": "horizon",
    "event_type": "anomaly",
    "category": "fuel",
    "min_severity": "caution",
    "agent_id": "fuel-analyst"
  },
  {
    "name": "horizon-equipment",
    "source": "horizon",
    "event_type": "anomaly",
    "category": "equipment",
    "min_severity": "warning",
    "agent_id": "mx-specialist"
  },
  {
    "name": "critical-catch-all",
    "source": "*",
    "event_type": "*",
    "min_severity": "critical",
    "agent_id": "orchestrator"
  }
]
```

### Rule Matching

Rules are matched by specificity (most specific wins):
1. Exact `source` match (+10 points)
2. Exact `event_type` match (+5 points)
3. Exact `category` match (+3 points)
4. Severity threshold met (+severity level)

Wildcards (`*`) match anything but score lower.

### Managing Rules

**List all rules:**
```bash
curl http://localhost:18765/api/triggers/rules
```

**Add a rule:**
```bash
curl -X POST http://localhost:18765/api/triggers/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-custom-rule",
    "source": "my-app",
    "event_type": "alert",
    "category": "security",
    "min_severity": "warning",
    "agent_id": "security-analyst"
  }'
```

**Delete a rule:**
```bash
curl -X DELETE http://localhost:18765/api/triggers/rules/my-custom-rule
```

### Test Routing (Dry Run)

See which agent would handle an event without actually triggering:

```bash
curl -X POST http://localhost:18765/api/triggers/test \
  -H "Content-Type: application/json" \
  -d '{
    "source": "horizon",
    "event_type": "anomaly",
    "category": "fuel",
    "severity": "warning",
    "title": "Test"
  }'
```

Response:
```json
{
  "event": {...},
  "would_spawn": "fuel-analyst",
  "matching_rules": [
    {"name": "horizon-fuel-anomaly", ...}
  ]
}
```

## Integration Examples

### Python (Async)

```python
from openhoof import OpenHoofClient

client = OpenHoofClient("http://localhost:18765")

async def on_anomaly_detected(anomaly):
    response = await client.trigger(
        source="my-app",
        event_type="anomaly",
        category=anomaly.category,
        severity=anomaly.severity,
        title=anomaly.title,
        description=anomaly.description,
        data=anomaly.to_dict()
    )
    print(f"Agent {response.agent_id} handling it")
```

### Python (Callback)

Drop-in callback for anomaly detection systems:

```python
from openhoof import AnomalyTriggerCallback

# Create callback
callback = AnomalyTriggerCallback(
    source="my-app",
    atmosphere_url="http://localhost:18765",
    min_severity="warning"  # Filter noise
)

# Register with your detector
my_anomaly_engine.register_callback(callback)

# Now anomalies automatically trigger agents!
```

### JavaScript/TypeScript

```typescript
async function triggerAgent(event: AnomalyEvent) {
  const response = await fetch('http://localhost:18765/api/triggers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source: 'my-app',
      event_type: 'anomaly',
      category: event.category,
      severity: event.severity,
      title: event.title,
      data: event.details
    })
  });
  
  const result = await response.json();
  console.log(`Agent ${result.agent_id} spawned`);
}
```

### cURL / Shell

```bash
#!/bin/bash
# trigger-alert.sh

curl -X POST http://localhost:18765/api/triggers \
  -H "Content-Type: application/json" \
  -d "{
    \"source\": \"${SOURCE:-shell}\",
    \"event_type\": \"alert\",
    \"severity\": \"${SEVERITY:-info}\",
    \"title\": \"$1\",
    \"description\": \"$2\"
  }"
```

## Trigger History

View recent triggers:

```bash
curl http://localhost:18765/api/triggers/history?limit=20
```

Response:
```json
[
  {
    "trigger_id": "TRG-20260206-0001",
    "event": {...},
    "agent_id": "fuel-analyst",
    "session_id": "abc-123",
    "status": "spawned",
    "timestamp": "2026-02-06T15:30:00Z"
  }
]
```

## What the Agent Receives

When triggered, the agent receives a structured message:

```markdown
## TRIGGER: Fuel Burn Rate Deviation
**Trigger ID:** TRG-20260206-0001
**Source:** horizon
**Type:** anomaly
**Category:** fuel
**Severity:** WARNING

### Description
Current burn rate is 15% above planned

### Source Data
```json
{
  "burn_ratio": 1.15,
  "current_fuel_lbs": 145000,
  "hours_remaining": 4.2
}
```

---
**Analyze this event and provide recommendations.**
If this requires coordination with other specialists, use spawn_agent.
```

The agent then analyzes and responds based on its SOUL.md instructions.

## Best Practices

1. **Use meaningful categories** — Makes rule matching easier
2. **Include relevant data** — Agents need context to help
3. **Set appropriate severity** — Prevents alert fatigue
4. **Test routing first** — Use `/triggers/test` before production
5. **Monitor trigger history** — Track what's happening

## Severity Guidelines

| Severity | When to Use |
|----------|-------------|
| `info` | FYI, no action needed |
| `caution` | Worth monitoring |
| `warning` | Needs attention soon |
| `critical` | Immediate action required |
