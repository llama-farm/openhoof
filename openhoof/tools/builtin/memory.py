"""Memory tools for reading and writing workspace files."""

from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from ..base import Tool, ToolResult, ToolContext


class MemoryWriteTool(Tool):
    """Write to agent memory files."""
    
    name = "memory_write"
    description = """Write content to a memory file in your workspace.
    
Use this to:
- Log events to daily memory (memory/YYYY-MM-DD.md)
- Update your TOOLS.md with local notes
- Update MEMORY.md with long-term learnings
- Update any workspace file

The content will be appended for daily files, or replaced for other files."""
    
    parameters = {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "File path relative to workspace (e.g., 'memory/2026-02-06.md', 'TOOLS.md', 'MEMORY.md')"
            },
            "content": {
                "type": "string",
                "description": "Content to write"
            },
            "append": {
                "type": "boolean",
                "description": "If true, append to file instead of replacing",
                "default": False
            }
        },
        "required": ["file", "content"]
    }
    
    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        file_path = params["file"]
        content = params["content"]
        append = params.get("append", False)
        
        # Resolve full path
        workspace = Path(context.workspace_dir)
        full_path = workspace / file_path
        
        # Security: ensure path is within workspace
        try:
            full_path = full_path.resolve()
            workspace_resolved = workspace.resolve()
            if not str(full_path).startswith(str(workspace_resolved)):
                return ToolResult(
                    success=False,
                    error="Cannot write outside workspace directory"
                )
        except Exception:
            return ToolResult(success=False, error="Invalid file path")
        
        # Create parent directories
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Auto-create daily memory header if new file
        is_daily = file_path.startswith("memory/") and file_path.endswith(".md")
        
        try:
            if append:
                # Append mode
                if not full_path.exists() and is_daily:
                    # Create with header
                    date_str = file_path.replace("memory/", "").replace(".md", "")
                    header = f"# Memory Log: {date_str}\n\n"
                    full_path.write_text(header)
                
                # Append with timestamp
                timestamp = datetime.now().strftime("%H:%M")
                with open(full_path, "a") as f:
                    f.write(f"\n**{timestamp}:** {content}\n")
            else:
                # Replace mode
                full_path.write_text(content)
            
            return ToolResult(
                success=True,
                message=f"{'Appended to' if append else 'Wrote'} {file_path}"
            )
        
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class MemoryReadTool(Tool):
    """Read workspace files."""
    
    name = "memory_read"
    description = """Read content from a workspace file.
    
Use this to:
- Read your SOUL.md, AGENTS.md, etc.
- Check daily memory files
- Read skill files
- Access any file in your workspace"""
    
    parameters = {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "File path relative to workspace (e.g., 'SOUL.md', 'memory/2026-02-06.md')"
            }
        },
        "required": ["file"]
    }
    
    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        file_path = params["file"]
        
        # Resolve full path
        workspace = Path(context.workspace_dir)
        full_path = workspace / file_path
        
        # Security: ensure path is within workspace
        try:
            full_path = full_path.resolve()
            workspace_resolved = workspace.resolve()
            if not str(full_path).startswith(str(workspace_resolved)):
                return ToolResult(
                    success=False,
                    error="Cannot read outside workspace directory"
                )
        except Exception:
            return ToolResult(success=False, error="Invalid file path")
        
        if not full_path.exists():
            return ToolResult(
                success=False,
                error=f"File not found: {file_path}"
            )
        
        try:
            content = full_path.read_text()
            return ToolResult(
                success=True,
                data={"content": content},
                message=f"Read {len(content)} characters from {file_path}"
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
