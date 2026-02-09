"""Integration tests for the builder agent system."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from openhoof.tools.builtin.configure_agent import ConfigureAgentTool
from openhoof.tools.builtin.list_agents import ListAgentsTool
from openhoof.tools.base import ToolContext
from openhoof.agents.lifecycle import AgentManager
from openhoof.config import Config


@pytest.fixture
def agents_dir(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    return d


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def mock_inference():
    return MagicMock()


@pytest.fixture
def context(agents_dir):
    workspace = agents_dir / "agent-builder"
    workspace.mkdir(exist_ok=True)
    return ToolContext(
        agent_id="agent-builder",
        session_key="agent:agent-builder:main",
        workspace_dir=str(workspace),
    )


# --- 6.1: Full agent creation flow ---

@pytest.mark.asyncio
async def test_full_agent_creation_flow(context, agents_dir):
    """Simulate builder creating a stock watcher agent end-to-end."""
    tool = ConfigureAgentTool()
    tool._agent_manager = None

    # Step 1: Builder calls configure_agent create
    result = await tool.execute({
        "action": "create",
        "agent_id": "stock-watcher",
        "config": {
            "name": "Stock Watcher",
            "description": "Monitors stock prices and alerts on significant changes",
            "model": "qwen3-8b",
            "tools": ["notify", "memory_write", "memory_read"],
            "max_tool_rounds": 5,
        },
        "files": {
            "SOUL.md": (
                "# Stock Watcher\n\n"
                "You monitor stock prices and alert users to significant changes.\n\n"
                "## Mission\n"
                "Watch configured stocks and send notifications when price movements "
                "exceed configured thresholds.\n"
            ),
        },
    }, context)

    assert result.success is True
    assert "stock-watcher" in result.message

    # Verify workspace created correctly
    ws = agents_dir / "stock-watcher"
    assert ws.exists()
    assert (ws / "agent.yaml").exists()
    assert (ws / "SOUL.md").exists()

    # Verify agent.yaml content
    with open(ws / "agent.yaml") as f:
        config = yaml.safe_load(f)
    assert config["id"] == "stock-watcher"
    assert config["name"] == "Stock Watcher"
    assert config["model"] == "qwen3-8b"
    assert "notify" in config["tools"]

    # Verify SOUL.md content
    soul = (ws / "SOUL.md").read_text()
    assert "Stock Watcher" in soul
    assert "stock prices" in soul


# --- 6.2: Agent modification flow ---

@pytest.mark.asyncio
async def test_agent_modification_flow(context, agents_dir):
    """Simulate builder reading and then updating an existing agent."""
    tool = ConfigureAgentTool()
    tool._agent_manager = None

    # Create initial agent
    ws = agents_dir / "fuel-analyst"
    ws.mkdir()
    initial_config = {
        "id": "fuel-analyst",
        "name": "Fuel Analyst",
        "description": "Analyzes fuel consumption",
        "model": "qwen3-8b",
        "tools": ["memory_write", "memory_read"],
        "max_tool_rounds": 5,
    }
    with open(ws / "agent.yaml", "w") as f:
        yaml.dump(initial_config, f)
    (ws / "SOUL.md").write_text("Original SOUL content")

    # Step 1: Builder reads the agent
    read_result = await tool.execute({
        "action": "read",
        "agent_id": "fuel-analyst",
    }, context)

    assert read_result.success is True
    assert read_result.data["config"]["name"] == "Fuel Analyst"

    # Step 2: Builder updates with new description and adds autonomy
    update_result = await tool.execute({
        "action": "update",
        "agent_id": "fuel-analyst",
        "config": {
            "description": "Analyzes fuel consumption and anomalies for C-17 fleet",
            "autonomy": {"enabled": True, "max_consecutive_turns": 25},
        },
        "files": {
            "SOUL.md": "Updated SOUL with autonomy focus",
        },
    }, context)

    assert update_result.success is True

    # Verify shallow merge: description updated, name preserved, autonomy replaced as section
    with open(ws / "agent.yaml") as f:
        updated = yaml.safe_load(f)

    assert updated["name"] == "Fuel Analyst"  # preserved
    assert updated["description"] == "Analyzes fuel consumption and anomalies for C-17 fleet"
    assert updated["model"] == "qwen3-8b"  # preserved
    assert updated["tools"] == ["memory_write", "memory_read"]  # preserved
    assert updated["autonomy"]["enabled"] is True
    assert updated["autonomy"]["max_consecutive_turns"] == 25
    # Defaults applied
    assert updated["autonomy"]["token_budget_per_hour"] == 100000

    # SOUL updated
    assert (ws / "SOUL.md").read_text() == "Updated SOUL with autonomy focus"


# --- 6.3: Provisioning + auto-start ---

def test_provisioning_and_autostart_config(agents_dir, data_dir, mock_inference):
    """System starts, builder workspace provisioned, auto-start config includes builder."""
    # AgentManager provisions defaults in __init__
    manager = AgentManager(
        agents_dir=agents_dir,
        data_dir=data_dir,
        inference=mock_inference,
    )

    # Builder workspace should exist
    builder_dir = agents_dir / "agent-builder"
    assert builder_dir.exists()
    assert (builder_dir / "agent.yaml").exists()
    assert (builder_dir / "SOUL.md").exists()

    # Verify the config includes builder in autostart
    config = Config()
    assert "agent-builder" in config.autostart_agents

    # Verify the builder agent.yaml has the right tools
    with open(builder_dir / "agent.yaml") as f:
        builder_config = yaml.safe_load(f)
    assert "configure_agent" in builder_config["tools"]
    assert "list_agents" in builder_config["tools"]
    assert "memory_write" in builder_config["tools"]
    assert "memory_read" in builder_config["tools"]


@pytest.mark.asyncio
async def test_configure_and_list_agents_together(context, agents_dir):
    """Create agents via configure_agent, then verify list_agents returns them."""
    configure = ConfigureAgentTool()
    configure._agent_manager = None
    list_tool = ListAgentsTool()
    list_tool._agent_manager = None

    # Create two agents
    await configure.execute({
        "action": "create",
        "agent_id": "alpha",
        "config": {"name": "Alpha", "description": "First agent"},
    }, context)
    await configure.execute({
        "action": "create",
        "agent_id": "beta",
        "config": {"name": "Beta", "model": "qwen3-1.7b"},
    }, context)

    # List all agents
    result = await list_tool.execute({}, context)

    assert result.success is True
    agents = result.data["agents"]
    ids = [a["agent_id"] for a in agents]
    assert "alpha" in ids
    assert "beta" in ids
    assert "agent-builder" in ids

    # Verify beta has correct model
    beta = next(a for a in agents if a["agent_id"] == "beta")
    assert beta["model"] == "qwen3-1.7b"
