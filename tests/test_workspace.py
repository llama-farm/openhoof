"""Tests for workspace management."""

import pytest
from pathlib import Path

from openhoof.core.workspace import (
    load_workspace,
    ensure_workspace,
    build_bootstrap_context,
    write_workspace_file,
    delete_workspace_file,
)


@pytest.mark.asyncio
async def test_ensure_workspace(temp_dir):
    """Test workspace creation."""
    workspace = temp_dir / "new-agent"
    
    result = await ensure_workspace(workspace)
    
    assert result == workspace
    assert workspace.exists()
    assert (workspace / "memory").exists()
    assert (workspace / "skills").exists()


@pytest.mark.asyncio
async def test_load_workspace(workspace_dir):
    """Test loading a workspace."""
    workspace = await load_workspace(workspace_dir)
    
    assert workspace.agent_id == workspace_dir.name
    assert workspace.soul is not None
    assert "Test Agent" in workspace.soul
    assert workspace.agents is not None


@pytest.mark.asyncio
async def test_build_bootstrap_context(workspace_dir):
    """Test building bootstrap context."""
    workspace = await load_workspace(workspace_dir)
    context = build_bootstrap_context(workspace)
    
    assert "SOUL.md" in context
    assert "Test Agent" in context
    assert "AGENTS.md" in context


@pytest.mark.asyncio
async def test_write_workspace_file(workspace_dir):
    """Test writing workspace files."""
    await write_workspace_file(workspace_dir, "memory/2026-02-06.md", "# Test Memory")
    
    file_path = workspace_dir / "memory" / "2026-02-06.md"
    assert file_path.exists()
    assert file_path.read_text() == "# Test Memory"


@pytest.mark.asyncio
async def test_delete_workspace_file(workspace_dir):
    """Test deleting workspace files."""
    # Create a file
    test_file = workspace_dir / "BOOTSTRAP.md"
    test_file.write_text("# Bootstrap")
    
    # Delete it
    result = await delete_workspace_file(workspace_dir, "BOOTSTRAP.md")
    
    assert result is True
    assert not test_file.exists()


@pytest.mark.asyncio
async def test_delete_nonexistent_file(workspace_dir):
    """Test deleting a file that doesn't exist."""
    result = await delete_workspace_file(workspace_dir, "NONEXISTENT.md")
    assert result is False
