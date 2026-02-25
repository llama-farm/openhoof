"""Memory tools - search, append, read."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Any


def memory_search(agent, query: str, max_results: int = 3) -> Dict[str, Any]:
    """
    Search MEMORY.md and daily logs using SQLite FTS.
    
    Returns top matching snippets instead of full files.
    """
    memory_dir = Path(agent.workspace) / "memory"
    memory_file = Path(agent.workspace) / "MEMORY.md"
    
    # For MVP, use simple text search (TODO: implement SQLite FTS)
    results = []
    
    # Search MEMORY.md
    if memory_file.exists():
        content = memory_file.read_text()
        lines = content.split("\n")
        
        for i, line in enumerate(lines):
            if query.lower() in line.lower():
                # Get context (3 lines before/after)
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                snippet = "\n".join(lines[start:end])
                
                results.append({
                    "path": "MEMORY.md",
                    "line": i + 1,
                    "snippet": snippet,
                    "score": 1.0
                })
                
                if len(results) >= max_results:
                    break
    
    # Search daily logs if we need more results
    if len(results) < max_results and memory_dir.exists():
        # Search last 7 days
        from datetime import timedelta
        
        for i in range(7):
            date = datetime.now() - timedelta(days=i)
            log_file = memory_dir / f"{date.strftime('%Y-%m-%d')}.md"
            
            if log_file.exists():
                content = log_file.read_text()
                if query.lower() in content.lower():
                    lines = content.split("\n")
                    for j, line in enumerate(lines):
                        if query.lower() in line.lower():
                            start = max(0, j - 1)
                            end = min(len(lines), j + 2)
                            snippet = "\n".join(lines[start:end])
                            
                            results.append({
                                "path": f"memory/{log_file.name}",
                                "line": j + 1,
                                "snippet": snippet,
                                "score": 0.8
                            })
                            
                            if len(results) >= max_results:
                                break
            
            if len(results) >= max_results:
                break
    
    if not results:
        return {
            "results": [],
            "message": f"No results found for query: {query}"
        }
    
    return {
        "results": results[:max_results],
        "query": query,
        "count": len(results[:max_results])
    }


def memory_append(agent, content: str, path: str = None) -> Dict[str, Any]:
    """
    Append content to MEMORY.md or daily log.
    Auto-timestamps entries.
    """
    workspace = Path(agent.workspace)
    
    # Default to today's daily log
    if path is None or path == "memory/YYYY-MM-DD.md":
        memory_dir = workspace / "memory"
        memory_dir.mkdir(exist_ok=True)
        
        today = datetime.now().strftime("%Y-%m-%d")
        path = f"memory/{today}.md"
    
    target = workspace / path
    target.parent.mkdir(parents=True, exist_ok=True)
    
    # Timestamp the entry
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n## {timestamp}\n{content}\n"
    
    # Append
    with open(target, "a") as f:
        f.write(entry)
    
    return {
        "success": True,
        "path": path,
        "timestamp": timestamp,
        "bytes_written": len(entry)
    }


def memory_read(agent, path: str, from_line: int = None, lines: int = None) -> Dict[str, Any]:
    """
    Read specific section from memory file.
    """
    workspace = Path(agent.workspace)
    target = workspace / path
    
    if not target.exists():
        return {"error": f"File not found: {path}"}
    
    content = target.read_text()
    all_lines = content.split("\n")
    
    # Read specific range
    if from_line is not None:
        start = from_line - 1  # 1-indexed
        end = start + lines if lines else len(all_lines)
        selected = all_lines[start:end]
        
        return {
            "path": path,
            "from_line": from_line,
            "lines_read": len(selected),
            "content": "\n".join(selected)
        }
    
    # Read full file (truncated if too long)
    max_chars = 2000
    if len(content) > max_chars:
        return {
            "path": path,
            "content": content[:max_chars],
            "truncated": True,
            "total_chars": len(content)
        }
    
    return {
        "path": path,
        "content": content,
        "truncated": False
    }
