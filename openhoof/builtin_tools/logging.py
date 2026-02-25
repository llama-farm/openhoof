"""Logging tools."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any


def log(agent, message: str, level: str = "info") -> Dict[str, Any]:
    """
    Write to daily log file with timestamp and level.
    """
    workspace = Path(agent.workspace)
    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)
    
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = memory_dir / f"{today}.md"
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    level_emoji = {
        "debug": "🔍",
        "info": "ℹ️",
        "warn": "⚠️",
        "error": "❌"
    }.get(level, "📝")
    
    entry = f"{level_emoji} [{timestamp}] {level.upper()}: {message}\n"
    
    with open(log_file, "a") as f:
        f.write(entry)
    
    return {
        "success": True,
        "path": f"memory/{today}.md",
        "timestamp": timestamp,
        "level": level
    }


def read_logs(agent, date: str = "today", limit: int = 100) -> Dict[str, Any]:
    """
    Read recent log entries.
    """
    workspace = Path(agent.workspace)
    memory_dir = workspace / "memory"
    
    if not memory_dir.exists():
        return {"entries": [], "message": "No logs found"}
    
    # Resolve date
    if date == "today":
        target_date = datetime.now()
    elif date == "yesterday":
        target_date = datetime.now() - timedelta(days=1)
    else:
        target_date = datetime.strptime(date, "%Y-%m-%d")
    
    log_file = memory_dir / f"{target_date.strftime('%Y-%m-%d')}.md"
    
    if not log_file.exists():
        return {
            "entries": [],
            "date": target_date.strftime("%Y-%m-%d"),
            "message": "No logs for this date"
        }
    
    content = log_file.read_text()
    lines = content.split("\n")
    
    # Return last N lines
    entries = [line for line in lines if line.strip()][-limit:]
    
    return {
        "date": target_date.strftime("%Y-%m-%d"),
        "entries": entries,
        "count": len(entries)
    }
