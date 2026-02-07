# Extending Agent Capabilities with Tools

<p align="center">
  <img src="openhoof-logo.png" alt="OpenHoof Logo" width="120">
</p>

Tools give agents the ability to take actions beyond just generating text.

## Built-in Tools

OpenHoof includes these tools out of the box:

| Tool | Description |
|------|-------------|
| `memory_read` | Read from agent's memory files |
| `memory_write` | Write to agent's memory files |
| `spawn_agent` | Spawn another agent for a task |
| `notify` | Queue a notification (with approval) |
| `exec` | Execute shell commands (with approval) |

## How Tools Work

When an agent needs to use a tool, it outputs a special format:

```
I need to check the fuel calculations. Let me look at the memory.

<tool_call>
{"name": "memory_read", "arguments": {"path": "memory/2026-02-06.md"}}
</tool_call>
```

OpenHoof intercepts this, executes the tool, and returns the result:

```
<tool_result>
{"success": true, "data": "## 14:30 - Fuel Alert\nREACH 421..."}
</tool_result>
```

The agent then continues with that context.

## Creating Custom Tools

### 1. Basic Tool

```python
# openhoof/tools/custom/weather.py
from openhoof.tools import Tool, ToolResult

class WeatherTool(Tool):
    """Get current weather for a location."""
    
    name = "get_weather"
    description = "Get current weather conditions for a location"
    
    # Define parameters (JSON Schema)
    parameters = {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City name or airport code"
            }
        },
        "required": ["location"]
    }
    
    async def execute(self, location: str) -> ToolResult:
        # Your implementation
        weather_data = await self.fetch_weather(location)
        
        return ToolResult(
            success=True,
            data={
                "location": location,
                "temperature": weather_data["temp"],
                "conditions": weather_data["conditions"]
            }
        )
    
    async def fetch_weather(self, location: str):
        # Call weather API, database, etc.
        pass
```

### 2. Register the Tool

```python
# openhoof/tools/custom/__init__.py
from .weather import WeatherTool

def register_custom_tools(registry):
    registry.register(WeatherTool())
```

Then in your config or startup:

```python
from openhoof.tools import ToolRegistry
from openhoof.tools.custom import register_custom_tools

registry = ToolRegistry()
register_custom_tools(registry)
```

### 3. Tool with Approval Required

For sensitive operations:

```python
class DatabaseTool(Tool):
    name = "update_database"
    description = "Update a record in the database"
    requires_approval = True  # ← Key flag
    
    async def execute(self, table: str, id: str, data: dict) -> ToolResult:
        # This won't run until human approves
        await self.db.update(table, id, data)
        return ToolResult(success=True, data={"updated": id})
```

When `requires_approval=True`:
1. Tool execution is queued
2. Human sees approval request in UI
3. Human approves/rejects
4. If approved, tool executes
5. Result returned to agent

## Tool Best Practices

### Keep Tools Focused
```python
# ✅ Good: Single purpose
class SendEmailTool(Tool):
    name = "send_email"
    ...

# ❌ Bad: Too many things
class CommunicationsTool(Tool):
    name = "communications"  # email? slack? sms?
    ...
```

### Provide Clear Descriptions
```python
# ✅ Good: Helpful description
description = "Send an email. Returns confirmation ID on success."

# ❌ Bad: Vague
description = "Email tool"
```

### Handle Errors Gracefully
```python
async def execute(self, **kwargs) -> ToolResult:
    try:
        result = await self.do_thing()
        return ToolResult(success=True, data=result)
    except NotFoundException:
        return ToolResult(
            success=False, 
            error="Resource not found"
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=f"Unexpected error: {str(e)}"
        )
```

### Use Approval for Side Effects
```python
# Tools that modify state should require approval
requires_approval = True  # For: write, delete, send, execute

# Read-only tools can auto-execute
requires_approval = False  # For: read, search, calculate
```

## Plugin Architecture

For larger extensions, create a plugin:

```
my_plugin/
├── __init__.py
├── tools/
│   ├── __init__.py
│   ├── weather.py
│   └── maps.py
├── triggers/
│   └── weather_alerts.py
└── plugin.yaml
```

```yaml
# plugin.yaml
name: weather-plugin
version: 1.0.0
description: Weather-related tools and triggers

tools:
  - weather.WeatherTool
  - maps.LocationTool

triggers:
  - weather_alerts.SevereWeatherRule
```

Register plugin:
```bash
openhoof plugins install ./my_plugin
```

## API for Tool Management

### List Available Tools
```bash
curl http://localhost:18765/api/tools
```

### Get Tool Schema
```bash
curl http://localhost:18765/api/tools/get_weather
```

### Execute Tool Directly (Testing)
```bash
curl -X POST http://localhost:18765/api/tools/get_weather/execute \
  -H "Content-Type: application/json" \
  -d '{"location": "Denver"}'
```

## Example: Complete Custom Tool

Here's a full example of a search tool:

```python
# openhoof/tools/custom/search.py
"""Search tool for querying a knowledge base."""

import httpx
from openhoof.tools import Tool, ToolResult

class SearchTool(Tool):
    """Search the knowledge base for relevant documents."""
    
    name = "search"
    description = """Search the knowledge base for documents matching a query.
    Returns top 5 most relevant results with snippets."""
    
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query"
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default: 5)",
                "default": 5
            },
            "category": {
                "type": "string",
                "description": "Filter by category (optional)",
                "enum": ["technical", "policy", "procedures"]
            }
        },
        "required": ["query"]
    }
    
    requires_approval = False  # Read-only, safe to auto-execute
    
    def __init__(self, search_api_url: str = "http://localhost:8080"):
        self.search_api_url = search_api_url
    
    async def execute(
        self, 
        query: str, 
        limit: int = 5,
        category: str = None
    ) -> ToolResult:
        try:
            async with httpx.AsyncClient() as client:
                params = {"q": query, "limit": limit}
                if category:
                    params["category"] = category
                
                response = await client.get(
                    f"{self.search_api_url}/search",
                    params=params,
                    timeout=10.0
                )
                response.raise_for_status()
                
                results = response.json()
                
                return ToolResult(
                    success=True,
                    data={
                        "query": query,
                        "total_results": len(results),
                        "results": [
                            {
                                "title": r["title"],
                                "snippet": r["snippet"][:200],
                                "relevance": r["score"]
                            }
                            for r in results
                        ]
                    }
                )
                
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                error="Search timed out. Try a more specific query."
            )
        except httpx.HTTPError as e:
            return ToolResult(
                success=False,
                error=f"Search service error: {str(e)}"
            )
```

## Tools Available to Agents

In an agent's SOUL.md, you can reference available tools:

```markdown
# SOUL.md

## Your Tools

You have access to these tools:

- **search**: Search the knowledge base
- **memory_read/write**: Access your memory files
- **spawn_agent**: Delegate to other agents
- **notify**: Alert humans (requires approval)

When you need information, use search first before asking.
```
