"""
Built-in tools for edge agents.

Provides essential capabilities for autonomous operation:
- Memory (search, append, read)
- Time (get_time, schedule_wakeup)
- Logging (log, read_logs)
- State (save/load/list)
- Context (read_user, read_agents, read_tool_guide)
- Mission lifecycle (checkpoint, mission_start, mission_complete)
"""

from .memory import memory_search, memory_append, memory_read
from .time_tools import get_time
from .logging import log, read_logs
from .state import save_state, load_state, list_state
from .context import read_soul, read_user, read_agents, read_heartbeat, read_tool_guide
from .mission import checkpoint, mission_start, mission_complete, get_context_stats, clear_history
from .cli import run_command, read_file, write_file
from .tool_schema import create_tool_schema

# Export all built-in tools
__all__ = [
    # Memory
    "memory_search",
    "memory_append", 
    "memory_read",
    
    # Time
    "get_time",
    
    # Logging
    "log",
    "read_logs",
    
    # State
    "save_state",
    "load_state",
    "list_state",
    
    # Context
    "read_soul",
    "read_user",
    "read_agents",
    "read_heartbeat",
    "read_tool_guide",
    
    # Mission
    "checkpoint",
    "mission_start",
    "mission_complete",
    "get_context_stats",
    "clear_history",
    
    # CLI / file tools
    "run_command",
    "read_file",
    "write_file",

    # Tool schema helper
    "create_tool_schema",
]


def get_builtin_tool_schemas():
    """Get all built-in tool schemas for agent registration."""
    return [
        # Memory tools
        {
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": "Search MEMORY.md and daily logs for relevant context. Returns top 3 snippets by default. Use this instead of loading full memory files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (e.g. 'last waypoint altitude', 'battery threshold')"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum results to return (default 3)",
                            "default": 3
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "memory_append",
                "description": "Append content to MEMORY.md or daily log. Use this to record decisions, observations, and important events.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Content to append (auto-timestamped)"
                        },
                        "path": {
                            "type": "string",
                            "description": "File to append to (default: today's daily log)",
                            "default": "memory/YYYY-MM-DD.md"
                        }
                    },
                    "required": ["content"]
                }
            }
        },
        
        # Time tools
        {
            "type": "function",
            "function": {
                "name": "get_time",
                "description": "Get current timestamp, date, time, and day of week. Use for timestamping events and checking time-based conditions.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        
        # Logging tools
        {
            "type": "function",
            "function": {
                "name": "log",
                "description": "Write to daily log file with timestamp. Use for recording events, decisions, and observations.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Log message"
                        },
                        "level": {
                            "type": "string",
                            "description": "Log level (info, warn, error, debug)",
                            "default": "info",
                            "enum": ["debug", "info", "warn", "error"]
                        }
                    },
                    "required": ["message"]
                }
            }
        },
        
        # Context loading tools
        {
            "type": "function",
            "function": {
                "name": "read_user",
                "description": "Read USER.md (user profile and preferences). Only call when you need user context.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_agents",
                "description": "Read AGENTS.md (operating instructions and workflows). Only call when you need operational guidance.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_tool_guide",
                "description": "Read tool usage guidance from TOOLS.md. Call when you need detailed guidance on how to use a specific tool.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "description": "Specific tool to get guidance for (optional - returns full guide if omitted)"
                        }
                    }
                }
            }
        },
        
        # Mission lifecycle
        {
            "type": "function",
            "function": {
                "name": "checkpoint",
                "description": "Save current context checkpoint to MEMORY.md. Optionally clear conversation history for fresh start.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Summary of progress/state"
                        },
                        "clear": {
                            "type": "boolean",
                            "description": "Clear conversation history after checkpoint (default false)",
                            "default": False
                        }
                    },
                    "required": ["summary"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "mission_start",
                "description": "Begin a new mission. Clears conversation history and logs mission start to MEMORY.md.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mission_id": {
                            "type": "string",
                            "description": "Mission identifier (e.g. 'patrol-001')"
                        },
                        "objective": {
                            "type": "string",
                            "description": "Mission objective"
                        }
                    },
                    "required": ["mission_id", "objective"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "mission_complete",
                "description": "End current mission. Archives conversation and clears working memory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Mission summary"
                        },
                        "outcome": {
                            "type": "string",
                            "description": "Mission outcome (success, failure, aborted)",
                            "enum": ["success", "failure", "aborted"]
                        }
                    },
                    "required": ["summary", "outcome"]
                }
            }
        },

        # ── CLI / file tools ──────────────────────────────────────────────────
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": (
                    "Run a CLI command and return stdout, stderr, and return code. "
                    "Use for git, docker, kubectl, shell scripts, and any system command. "
                    "Output is automatically truncated to protect token budget. "
                    "Set shell=true for pipes and redirects (e.g. 'cat file | grep error')."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {
                            "type": "string",
                            "description": "Command to run (e.g. 'git status', 'docker ps -a')"
                        },
                        "cwd": {
                            "type": "string",
                            "description": "Working directory (defaults to agent workspace)"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Max seconds to wait before timeout (default 30)",
                            "default": 30
                        },
                        "shell": {
                            "type": "boolean",
                            "description": "Use shell mode for pipes/redirects. Default false (safer).",
                            "default": False
                        }
                    },
                    "required": ["cmd"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": (
                    "Read a file's contents. Returns up to max_lines lines (default 200) "
                    "to stay within token budget. Use offset for pagination through large files."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path (absolute or relative to workspace)"
                        },
                        "max_lines": {
                            "type": "integer",
                            "description": "Max lines to return (default 200)",
                            "default": 200
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Start from this line number for pagination (default 0)",
                            "default": 0
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": (
                    "Write or append content to a file. "
                    "Parent directories are created automatically. "
                    "Use append=true to add to an existing file without overwriting."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path (absolute or relative to workspace)"
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write"
                        },
                        "append": {
                            "type": "boolean",
                            "description": "Append instead of overwrite (default false)",
                            "default": False
                        }
                    },
                    "required": ["path", "content"]
                }
            }
        },
    ]


def builtin_executor(agent, tool_name: str, params: dict) -> dict:
    """
    Execute built-in tools.
    
    Args:
        agent: Agent instance (for accessing workspace, memory, etc.)
        tool_name: Name of tool to execute
        params: Tool parameters
    
    Returns:
        Tool result dict
    """
    # Memory tools
    if tool_name == "memory_search":
        return memory_search(agent, **params)
    elif tool_name == "memory_append":
        return memory_append(agent, **params)
    elif tool_name == "memory_read":
        return memory_read(agent, **params)
    
    # Time tools
    elif tool_name == "get_time":
        return get_time()
    
    # Logging tools
    elif tool_name == "log":
        return log(agent, **params)
    elif tool_name == "read_logs":
        return read_logs(agent, **params)
    
    # State tools
    elif tool_name == "save_state":
        return save_state(agent, **params)
    elif tool_name == "load_state":
        return load_state(agent, **params)
    elif tool_name == "list_state":
        return list_state(agent)
    
    # Context loading tools
    elif tool_name == "read_soul":
        return read_soul(agent)
    elif tool_name == "read_user":
        return read_user(agent)
    elif tool_name == "read_agents":
        return read_agents(agent)
    elif tool_name == "read_heartbeat":
        return read_heartbeat(agent)
    elif tool_name == "read_tool_guide":
        return read_tool_guide(agent, **params)
    
    # Mission lifecycle
    elif tool_name == "checkpoint":
        return checkpoint(agent, **params)
    elif tool_name == "mission_start":
        return mission_start(agent, **params)
    elif tool_name == "mission_complete":
        return mission_complete(agent, **params)
    elif tool_name == "get_context_stats":
        return get_context_stats(agent)
    elif tool_name == "clear_history":
        return clear_history(agent, **params)

    # CLI / file tools
    elif tool_name == "run_command":
        return run_command(agent, **params)
    elif tool_name == "read_file":
        return read_file(agent, **params)
    elif tool_name == "write_file":
        return write_file(agent, **params)

    else:
        return {"error": f"Unknown built-in tool: {tool_name}"}
