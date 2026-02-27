"""
CLI execution tools for edge agents.

Gives agents the ability to:
- run_command  — execute a shell command, get stdout/stderr/returncode
- read_file    — read a file's contents (with line limit to protect token budget)
- write_file   — write or append content to a file

Design principles:
- shell=False by default (safe, no injection). Opt in to shell=True for pipes/redirects.
- All output truncated automatically — agents work within token budgets.
- Every error returns {"success": False, "error": "..."} — LLM can reason about failures.
- Timeouts on everything — never block the agent loop.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

# Max output chars to return to LLM — protects token budget
_MAX_OUTPUT = 4000
_MAX_TAIL = 500


def shell_exec(
    agent,
    cmd: str,
    timeout: int = 30,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a shell command. Shell mode on by default — supports pipes, redirects, &&.

    This is the simple version of run_command. Use it when you want to run a
    one-liner without worrying about shell mode flags. Great for CLI fallbacks.

    Examples:
        shell_exec("git status && git log --oneline -5")
        shell_exec("cat drone.log | grep ERROR | tail -20")
        shell_exec("python3 scripts/preflight.py")

    Args:
        cmd:     Shell command string (pipes and redirects supported)
        timeout: Max seconds to wait (default 30)
        cwd:     Working directory (defaults to agent workspace)

    Returns:
        {"success": bool, "output": str, "error": str, "returncode": int}
    """
    return run_command(agent, cmd, cwd=cwd, timeout=timeout, shell=True)


def run_command(
    agent,
    cmd: str,
    cwd: Optional[str] = None,
    timeout: int = 30,
    shell: bool = False,
) -> Dict[str, Any]:
    """
    Run a CLI command. Returns stdout, stderr, returncode, and success flag.

    Args:
        cmd:     Command string (e.g. "git status", "docker ps -a")
        cwd:     Working directory (defaults to agent workspace)
        timeout: Max seconds to wait (default 30)
        shell:   Use shell mode for pipes/redirects (e.g. "cat f | grep err").
                 Default False — safer, no shell injection.

    Returns:
        {
            "success": bool,
            "returncode": int,
            "output": str,     # stdout (truncated if long)
            "error": str,      # stderr (truncated)
            "cmd": str,
            "truncated": bool
        }
    """
    work_dir = cwd or getattr(agent, "workspace", None)

    try:
        args: Any = cmd if shell else shlex.split(cmd)

        result = subprocess.run(
            args,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
        )

        stdout = result.stdout
        stderr = result.stderr
        truncated = False

        if len(stdout) > _MAX_OUTPUT:
            head = stdout[:_MAX_OUTPUT - _MAX_TAIL]
            tail = stdout[-_MAX_TAIL:]
            dropped = len(stdout) - len(head) - len(tail)
            stdout = f"{head}\n... [{dropped} chars truncated] ...\n{tail}"
            truncated = True

        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "output": stdout,
            "error": stderr[:1000] if stderr else "",
            "cmd": cmd,
            "truncated": truncated,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "returncode": -1,
            "output": "",
            "error": f"Timed out after {timeout}s",
            "cmd": cmd,
            "truncated": False,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "returncode": -1,
            "output": "",
            "error": f"Command not found: {cmd.split()[0]}",
            "cmd": cmd,
            "truncated": False,
        }
    except Exception as e:
        return {
            "success": False,
            "returncode": -1,
            "output": "",
            "error": str(e),
            "cmd": cmd,
            "truncated": False,
        }


def read_file(
    agent,
    path: str,
    max_lines: int = 200,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Read a file and return its contents.

    Args:
        path:      File path (absolute or relative to agent workspace)
        max_lines: Max lines to return (default 200 — token budget)
        offset:    Start from this line number (0-indexed, for pagination)

    Returns:
        {
            "success": bool,
            "content": str,
            "total_lines": int,
            "returned_lines": int,
            "truncated": bool,
            "path": str
        }
    """
    try:
        p = Path(path)
        if not p.is_absolute():
            workspace = getattr(agent, "workspace", None)
            if workspace:
                p = Path(workspace) / p

        if not p.exists():
            return {"success": False, "error": f"File not found: {path}"}

        if not p.is_file():
            return {"success": False, "error": f"Not a file: {path}"}

        all_lines = p.read_text(errors="replace").splitlines()
        total = len(all_lines)
        window = all_lines[offset: offset + max_lines]
        truncated = (offset + max_lines) < total

        return {
            "success": True,
            "content": "\n".join(window),
            "total_lines": total,
            "returned_lines": len(window),
            "offset": offset,
            "truncated": truncated,
            "path": str(p.resolve()),
        }

    except PermissionError:
        return {"success": False, "error": f"Permission denied: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def write_file(
    agent,
    path: str,
    content: str,
    append: bool = False,
    mkdir: bool = True,
) -> Dict[str, Any]:
    """
    Write or append content to a file.

    Args:
        path:    File path (absolute or relative to agent workspace)
        content: Content to write
        append:  If True, append instead of overwrite (default False)
        mkdir:   Auto-create parent directories (default True)

    Returns:
        {
            "success": bool,
            "path": str,
            "bytes_written": int,
            "mode": "write" | "append"
        }
    """
    try:
        p = Path(path)
        if not p.is_absolute():
            workspace = getattr(agent, "workspace", None)
            if workspace:
                p = Path(workspace) / p

        if mkdir:
            p.parent.mkdir(parents=True, exist_ok=True)

        mode = "a" if append else "w"
        encoded = content.encode()
        with open(p, mode) as f:
            f.write(content)

        return {
            "success": True,
            "path": str(p.resolve()),
            "bytes_written": len(encoded),
            "mode": "append" if append else "write",
        }

    except PermissionError:
        return {"success": False, "error": f"Permission denied: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
