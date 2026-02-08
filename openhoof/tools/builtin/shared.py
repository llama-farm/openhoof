"""Shared knowledge tools for cross-agent data sharing."""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

from ..base import Tool, ToolResult, ToolContext


def _get_shared_dir(context: ToolContext) -> Path:
    """Get the shared knowledge directory (sibling to agent workspaces)."""
    workspace = Path(context.workspace_dir)
    # Go up from agent workspace to the agents root, then to shared
    shared_dir = workspace.parent.parent / "data" / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    return shared_dir


class SharedWriteTool(Tool):
    """Write to the shared cross-agent knowledge store."""

    name = "shared_write"
    description = """Write content to the shared knowledge store that ALL agents can access.

Use this to:
- Share findings with other agents
- Store analysis results for cross-agent reference
- Save data that shouldn't be locked to your workspace alone

Files are stored in a central shared directory."""

    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Key name for the knowledge entry (e.g., 'fuel-analysis-2026-02-07', 'weather-brief')"
            },
            "content": {
                "type": "string",
                "description": "Content to store"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for categorization"
            }
        },
        "required": ["key", "content"]
    }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        key = params["key"]
        content = params["content"]
        tags = params.get("tags", [])

        shared_dir = _get_shared_dir(context)
        knowledge_dir = shared_dir / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)

        # Write the content file
        file_path = knowledge_dir / f"{key}.md"
        header = f"---\nauthor: {context.agent_id}\ncreated: {datetime.now().isoformat()}\ntags: {json.dumps(tags)}\n---\n\n"
        file_path.write_text(header + content)

        # Also append to the index
        index_path = shared_dir / "index.jsonl"
        entry = {
            "key": key,
            "agent_id": context.agent_id,
            "session_key": context.session_key,
            "timestamp": datetime.now().isoformat(),
            "tags": tags,
            "size": len(content),
        }
        with open(index_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        return ToolResult(
            success=True,
            message=f"Shared knowledge '{key}' saved ({len(content)} chars). All agents can now read it."
        )


class SharedReadTool(Tool):
    """Read from the shared cross-agent knowledge store."""

    name = "shared_read"
    description = """Read content from the shared knowledge store.

Use this to:
- Access findings from other agents
- Read shared analysis results
- Check what other agents have contributed"""

    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Key name of the knowledge entry to read"
            }
        },
        "required": ["key"]
    }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        key = params["key"]
        shared_dir = _get_shared_dir(context)
        file_path = shared_dir / "knowledge" / f"{key}.md"

        if not file_path.exists():
            # List available keys
            knowledge_dir = shared_dir / "knowledge"
            available = []
            if knowledge_dir.exists():
                available = [f.stem for f in knowledge_dir.glob("*.md")]
            return ToolResult(
                success=False,
                error=f"Key '{key}' not found. Available keys: {available[:20]}"
            )

        content = file_path.read_text()
        return ToolResult(
            success=True,
            data={"key": key, "content": content},
            message=f"Read shared knowledge '{key}' ({len(content)} chars)"
        )


class SharedLogTool(Tool):
    """Append a finding to the shared event/findings log."""

    name = "shared_log"
    description = """Log a finding or event to the shared append-only log.

Use this to:
- Record important discoveries
- Log events for other agents to see
- Create an audit trail of agent activities

All agents can search this log."""

    parameters = {
        "type": "object",
        "properties": {
            "finding": {
                "type": "string",
                "description": "The finding or event to log"
            },
            "category": {
                "type": "string",
                "description": "Category (e.g., 'anomaly', 'insight', 'warning', 'status')"
            },
            "severity": {
                "type": "string",
                "enum": ["info", "warning", "critical"],
                "description": "Severity level"
            }
        },
        "required": ["finding"]
    }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        finding = params["finding"]
        category = params.get("category", "general")
        severity = params.get("severity", "info")

        shared_dir = _get_shared_dir(context)
        findings_path = shared_dir / "findings.jsonl"

        entry = {
            "timestamp": datetime.now().isoformat(),
            "agent_id": context.agent_id,
            "session_key": context.session_key,
            "category": category,
            "severity": severity,
            "finding": finding,
        }

        with open(findings_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        return ToolResult(
            success=True,
            message=f"Logged finding [{severity}|{category}]: {finding[:100]}..."
        )


class SharedSearchTool(Tool):
    """Search across shared knowledge and findings."""

    name = "shared_search"
    description = """Search the shared knowledge store and findings log.

Use this to find what other agents have discovered or stored."""

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (searches keys, tags, and content)"
            },
            "category": {
                "type": "string",
                "description": "Filter by category"
            },
            "agent_id": {
                "type": "string",
                "description": "Filter by agent that created the entry"
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default: 10)"
            }
        },
        "required": ["query"]
    }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        query = params["query"].lower()
        category_filter = params.get("category")
        agent_filter = params.get("agent_id")
        limit = params.get("limit", 10)

        shared_dir = _get_shared_dir(context)
        results: List[Dict[str, Any]] = []

        # Search knowledge files
        knowledge_dir = shared_dir / "knowledge"
        if knowledge_dir.exists():
            for f in knowledge_dir.glob("*.md"):
                if query in f.stem.lower() or query in f.read_text().lower():
                    results.append({
                        "type": "knowledge",
                        "key": f.stem,
                        "preview": f.read_text()[:200]
                    })

        # Search findings log
        findings_path = shared_dir / "findings.jsonl"
        if findings_path.exists():
            for line in findings_path.read_text().strip().split("\n"):
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if category_filter and entry.get("category") != category_filter:
                        continue
                    if agent_filter and entry.get("agent_id") != agent_filter:
                        continue
                    if query in entry.get("finding", "").lower() or query in entry.get("category", "").lower():
                        results.append({
                            "type": "finding",
                            "timestamp": entry["timestamp"],
                            "agent_id": entry["agent_id"],
                            "category": entry.get("category"),
                            "severity": entry.get("severity"),
                            "finding": entry["finding"][:200]
                        })
                except json.JSONDecodeError:
                    continue

        results = results[:limit]

        return ToolResult(
            success=True,
            data={"results": results, "total": len(results)},
            message=f"Found {len(results)} results for '{query}'"
        )


class ListToolsTool(Tool):
    """List all available tools and their descriptions."""

    name = "list_tools"
    description = """List all tools currently available to you.

Use this to understand what capabilities you have."""

    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }

    # Will be set by the tool registry after creation
    _registry = None

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        if not self._registry:
            return ToolResult(success=False, error="Tool registry not available")

        tools = self._registry.list_tools()
        tool_list = []
        for t in tools:
            tool_list.append({
                "name": t.name,
                "description": t.description.strip()[:200],
                "requires_approval": t.requires_approval,
                "parameters": list(t.parameters.get("properties", {}).keys())
            })

        return ToolResult(
            success=True,
            data={"tools": tool_list, "count": len(tool_list)},
            message=f"{len(tool_list)} tools available"
        )
