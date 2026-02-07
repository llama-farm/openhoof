"""Tests for tool framework."""

import pytest
from pathlib import Path

from openhoof.tools import Tool, ToolResult, ToolContext, ToolRegistry
from openhoof.tools.builtin import (
    MemoryWriteTool,
    MemoryReadTool,
    NotifyTool,
    ExecTool,
)


def make_context(workspace_dir: Path) -> ToolContext:
    """Create a test tool context."""
    return ToolContext(
        agent_id="test-agent",
        session_key="test:session",
        workspace_dir=str(workspace_dir)
    )


def test_tool_registry(tool_registry):
    """Test tool registry operations."""
    # Should have built-in tools
    assert tool_registry.get("memory_write") is not None
    assert tool_registry.get("memory_read") is not None
    assert tool_registry.get("notify") is not None
    assert tool_registry.get("exec") is not None


def test_get_openai_schemas(tool_registry):
    """Test getting OpenAI tool schemas."""
    schemas = tool_registry.get_openai_schemas()
    
    assert len(schemas) > 0
    assert all(s["type"] == "function" for s in schemas)
    assert all("function" in s for s in schemas)


@pytest.mark.asyncio
async def test_memory_write_tool(workspace_dir):
    """Test memory write tool."""
    tool = MemoryWriteTool()
    context = make_context(workspace_dir)
    
    result = await tool.execute({
        "file": "TOOLS.md",
        "content": "# Tools\nTest content"
    }, context)
    
    assert result.success
    assert (workspace_dir / "TOOLS.md").exists()


@pytest.mark.asyncio
async def test_memory_write_append(workspace_dir):
    """Test memory write with append mode."""
    tool = MemoryWriteTool()
    context = make_context(workspace_dir)
    
    result = await tool.execute({
        "file": "memory/2026-02-06.md",
        "content": "Test log entry",
        "append": True
    }, context)
    
    assert result.success
    content = (workspace_dir / "memory" / "2026-02-06.md").read_text()
    assert "Test log entry" in content


@pytest.mark.asyncio
async def test_memory_write_security(workspace_dir):
    """Test memory write security (can't escape workspace)."""
    tool = MemoryWriteTool()
    context = make_context(workspace_dir)
    
    result = await tool.execute({
        "file": "../../../etc/passwd",
        "content": "hacked"
    }, context)
    
    assert not result.success
    assert "outside workspace" in result.error.lower()


@pytest.mark.asyncio
async def test_memory_read_tool(workspace_dir):
    """Test memory read tool."""
    tool = MemoryReadTool()
    context = make_context(workspace_dir)
    
    result = await tool.execute({
        "file": "SOUL.md"
    }, context)
    
    assert result.success
    assert result.data is not None
    assert "Test Agent" in result.data["content"]


@pytest.mark.asyncio
async def test_memory_read_not_found(workspace_dir):
    """Test memory read for non-existent file."""
    tool = MemoryReadTool()
    context = make_context(workspace_dir)
    
    result = await tool.execute({
        "file": "NONEXISTENT.md"
    }, context)
    
    assert not result.success
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_notify_tool(workspace_dir):
    """Test notify tool (requires approval)."""
    tool = NotifyTool()
    context = make_context(workspace_dir)
    
    result = await tool.execute({
        "title": "Test Alert",
        "message": "This is a test notification",
        "priority": "high"
    }, context)
    
    assert result.success
    assert result.requires_approval
    assert result.approval_id is not None


@pytest.mark.asyncio
async def test_exec_tool(workspace_dir):
    """Test exec tool."""
    tool = ExecTool()
    context = make_context(workspace_dir)
    
    result = await tool.execute({
        "command": "echo 'hello world'"
    }, context)
    
    assert result.success
    assert "hello world" in result.data["stdout"]


@pytest.mark.asyncio
async def test_exec_tool_dangerous_command(workspace_dir):
    """Test exec tool blocks dangerous commands."""
    tool = ExecTool()
    context = make_context(workspace_dir)
    
    result = await tool.execute({
        "command": "rm -rf /"
    }, context)
    
    assert not result.success
    assert "blocked" in result.error.lower()


@pytest.mark.asyncio
async def test_exec_tool_timeout(workspace_dir):
    """Test exec tool timeout."""
    tool = ExecTool()
    context = make_context(workspace_dir)
    
    result = await tool.execute({
        "command": "sleep 10",
        "timeout": 1
    }, context)
    
    assert not result.success
    assert "timed out" in result.error.lower()
