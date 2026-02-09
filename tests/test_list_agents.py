"""Tests for list_agents tool."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock

from openhoof.tools.builtin.list_agents import ListAgentsTool
from openhoof.tools.base import ToolContext


@pytest.fixture
def agents_dir(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    return d


@pytest.fixture
def context(agents_dir):
    workspace = agents_dir / "agent-builder"
    workspace.mkdir()
    return ToolContext(
        agent_id="agent-builder",
        session_key="agent:agent-builder:main",
        workspace_dir=str(workspace),
    )


@pytest.fixture
def tool():
    t = ListAgentsTool()
    t._agent_manager = None
    return t


def _create_agent(agents_dir, agent_id, name, description="", model=None, autonomy_enabled=False):
    ws = agents_dir / agent_id
    ws.mkdir(exist_ok=True)
    data = {"id": agent_id, "name": name, "description": description}
    if model:
        data["model"] = model
    if autonomy_enabled:
        data["autonomy"] = {"enabled": True}
    with open(ws / "agent.yaml", "w") as f:
        yaml.dump(data, f)


@pytest.mark.asyncio
async def test_list_all(tool, context, agents_dir):
    _create_agent(agents_dir, "alpha", "Alpha Agent")
    _create_agent(agents_dir, "beta", "Beta Agent", model="qwen3-8b")

    result = await tool.execute({}, context)

    assert result.success is True
    agents = result.data["agents"]
    ids = [a["agent_id"] for a in agents]
    assert "agent-builder" in ids
    assert "alpha" in ids
    assert "beta" in ids


@pytest.mark.asyncio
async def test_list_running_only(tool, context, agents_dir):
    _create_agent(agents_dir, "running-one", "Running One")
    _create_agent(agents_dir, "stopped-one", "Stopped One")

    mock_manager = MagicMock()
    mock_manager._agents = {"running-one": MagicMock()}
    tool._agent_manager = mock_manager

    result = await tool.execute({"status": "running"}, context)

    assert result.success is True
    agents = result.data["agents"]
    assert len(agents) == 1
    assert agents[0]["agent_id"] == "running-one"
    assert agents[0]["status"] == "running"


@pytest.mark.asyncio
async def test_list_stopped_only(tool, context, agents_dir):
    _create_agent(agents_dir, "running-two", "Running Two")
    _create_agent(agents_dir, "stopped-two", "Stopped Two")

    mock_manager = MagicMock()
    mock_manager._agents = {"running-two": MagicMock()}
    tool._agent_manager = mock_manager

    result = await tool.execute({"status": "stopped"}, context)

    assert result.success is True
    agents = result.data["agents"]
    ids = [a["agent_id"] for a in agents]
    assert "running-two" not in ids
    assert "stopped-two" in ids


@pytest.mark.asyncio
async def test_list_empty_system(tool, context, agents_dir):
    # Only the builder agent exists (from context fixture)
    result = await tool.execute({}, context)

    assert result.success is True
    agents = result.data["agents"]
    assert len(agents) == 1
    assert agents[0]["agent_id"] == "agent-builder"


@pytest.mark.asyncio
async def test_agent_details_fields(tool, context, agents_dir):
    _create_agent(
        agents_dir, "detailed", "Detailed Agent",
        description="A detailed one", model="qwen3-8b", autonomy_enabled=True,
    )

    result = await tool.execute({}, context)

    agent = next(a for a in result.data["agents"] if a["agent_id"] == "detailed")
    assert agent["name"] == "Detailed Agent"
    assert agent["description"] == "A detailed one"
    assert agent["model"] == "qwen3-8b"
    assert agent["autonomy_enabled"] is True
    assert agent["status"] == "stopped"
