"""Workspace management for agents."""

import os
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE_FILES = [
    "SOUL.md",
    "AGENTS.md",
    "TOOLS.md",
    "USER.md",
    "MEMORY.md",
    "HEARTBEAT.md",
    "BOOTSTRAP.md",
]


@dataclass
class WorkspaceFile:
    """A file in an agent's workspace."""
    name: str
    path: Path
    content: Optional[str] = None
    exists: bool = True


@dataclass
class AgentWorkspace:
    """An agent's workspace containing identity and memory files."""
    dir: Path
    agent_id: str
    
    # Core identity files
    soul: Optional[str] = None
    agents: Optional[str] = None
    tools: Optional[str] = None
    user: Optional[str] = None
    memory: Optional[str] = None
    heartbeat: Optional[str] = None
    bootstrap: Optional[str] = None
    
    # Daily memory files
    daily_memories: List[WorkspaceFile] = field(default_factory=list)
    
    # Skills
    skills: List[WorkspaceFile] = field(default_factory=list)


def _read_file_safe(path: Path) -> Optional[str]:
    """Read a file, returning None if it doesn't exist."""
    try:
        return path.read_text()
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.warning(f"Error reading {path}: {e}")
        return None


async def load_workspace(workspace_dir: Path) -> AgentWorkspace:
    """Load all workspace files for an agent."""
    agent_id = workspace_dir.name
    
    # Load standard files
    soul = _read_file_safe(workspace_dir / "SOUL.md")
    agents = _read_file_safe(workspace_dir / "AGENTS.md")
    tools = _read_file_safe(workspace_dir / "TOOLS.md")
    user = _read_file_safe(workspace_dir / "USER.md")
    memory = _read_file_safe(workspace_dir / "MEMORY.md")
    heartbeat = _read_file_safe(workspace_dir / "HEARTBEAT.md")
    bootstrap = _read_file_safe(workspace_dir / "BOOTSTRAP.md")
    
    # Load recent daily memories (today + yesterday)
    memory_dir = workspace_dir / "memory"
    daily_memories: List[WorkspaceFile] = []
    
    if memory_dir.exists():
        today = datetime.now()
        for days_ago in [0, 1]:  # Today and yesterday
            date = today - timedelta(days=days_ago)
            filename = f"{date.strftime('%Y-%m-%d')}.md"
            file_path = memory_dir / filename
            content = _read_file_safe(file_path)
            if content:
                daily_memories.append(WorkspaceFile(
                    name=filename,
                    path=file_path,
                    content=content,
                    exists=True
                ))
    
    # Load skills
    skills: List[WorkspaceFile] = []
    skills_dir = workspace_dir / "skills"
    if skills_dir.exists():
        for skill_file in skills_dir.glob("*.md"):
            content = _read_file_safe(skill_file)
            if content:
                skills.append(WorkspaceFile(
                    name=skill_file.name,
                    path=skill_file,
                    content=content,
                    exists=True
                ))
    
    return AgentWorkspace(
        dir=workspace_dir,
        agent_id=agent_id,
        soul=soul,
        agents=agents,
        tools=tools,
        user=user,
        memory=memory,
        heartbeat=heartbeat,
        bootstrap=bootstrap,
        daily_memories=daily_memories,
        skills=skills
    )


async def ensure_workspace(
    workspace_dir: Path,
    templates_dir: Optional[Path] = None
) -> Path:
    """Create workspace directory with default template files if missing."""
    workspace_dir.mkdir(parents=True, exist_ok=True)
    
    # Create memory directory
    (workspace_dir / "memory").mkdir(exist_ok=True)
    
    # Create skills directory
    (workspace_dir / "skills").mkdir(exist_ok=True)
    
    # Write template files if they don't exist
    if templates_dir:
        for filename in DEFAULT_WORKSPACE_FILES:
            dest = workspace_dir / filename
            if not dest.exists():
                template = templates_dir / filename
                if template.exists():
                    dest.write_text(template.read_text())
    
    return workspace_dir


def build_bootstrap_context(
    workspace: AgentWorkspace,
    include_memory: bool = True,
    include_daily: bool = True,
    include_skills: bool = True
) -> str:
    """Build the system prompt context from workspace files."""
    sections: List[str] = []
    
    if workspace.soul:
        sections.append(f"## SOUL.md\n{workspace.soul}")
    
    if workspace.agents:
        sections.append(f"## AGENTS.md\n{workspace.agents}")
    
    if workspace.tools:
        sections.append(f"## TOOLS.md\n{workspace.tools}")
    
    if workspace.user:
        sections.append(f"## USER.md\n{workspace.user}")
    
    # Only include MEMORY.md in main sessions (security)
    if include_memory and workspace.memory:
        sections.append(f"## MEMORY.md\n{workspace.memory}")
    
    # Include daily memories
    if include_daily:
        for daily in workspace.daily_memories:
            if daily.content:
                sections.append(f"## memory/{daily.name}\n{daily.content}")
    
    # Include skills
    if include_skills:
        for skill in workspace.skills:
            if skill.content:
                sections.append(f"## skills/{skill.name}\n{skill.content}")
    
    return "\n\n---\n\n".join(sections)


async def write_workspace_file(
    workspace_dir: Path,
    filename: str,
    content: str
) -> Path:
    """Write content to a workspace file."""
    # Handle nested paths like memory/2026-02-06.md
    file_path = workspace_dir / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    return file_path


async def delete_workspace_file(workspace_dir: Path, filename: str) -> bool:
    """Delete a workspace file (e.g., BOOTSTRAP.md after first run)."""
    file_path = workspace_dir / filename
    if file_path.exists():
        file_path.unlink()
        return True
    return False
