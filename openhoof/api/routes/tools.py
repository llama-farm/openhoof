"""Tools management API routes."""

from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..dependencies import get_manager

router = APIRouter(prefix="/api/tools", tags=["tools"])


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict
    requires_approval: bool = False


class AgentToolsUpdate(BaseModel):
    tools: List[str]


@router.get("")
async def list_tools() -> List[dict]:
    """List all available tools in the registry."""
    manager = get_manager()
    tools = manager.tool_registry.list_tools()

    return [
        {
            "name": t.name,
            "description": t.description.strip(),
            "parameters": t.parameters,
            "requires_approval": t.requires_approval,
            "parameter_names": list(t.parameters.get("properties", {}).keys()),
            "required_params": t.parameters.get("required", []),
        }
        for t in tools
    ]


@router.get("/{tool_name}")
async def get_tool(tool_name: str) -> dict:
    """Get details for a specific tool."""
    manager = get_manager()
    tool = manager.tool_registry.get(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")

    return {
        "name": tool.name,
        "description": tool.description.strip(),
        "parameters": tool.parameters,
        "requires_approval": tool.requires_approval,
        "openai_schema": tool.to_openai_schema(),
    }


@router.get("/agents/{agent_id}")
async def get_agent_tools(agent_id: str) -> dict:
    """Get tools assigned to a specific agent."""
    manager = get_manager()
    handle = await manager.get_agent(agent_id)

    if handle:
        tool_names = handle.config.tools or [t.name for t in manager.tool_registry.list_tools()]
    else:
        # Check config on disk
        config_path = manager.agents_dir / agent_id / "agent.yaml"
        if config_path.exists():
            from ...agents.lifecycle import AgentConfig
            config = AgentConfig.from_yaml(config_path)
            tool_names = config.tools or [t.name for t in manager.tool_registry.list_tools()]
        else:
            tool_names = [t.name for t in manager.tool_registry.list_tools()]

    # Get full tool info for each
    all_tools = {t.name: t for t in manager.tool_registry.list_tools()}
    assigned = []
    available = []

    for name, tool in all_tools.items():
        info = {
            "name": tool.name,
            "description": tool.description.strip().split("\n")[0],
            "assigned": name in tool_names,
        }
        if name in tool_names:
            assigned.append(info)
        else:
            available.append(info)

    return {
        "agent_id": agent_id,
        "assigned_tools": assigned,
        "available_tools": available,
        "total_assigned": len(assigned),
        "total_available": len(available),
    }


@router.put("/agents/{agent_id}")
async def update_agent_tools(agent_id: str, body: AgentToolsUpdate) -> dict:
    """Update tools assigned to an agent."""
    manager = get_manager()

    # Validate tool names
    all_tool_names = {t.name for t in manager.tool_registry.list_tools()}
    invalid = set(body.tools) - all_tool_names
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tools: {list(invalid)}. Available: {sorted(all_tool_names)}"
        )

    await manager.update_agent_tools(agent_id, body.tools)

    return {
        "agent_id": agent_id,
        "tools": body.tools,
        "message": f"Updated {agent_id} with {len(body.tools)} tools"
    }
