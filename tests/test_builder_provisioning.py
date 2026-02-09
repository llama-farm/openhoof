"""Tests for builder agent provisioning."""

import pytest
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from openhoof.agents.lifecycle import AgentManager


@pytest.fixture
def setup_dirs(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return agents_dir, data_dir


@pytest.fixture
def mock_inference():
    return MagicMock()


def test_first_run_copies_defaults(setup_dirs, mock_inference):
    agents_dir, data_dir = setup_dirs

    # Ensure builder workspace doesn't exist
    assert not (agents_dir / "agent-builder").exists()

    manager = AgentManager(
        agents_dir=agents_dir,
        data_dir=data_dir,
        inference=mock_inference,
    )

    # Builder workspace should now exist
    builder_dir = agents_dir / "agent-builder"
    assert builder_dir.exists()
    assert (builder_dir / "agent.yaml").exists()
    assert (builder_dir / "SOUL.md").exists()
    assert (builder_dir / "AGENTS.md").exists()


def test_existing_workspace_preserved(setup_dirs, mock_inference):
    agents_dir, data_dir = setup_dirs

    # Create a custom builder workspace
    builder_dir = agents_dir / "agent-builder"
    builder_dir.mkdir()
    (builder_dir / "SOUL.md").write_text("Custom SOUL content")
    (builder_dir / "agent.yaml").write_text("id: agent-builder\nname: Custom Builder\n")

    manager = AgentManager(
        agents_dir=agents_dir,
        data_dir=data_dir,
        inference=mock_inference,
    )

    # Custom content should be preserved
    assert (builder_dir / "SOUL.md").read_text() == "Custom SOUL content"
    assert "Custom Builder" in (builder_dir / "agent.yaml").read_text()


def test_reprovision_after_deletion(setup_dirs, mock_inference):
    agents_dir, data_dir = setup_dirs

    # First run provisions it
    manager1 = AgentManager(
        agents_dir=agents_dir,
        data_dir=data_dir,
        inference=mock_inference,
    )
    assert (agents_dir / "agent-builder").exists()

    # Delete it
    shutil.rmtree(agents_dir / "agent-builder")
    assert not (agents_dir / "agent-builder").exists()

    # Second run re-provisions it
    manager2 = AgentManager(
        agents_dir=agents_dir,
        data_dir=data_dir,
        inference=mock_inference,
    )
    assert (agents_dir / "agent-builder").exists()
    assert (agents_dir / "agent-builder" / "SOUL.md").exists()
