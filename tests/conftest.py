"""Pytest fixtures for Atmosphere Agents tests."""

import pytest
import tempfile
from pathlib import Path
import asyncio

from openhoof.config import Config, Settings
from openhoof.core.workspace import ensure_workspace
from openhoof.core.sessions import SessionStore
from openhoof.core.transcripts import TranscriptStore
from openhoof.core.events import EventBus
from openhoof.tools import ToolRegistry
from openhoof.tools.builtin import register_builtin_tools


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def config():
    """Create test configuration."""
    return Config()


@pytest.fixture
async def workspace_dir(temp_dir):
    """Create a test workspace."""
    workspace = temp_dir / "test-agent"
    await ensure_workspace(workspace)
    
    # Write test SOUL.md
    (workspace / "SOUL.md").write_text("""# Test Agent

You are a test agent.

## Identity
A helpful test agent.
""")
    
    # Write test AGENTS.md
    (workspace / "AGENTS.md").write_text("""# Workspace

## Behavior
- Be helpful
- Run tests
""")
    
    return workspace


@pytest.fixture
def session_store(temp_dir):
    """Create a test session store."""
    return SessionStore(temp_dir / "sessions.json")


@pytest.fixture
def transcript_store(temp_dir):
    """Create a test transcript store."""
    return TranscriptStore(temp_dir / "transcripts")


@pytest.fixture
def event_bus():
    """Create a test event bus."""
    return EventBus()


@pytest.fixture
def tool_registry():
    """Create a tool registry with built-in tools."""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry
