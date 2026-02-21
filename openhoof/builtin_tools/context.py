"""Context loading tools - lazy load context files on demand."""

import re
from pathlib import Path
from typing import Dict, Any


def read_soul(agent) -> Dict[str, Any]:
    """Read SOUL.md (rarely needed - already in system prompt)."""
    workspace = Path(agent.workspace)
    soul_file = workspace / "SOUL.md"
    
    if not soul_file.exists():
        return {"content": "No SOUL.md file found"}
    
    content = soul_file.read_text()
    
    return {
        "content": content[:1000],  # Max 1KB
        "truncated": len(content) > 1000
    }


def read_user(agent) -> Dict[str, Any]:
    """Read USER.md (user profile and preferences)."""
    workspace = Path(agent.workspace)
    user_file = workspace / "USER.md"
    
    if not user_file.exists():
        return {"content": "No USER.md file found"}
    
    content = user_file.read_text()
    
    return {
        "content": content[:500],  # Max 500 chars (~50 tokens)
        "truncated": len(content) > 500
    }


def read_agents(agent) -> Dict[str, Any]:
    """Read AGENTS.md (operating instructions)."""
    workspace = Path(agent.workspace)
    agents_file = workspace / "AGENTS.md"
    
    if not agents_file.exists():
        return {"content": "No AGENTS.md file found"}
    
    content = agents_file.read_text()
    
    return {
        "content": content[:2000],  # Max 2KB (~400 tokens)
        "truncated": len(content) > 2000
    }


def read_heartbeat(agent) -> Dict[str, Any]:
    """Read HEARTBEAT.md (heartbeat checklist)."""
    workspace = Path(agent.workspace)
    heartbeat_file = workspace / "HEARTBEAT.md"
    
    if not heartbeat_file.exists():
        return {"content": "No HEARTBEAT.md file found"}
    
    content = heartbeat_file.read_text()
    
    return {
        "content": content[:500],  # Max 500 chars (~50 tokens)
        "truncated": len(content) > 500
    }


def read_tool_guide(agent, tool_name: str = None) -> Dict[str, Any]:
    """
    Read tool usage guidance from TOOLS.md.
    Optionally extract section for specific tool.
    """
    workspace = Path(agent.workspace)
    tools_file = workspace / "TOOLS.md"
    
    if not tools_file.exists():
        return {"content": "No TOOLS.md file found"}
    
    content = tools_file.read_text()
    
    if tool_name:
        # Extract section for specific tool (## tool_name)
        pattern = rf"## {re.escape(tool_name)}.*?(?=##|$)"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        
        if match:
            section = match.group(0).strip()
            return {
                "content": section[:1000],  # Max 1KB
                "tool": tool_name,
                "truncated": len(section) > 1000
            }
        else:
            return {
                "content": f"No guidance found for tool: {tool_name}",
                "tool": tool_name
            }
    
    # Return full guide (truncated)
    return {
        "content": content[:2000],  # Max 2KB
        "truncated": len(content) > 2000
    }
