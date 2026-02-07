# API Reference

<p align="center">
  <img src="openhoof-logo.png" alt="OpenHoof Logo" width="120">
</p>

OpenHoof provides a REST API on port 18765 (configurable).

**Base URL:** `http://localhost:18765/api`

## Health

### GET /health
Check system health.

**Response:**
```json
{
  "status": "healthy",
  "components": {
    "api": true,
    "inference": true
  }
}
```

---

## Agents

### GET /agents
List all agents.

**Response:**
```json
[
  {
    "agent_id": "fuel-analyst",
    "name": "Fuel Analyst",
    "description": "Analyzes fuel consumption",
    "status": "stopped",
    "workspace_dir": "/home/user/.openhoof/agents/fuel-analyst"
  }
]
```

### POST /agents
Create a new agent.

**Request:**
```json
{
  "agent_id": "my-agent",
  "name": "My Agent",
  "description": "Does things"
}
```

**Response:**
```json
{
  "agent_id": "my-agent",
  "name": "My Agent",
  "status": "created"
}
```

### GET /agents/{id}
Get agent details.

**Response:**
```json
{
  "agent_id": "fuel-analyst",
  "name": "Fuel Analyst",
  "description": "Analyzes fuel consumption",
  "status": "running",
  "workspace_dir": "/home/user/.openhoof/agents/fuel-analyst",
  "model": null,
  "thinking": null,
  "files": ["SOUL.md", "MEMORY.md", "memory/"]
}
```

### PUT /agents/{id}
Update agent metadata.

**Request:**
```json
{
  "name": "Senior Fuel Analyst",
  "description": "Updated description"
}
```

### DELETE /agents/{id}
Delete an agent and its workspace.

### POST /agents/{id}/start
Start an agent.

### POST /agents/{id}/stop
Stop an agent.

---

## Agent Files

### GET /agents/{id}/files/{path}
Read a file from agent workspace.

**Example:**
```
GET /agents/fuel-analyst/files/SOUL.md
```

**Response:**
```markdown
# SOUL.md - Fuel Analyst

You are a Fuel Analyst AI...
```

### PUT /agents/{id}/files/{path}
Write a file to agent workspace.

**Request:**
```
Content-Type: text/markdown

# Updated SOUL.md content
...
```

### DELETE /agents/{id}/files/{path}
Delete a file from workspace.

---

## Chat

### POST /agents/{id}/chat
Send a message to an agent.

**Request:**
```json
{
  "message": "Analyze this fuel anomaly",
  "session_id": "optional-session-id",
  "context": {
    "additional": "data"
  }
}
```

**Response:**
```json
{
  "session_id": "abc-123",
  "response": "Based on the data, I see a 15% deviation...",
  "tool_calls": [],
  "tokens": {
    "input": 150,
    "output": 200
  }
}
```

### GET /agents/{id}/sessions
List chat sessions for an agent.

**Response:**
```json
[
  {
    "session_id": "abc-123",
    "created_at": "2026-02-06T15:30:00Z",
    "last_message_at": "2026-02-06T15:35:00Z",
    "message_count": 5
  }
]
```

### GET /agents/{id}/sessions/{session_id}
Get session transcript.

**Response:**
```json
{
  "session_id": "abc-123",
  "agent_id": "fuel-analyst",
  "messages": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi! How can I help?"}
  ]
}
```

---

## Triggers

### POST /triggers
Fire a trigger event.

**Request:**
```json
{
  "source": "horizon",
  "event_type": "anomaly",
  "category": "fuel",
  "severity": "warning",
  "title": "Fuel Burn Rate Deviation",
  "description": "Current burn rate is 15% above planned",
  "data": {
    "burn_ratio": 1.15,
    "current_fuel_lbs": 145000
  }
}
```

**Response:**
```json
{
  "trigger_id": "TRG-20260206-0001",
  "status": "spawned",
  "agent_id": "fuel-analyst",
  "session_id": "abc-123"
}
```

### POST /triggers/test
Test trigger routing without spawning.

**Request:** Same as POST /triggers

**Response:**
```json
{
  "event": {...},
  "would_spawn": "fuel-analyst",
  "matching_rules": [...]
}
```

### GET /triggers/rules
List trigger routing rules.

### POST /triggers/rules
Add a routing rule.

**Request:**
```json
{
  "name": "my-rule",
  "source": "my-app",
  "event_type": "alert",
  "category": "*",
  "min_severity": "warning",
  "agent_id": "my-agent"
}
```

### DELETE /triggers/rules/{name}
Delete a routing rule.

### GET /triggers/history
Get recent trigger history.

**Query params:**
- `limit` (int): Max results (default: 50)

---

## Activity

### GET /activity
Get recent activity feed.

**Query params:**
- `limit` (int): Max results (default: 50)
- `agent_id` (string): Filter by agent

**Response:**
```json
[
  {
    "type": "agent:message",
    "timestamp": "2026-02-06T15:30:00Z",
    "data": {
      "agent_id": "fuel-analyst",
      "content": "Analysis complete"
    }
  }
]
```

---

## Approvals

### GET /approvals
List pending approvals.

**Response:**
```json
[
  {
    "approval_id": "APR-001",
    "agent_id": "fuel-analyst",
    "tool": "notify",
    "arguments": {...},
    "requested_at": "2026-02-06T15:30:00Z",
    "status": "pending"
  }
]
```

### POST /approvals/{id}/approve
Approve a pending action.

### POST /approvals/{id}/reject
Reject a pending action.

**Request (optional):**
```json
{
  "reason": "Not appropriate at this time"
}
```

---

## WebSocket

### WS /events
Real-time event stream.

**Connect:**
```javascript
const ws = new WebSocket('ws://localhost:18765/api/events');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Event:', data.type, data.data);
};
```

**Event types:**
- `agent:started` - Agent started
- `agent:stopped` - Agent stopped
- `agent:message` - Agent sent message
- `agent:thinking` - Agent is thinking
- `agent:tool_call` - Tool called
- `agent:tool_result` - Tool returned
- `trigger:spawned` - Trigger spawned agent
- `approval:requested` - Approval needed
- `approval:resolved` - Approval resolved

---

## Error Responses

All errors follow this format:

```json
{
  "detail": "Error message here"
}
```

**Status codes:**
- `400` - Bad request (validation error)
- `404` - Not found
- `500` - Internal server error

---

## OpenAPI Docs

Interactive API documentation available at:
- **Swagger UI:** http://localhost:18765/docs
- **ReDoc:** http://localhost:18765/redoc
