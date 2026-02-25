"""Bootstrap new agent workspaces with minimal edge-optimized templates."""

from pathlib import Path


def bootstrap_agent(
    workspace: str,
    name: str = "Agent",
    emoji: str = "🤖",
    mission: str = "Autonomous operation",
    user_name: str = "User",
    timezone: str = "UTC",
    notes: str = "",
    custom_tools: str = ""
) -> dict:
    """
    Create new agent workspace with minimal edge-optimized templates.
    
    Args:
        workspace: Path to workspace directory
        name: Agent name
        emoji: Agent emoji
        mission: One-line mission description
        user_name: User's name
        timezone: User's timezone
        notes: User notes
        custom_tools: Custom tool notes for TOOLS.md
    
    Returns:
        Status dict with created files
    """
    ws_path = Path(workspace).expanduser()
    ws_path.mkdir(parents=True, exist_ok=True)
    
    # Load templates
    template_dir = Path(__file__).parent / "templates"
    
    created = []
    
    # SOUL.md
    soul_template = (template_dir / "SOUL.md").read_text()
    soul_content = soul_template.format(
        name=name,
        emoji=emoji,
        mission=mission
    )
    (ws_path / "SOUL.md").write_text(soul_content)
    created.append("SOUL.md")
    
    # AGENTS.md
    agents_content = (template_dir / "AGENTS.md").read_text()
    (ws_path / "AGENTS.md").write_text(agents_content)
    created.append("AGENTS.md")
    
    # USER.md
    user_template = (template_dir / "USER.md").read_text()
    user_content = user_template.format(
        user_name=user_name,
        timezone=timezone,
        notes=notes or "No notes yet"
    )
    (ws_path / "USER.md").write_text(user_content)
    created.append("USER.md")
    
    # HEARTBEAT.md
    heartbeat_content = (template_dir / "HEARTBEAT.md").read_text()
    (ws_path / "HEARTBEAT.md").write_text(heartbeat_content)
    created.append("HEARTBEAT.md")
    
    # TOOLS.md
    tools_template = (template_dir / "TOOLS.md").read_text()
    tools_content = tools_template.format(
        custom_notes=custom_tools or "No custom tools yet"
    )
    (ws_path / "TOOLS.md").write_text(tools_content)
    created.append("TOOLS.md")
    
    # IDENTITY.md
    identity_template = (template_dir / "IDENTITY.md").read_text()
    identity_content = identity_template.format(
        name=name,
        emoji=emoji
    )
    (ws_path / "IDENTITY.md").write_text(identity_content)
    created.append("IDENTITY.md")
    
    # MEMORY.md (empty initially)
    from datetime import datetime
    created_date = datetime.now().strftime("%Y-%m-%d")
    (ws_path / "MEMORY.md").write_text(f"# MEMORY.md - {name}\n\nCreated {created_date}\n")
    created.append("MEMORY.md")
    
    # Create memory/ directory
    memory_dir = ws_path / "memory"
    memory_dir.mkdir(exist_ok=True)
    
    # Create .microclaw/ directory
    microclaw_dir = ws_path / ".microclaw"
    microclaw_dir.mkdir(exist_ok=True)
    (microclaw_dir / "training").mkdir(exist_ok=True)
    (microclaw_dir / "ddil").mkdir(exist_ok=True)
    
    return {
        "success": True,
        "workspace": str(ws_path),
        "created": created,
        "message": f"Bootstrapped agent workspace: {name} {emoji}"
    }
