"""Agent management endpoints."""

from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from ..dependencies import get_manager
from ...config import get_agents_dir
from ...core.workspace import ensure_workspace, load_workspace

router = APIRouter()


class AgentCreate(BaseModel):
    """Request to create a new agent."""
    agent_id: str
    name: str
    description: Optional[str] = ""
    template: Optional[str] = None  # Template agent to copy from
    soul: Optional[str] = None  # Custom SOUL.md content
    model: Optional[str] = None
    thinking: Optional[str] = None
    heartbeat_enabled: bool = True
    heartbeat_interval: int = 1800


class AgentUpdate(BaseModel):
    """Request to update an agent."""
    name: Optional[str] = None
    description: Optional[str] = None
    model: Optional[str] = None
    thinking: Optional[str] = None
    heartbeat_enabled: Optional[bool] = None
    heartbeat_interval: Optional[int] = None


class AgentResponse(BaseModel):
    """Agent response model."""
    agent_id: str
    name: str
    description: str = ""
    status: str
    workspace_dir: str
    model: Optional[str] = None
    thinking: Optional[str] = None


@router.get("")
async def list_agents() -> List[AgentResponse]:
    """List all agents."""
    manager = get_manager()
    agents = await manager.list_agents()
    return [AgentResponse(**a) for a in agents]


@router.post("")
async def create_agent(request: AgentCreate) -> AgentResponse:
    """Create a new agent."""
    agents_dir = get_agents_dir()
    workspace_dir = agents_dir / request.agent_id
    
    if workspace_dir.exists():
        raise HTTPException(status_code=409, detail=f"Agent already exists: {request.agent_id}")
    
    # Create workspace
    await ensure_workspace(workspace_dir)
    
    # Write agent.yaml
    import yaml
    config_data = {
        "id": request.agent_id,
        "name": request.name,
        "description": request.description,
        "model": request.model,
        "thinking": request.thinking,
        "heartbeat": {
            "enabled": request.heartbeat_enabled,
            "interval": request.heartbeat_interval,
        },
    }
    (workspace_dir / "agent.yaml").write_text(yaml.dump(config_data, default_flow_style=False))
    
    # Write custom SOUL.md if provided
    if request.soul:
        (workspace_dir / "SOUL.md").write_text(request.soul)
    else:
        # Write default SOUL.md
        default_soul = f"""# {request.name}

{request.description or 'An AI agent.'}

## Identity

You are **{request.name}**, an AI agent in the Atmosphere platform.

## Behavior

- Be helpful and precise
- Use tools when needed
- Write to memory to remember important things
- Ask for clarification when uncertain

## Boundaries

- Stay within your workspace
- Request approval for sensitive actions
- Respect privacy and security
"""
        (workspace_dir / "SOUL.md").write_text(default_soul)
    
    # Write default AGENTS.md
    default_agents = """# Workspace

## Every Session

1. Read SOUL.md - who you are
2. Read memory/ files for recent context
3. Check HEARTBEAT.md for tasks

## Memory

- Daily logs: memory/YYYY-MM-DD.md
- Long-term: MEMORY.md
"""
    (workspace_dir / "AGENTS.md").write_text(default_agents)
    
    return AgentResponse(
        agent_id=request.agent_id,
        name=request.name,
        description=request.description or "",
        status="stopped",
        workspace_dir=str(workspace_dir),
        model=request.model,
        thinking=request.thinking,
    )


@router.get("/{agent_id}")
async def get_agent(agent_id: str) -> AgentResponse:
    """Get agent details."""
    manager = get_manager()
    agents = await manager.list_agents()
    
    for agent in agents:
        if agent["agent_id"] == agent_id:
            return AgentResponse(**agent)
    
    raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    """Delete an agent."""
    manager = get_manager()
    
    # Stop if running
    await manager.stop_agent(agent_id)
    
    # Delete workspace
    agents_dir = get_agents_dir()
    workspace_dir = agents_dir / agent_id
    
    if not workspace_dir.exists():
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    
    import shutil
    shutil.rmtree(workspace_dir)
    
    return {"status": "deleted", "agent_id": agent_id}


@router.post("/{agent_id}/start")
async def start_agent(agent_id: str) -> AgentResponse:
    """Start an agent."""
    manager = get_manager()
    
    try:
        handle = await manager.start_agent(agent_id)
        return AgentResponse(
            agent_id=handle.agent_id,
            name=handle.config.name,
            description=handle.config.description,
            status="running",
            workspace_dir=str(handle.workspace.dir),
            model=handle.config.model,
            thinking=handle.config.thinking,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{agent_id}/stop")
async def stop_agent(agent_id: str):
    """Stop an agent."""
    manager = get_manager()
    
    if await manager.stop_agent(agent_id):
        return {"status": "stopped", "agent_id": agent_id}
    
    raise HTTPException(status_code=404, detail=f"Agent not running: {agent_id}")


# Workspace file endpoints

@router.get("/{agent_id}/workspace")
async def list_workspace_files(agent_id: str) -> List[str]:
    """List files in agent workspace."""
    agents_dir = get_agents_dir()
    workspace_dir = agents_dir / agent_id
    
    if not workspace_dir.exists():
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    
    files = []
    for f in workspace_dir.rglob("*"):
        if f.is_file():
            rel_path = f.relative_to(workspace_dir)
            files.append(str(rel_path))
    
    return sorted(files)


@router.get("/{agent_id}/workspace/{file_path:path}")
async def get_workspace_file(agent_id: str, file_path: str):
    """Get content of a workspace file."""
    agents_dir = get_agents_dir()
    workspace_dir = agents_dir / agent_id
    full_path = workspace_dir / file_path
    
    # Security check
    try:
        full_path = full_path.resolve()
        if not str(full_path).startswith(str(workspace_dir.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")
    
    if not full_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    
    return {"path": file_path, "content": full_path.read_text()}


class FileContent(BaseModel):
    content: str


@router.put("/{agent_id}/workspace/{file_path:path}")
async def update_workspace_file(agent_id: str, file_path: str, body: FileContent):
    """Update a workspace file."""
    agents_dir = get_agents_dir()
    workspace_dir = agents_dir / agent_id
    full_path = workspace_dir / file_path
    
    # Security check
    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path = full_path.resolve()
        if not str(full_path).startswith(str(workspace_dir.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")
    
    full_path.write_text(body.content)
    
    return {"path": file_path, "status": "updated"}
