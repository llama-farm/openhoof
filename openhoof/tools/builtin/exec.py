"""Shell execution tool."""

import asyncio
import os
from typing import Dict, Any

from ..base import Tool, ToolResult, ToolContext


class ExecTool(Tool):
    """Execute shell commands."""
    
    name = "exec"
    description = """Execute a shell command.
    
Use this for:
- Running scripts or programs
- File operations
- System commands
- Any shell-based task

Commands run with a timeout and limited permissions."""
    
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute"
            },
            "workdir": {
                "type": "string",
                "description": "Working directory (defaults to workspace)"
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30)",
                "default": 30
            }
        },
        "required": ["command"]
    }
    
    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        command = params["command"]
        workdir = params.get("workdir", context.workspace_dir)
        timeout = params.get("timeout", 30)
        
        # Security: basic command filtering
        dangerous_patterns = [
            "rm -rf /",
            "rm -rf ~",
            "> /dev/",
            "mkfs",
            "dd if=",
            ":(){:|:&};:",  # Fork bomb
        ]
        
        for pattern in dangerous_patterns:
            if pattern in command:
                return ToolResult(
                    success=False,
                    error=f"Command blocked for safety: contains '{pattern}'"
                )
        
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                env={**os.environ, "HOME": os.path.expanduser("~")}
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return ToolResult(
                    success=False,
                    error=f"Command timed out after {timeout}s"
                )
            
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")
            
            # Truncate long output
            max_output = 10000
            if len(stdout_str) > max_output:
                stdout_str = stdout_str[:max_output] + "\n... (truncated)"
            if len(stderr_str) > max_output:
                stderr_str = stderr_str[:max_output] + "\n... (truncated)"
            
            return ToolResult(
                success=process.returncode == 0,
                data={
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "exit_code": process.returncode
                },
                message=stdout_str if process.returncode == 0 else stderr_str,
                error=stderr_str if process.returncode != 0 else None
            )
        
        except Exception as e:
            return ToolResult(success=False, error=str(e))
