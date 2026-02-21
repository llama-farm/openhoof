"""Mission lifecycle tools - checkpoints, start/complete, context management."""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any


def checkpoint(agent, summary: str, clear: bool = False) -> Dict[str, Any]:
    """
    Save context checkpoint to MEMORY.md.
    Optionally clear conversation history.
    """
    workspace = Path(agent.workspace)
    memory_file = workspace / "MEMORY.md"
    
    # Create checkpoint
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    checkpoint_id = f"checkpoint-{int(time.time())}"
    
    entry = f"\n## {checkpoint_id}\n**Time:** {timestamp}\n**Summary:** {summary}\n"
    
    # Append to MEMORY.md
    with open(memory_file, "a") as f:
        f.write(entry)
    
    # Clear conversation history if requested
    if clear and hasattr(agent, 'messages') and agent.messages:
        # Keep system prompt only
        system_prompt = agent.messages[0] if agent.messages else None
        agent.messages = [system_prompt] if system_prompt else []
        
        # Also reset turn count if context manager exists
        if hasattr(agent, 'context_manager'):
            agent.context_manager.turn_count = 0
    
    return {
        "success": True,
        "checkpoint_id": checkpoint_id,
        "timestamp": timestamp,
        "cleared_history": clear
    }


def mission_start(agent, mission_id: str, objective: str) -> Dict[str, Any]:
    """
    Begin new mission - clear context and log start.
    """
    workspace = Path(agent.workspace)
    memory_file = workspace / "MEMORY.md"
    
    # Log mission start
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n# Mission: {mission_id}\n**Started:** {timestamp}\n**Objective:** {objective}\n"
    
    with open(memory_file, "a") as f:
        f.write(entry)
    
    # Clear conversation history (fresh start)
    if hasattr(agent, 'messages') and agent.messages:
        system_prompt = agent.messages[0] if agent.messages else None
        agent.messages = [system_prompt] if system_prompt else []
    
    # Reset turn count
    if hasattr(agent, 'context_manager'):
        agent.context_manager.turn_count = 0
    
    # Save mission ID to state
    state_dir = workspace / ".microclaw"
    state_dir.mkdir(exist_ok=True)
    
    mission_state = {
        "mission_id": mission_id,
        "objective": objective,
        "started": int(time.time()),
        "status": "active"
    }
    
    with open(state_dir / "mission.json", "w") as f:
        json.dump(mission_state, f, indent=2)
    
    return {
        "success": True,
        "mission_id": mission_id,
        "timestamp": timestamp,
        "message": "Mission started, conversation history cleared"
    }


def mission_complete(agent, summary: str, outcome: str) -> Dict[str, Any]:
    """
    End mission - archive conversation and clear working memory.
    """
    workspace = Path(agent.workspace)
    memory_file = workspace / "MEMORY.md"
    missions_dir = workspace / "memory" / "missions"
    missions_dir.mkdir(parents=True, exist_ok=True)
    
    # Load mission state
    mission_state_file = workspace / ".microclaw" / "mission.json"
    if mission_state_file.exists():
        with open(mission_state_file, "r") as f:
            mission_state = json.load(f)
        mission_id = mission_state.get("mission_id", "unknown")
    else:
        mission_id = f"mission-{int(time.time())}"
    
    # Log completion
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"**Completed:** {timestamp}\n**Outcome:** {outcome}\n**Summary:** {summary}\n"
    
    with open(memory_file, "a") as f:
        f.write(entry)
    
    # Archive conversation to mission file
    archive_file = missions_dir / f"{mission_id}.json"
    
    archive_data = {
        "mission_id": mission_id,
        "started": mission_state.get("started") if mission_state_file.exists() else int(time.time()),
        "completed": int(time.time()),
        "outcome": outcome,
        "summary": summary,
        "conversation": getattr(agent, 'messages', [])
    }
    
    with open(archive_file, "w") as f:
        json.dump(archive_data, f, indent=2)
    
    # Clear conversation history
    if hasattr(agent, 'messages') and agent.messages:
        system_prompt = agent.messages[0] if agent.messages else None
        agent.messages = [system_prompt] if system_prompt else []
    
    # Clear mission state
    if mission_state_file.exists():
        mission_state_file.unlink()
    
    return {
        "success": True,
        "mission_id": mission_id,
        "outcome": outcome,
        "archived_to": f"memory/missions/{mission_id}.json",
        "message": "Mission complete, conversation archived and cleared"
    }


def get_context_stats(agent) -> Dict[str, Any]:
    """
    Get current context window statistics.
    """
    # Count messages
    message_count = len(getattr(agent, 'messages', []))
    
    # Estimate tokens (rough: 1 token ~= 4 characters)
    total_chars = sum(len(str(msg)) for msg in getattr(agent, 'messages', []))
    estimated_tokens = total_chars // 4
    
    # Get turn count
    turn_count = getattr(agent.context_manager, 'turn_count', 0) if hasattr(agent, 'context_manager') else 0
    
    return {
        "messages": message_count,
        "estimated_tokens": estimated_tokens,
        "turns": turn_count,
        "max_history_turns": getattr(agent, 'max_history_turns', 30),
        "max_turns": getattr(agent, 'max_turns', 10)
    }


def clear_history(agent, keep_last: int = 5) -> Dict[str, Any]:
    """
    Emergency context cleanup - keep only last N turns.
    """
    if not hasattr(agent, 'messages') or not agent.messages:
        return {"message": "No conversation history to clear"}
    
    # Keep system prompt + last N messages
    system_prompt = agent.messages[0]
    recent = agent.messages[-keep_last:] if len(agent.messages) > keep_last else agent.messages[1:]
    
    old_count = len(agent.messages)
    agent.messages = [system_prompt] + recent
    
    # Reset turn count
    if hasattr(agent, 'context_manager'):
        agent.context_manager.turn_count = 0
    
    return {
        "success": True,
        "cleared": old_count - len(agent.messages),
        "kept": len(agent.messages),
        "message": f"Cleared history, kept last {keep_last} messages"
    }
