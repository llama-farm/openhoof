"""Pytest configuration for OpenHoof v2.0 tests."""

import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def temp_dir():
    """Temporary directory for test workspaces."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def agent_workspace(temp_dir):
    """Bootstrap a minimal agent workspace for testing."""
    workspace = temp_dir / "test-agent"
    workspace.mkdir()

    (workspace / "SOUL.md").write_text(
        "You are TestBot 🤖. A test agent.\n\nCore rules:\n- Be helpful\n- Run tests\n"
    )
    (workspace / "MEMORY.md").write_text("# Memory\n\n*No entries yet.*\n")
    (workspace / "IDENTITY.md").write_text("# IDENTITY.md\n- **Name:** TestBot\n- **Emoji:** 🤖\n")

    return workspace
