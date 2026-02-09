"""Tests for configure_agent tool."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from openhoof.tools.builtin.configure_agent import ConfigureAgentTool
from openhoof.tools.base import ToolContext


@pytest.fixture
def agents_dir(tmp_path):
    """Create a temporary agents directory."""
    d = tmp_path / "agents"
    d.mkdir()
    return d


@pytest.fixture
def context(agents_dir):
    """Create a ToolContext pointing to a workspace inside agents_dir."""
    # The tool derives agents_dir from workspace_dir.parent
    workspace = agents_dir / "agent-builder"
    workspace.mkdir()
    return ToolContext(
        agent_id="agent-builder",
        session_key="agent:agent-builder:main",
        workspace_dir=str(workspace),
    )


@pytest.fixture
def tool():
    t = ConfigureAgentTool()
    t._agent_manager = None
    return t


# --- CREATE ---

@pytest.mark.asyncio
async def test_create_with_full_config(tool, context, agents_dir):
    result = await tool.execute({
        "action": "create",
        "agent_id": "stock-watcher",
        "config": {
            "name": "Stock Watcher",
            "description": "Monitors stock prices",
            "model": "qwen3-8b",
            "tools": ["notify"],
        },
        "files": {"SOUL.md": "You are a stock monitor."},
    }, context)

    assert result.success is True
    assert "stock-watcher" in result.message

    ws = agents_dir / "stock-watcher"
    assert ws.exists()
    assert (ws / "agent.yaml").exists()
    assert (ws / "SOUL.md").read_text() == "You are a stock monitor."

    with open(ws / "agent.yaml") as f:
        data = yaml.safe_load(f)
    assert data["name"] == "Stock Watcher"
    assert data["model"] == "qwen3-8b"


@pytest.mark.asyncio
async def test_create_with_minimal_config(tool, context, agents_dir):
    result = await tool.execute({
        "action": "create",
        "agent_id": "helper",
        "config": {"name": "Helper"},
    }, context)

    assert result.success is True
    ws = agents_dir / "helper"
    assert (ws / "SOUL.md").exists()
    assert "Helper" in (ws / "SOUL.md").read_text()


@pytest.mark.asyncio
async def test_create_duplicate_id(tool, context, agents_dir):
    # Create first
    (agents_dir / "existing").mkdir()
    result = await tool.execute({
        "action": "create",
        "agent_id": "existing",
        "config": {"name": "Existing"},
    }, context)

    assert result.success is False
    assert "already exists" in result.error


@pytest.mark.asyncio
async def test_create_with_advanced_config(tool, context, agents_dir):
    result = await tool.execute({
        "action": "create",
        "agent_id": "trader",
        "config": {
            "name": "Trader",
            "autonomy": {"enabled": True},
            "hot_state": {"fields": {"prices": {"type": "object", "ttl": 30}}},
            "sensors": [{
                "name": "price-feed",
                "type": "poll",
                "interval": 5,
                "source": {"tool": "get_prices"},
            }],
        },
    }, context)

    assert result.success is True
    with open(agents_dir / "trader" / "agent.yaml") as f:
        data = yaml.safe_load(f)
    # Autonomy defaults applied
    assert data["autonomy"]["max_consecutive_turns"] == 50
    # Sensor defaults applied
    assert data["sensors"][0]["updates"] == []


@pytest.mark.asyncio
async def test_create_missing_name(tool, context):
    result = await tool.execute({
        "action": "create",
        "agent_id": "no-name",
        "config": {"description": "No name agent"},
    }, context)

    assert result.success is False
    assert "name" in result.error


# --- READ ---

@pytest.mark.asyncio
async def test_read_existing(tool, context, agents_dir):
    ws = agents_dir / "test-agent"
    ws.mkdir()
    with open(ws / "agent.yaml", "w") as f:
        yaml.dump({"name": "Test", "id": "test-agent"}, f)
    (ws / "SOUL.md").write_text("soul content")

    result = await tool.execute({
        "action": "read",
        "agent_id": "test-agent",
    }, context)

    assert result.success is True
    assert result.data["config"]["name"] == "Test"
    assert len(result.data["files"]) == 2


@pytest.mark.asyncio
async def test_read_nonexistent(tool, context):
    result = await tool.execute({
        "action": "read",
        "agent_id": "nonexistent",
    }, context)

    assert result.success is False
    assert "not found" in result.error


# --- UPDATE ---

@pytest.mark.asyncio
async def test_update_scalar_fields(tool, context, agents_dir):
    ws = agents_dir / "updatable"
    ws.mkdir()
    with open(ws / "agent.yaml", "w") as f:
        yaml.dump({"name": "Old Name", "model": "qwen3-8b", "tools": ["notify"]}, f)

    result = await tool.execute({
        "action": "update",
        "agent_id": "updatable",
        "config": {"description": "New desc", "model": "qwen3-1.7b"},
    }, context)

    assert result.success is True
    with open(ws / "agent.yaml") as f:
        data = yaml.safe_load(f)
    assert data["description"] == "New desc"
    assert data["model"] == "qwen3-1.7b"
    assert data["name"] == "Old Name"  # preserved
    assert data["tools"] == ["notify"]  # preserved


@pytest.mark.asyncio
async def test_update_nested_section_replaces(tool, context, agents_dir):
    ws = agents_dir / "nested"
    ws.mkdir()
    with open(ws / "agent.yaml", "w") as f:
        yaml.dump({
            "name": "Nested",
            "autonomy": {
                "enabled": True,
                "max_consecutive_turns": 100,
                "token_budget_per_hour": 200000,
            },
        }, f)

    result = await tool.execute({
        "action": "update",
        "agent_id": "nested",
        "config": {"autonomy": {"enabled": True, "max_consecutive_turns": 20}},
    }, context)

    assert result.success is True
    with open(ws / "agent.yaml") as f:
        data = yaml.safe_load(f)
    # Entire autonomy section replaced, not merged
    assert data["autonomy"]["max_consecutive_turns"] == 20
    # Defaults applied to omitted fields
    assert data["autonomy"]["token_budget_per_hour"] == 100000


@pytest.mark.asyncio
async def test_update_workspace_files(tool, context, agents_dir):
    ws = agents_dir / "file-update"
    ws.mkdir()
    with open(ws / "agent.yaml", "w") as f:
        yaml.dump({"name": "FileUpdate"}, f)

    result = await tool.execute({
        "action": "update",
        "agent_id": "file-update",
        "files": {"SOUL.md": "Updated soul", "HEARTBEAT.md": "Check hourly"},
    }, context)

    assert result.success is True
    assert (ws / "SOUL.md").read_text() == "Updated soul"
    assert (ws / "HEARTBEAT.md").read_text() == "Check hourly"


@pytest.mark.asyncio
async def test_update_nonexistent(tool, context):
    result = await tool.execute({
        "action": "update",
        "agent_id": "nonexistent",
        "config": {"name": "Ghost"},
    }, context)

    assert result.success is False
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_update_running_agent_warning(tool, context, agents_dir):
    ws = agents_dir / "running-agent"
    ws.mkdir()
    with open(ws / "agent.yaml", "w") as f:
        yaml.dump({"name": "Running"}, f)

    # Mock agent_manager with running agent
    mock_manager = MagicMock()
    mock_manager._agents = {"running-agent": MagicMock()}
    tool._agent_manager = mock_manager

    result = await tool.execute({
        "action": "update",
        "agent_id": "running-agent",
        "config": {"description": "updated"},
    }, context)

    assert result.success is True
    assert "restart" in result.message.lower()


# --- DELETE ---

@pytest.mark.asyncio
async def test_delete_stopped(tool, context, agents_dir):
    ws = agents_dir / "deleteme"
    ws.mkdir()
    (ws / "agent.yaml").write_text("name: Deleteme")

    result = await tool.execute({
        "action": "delete",
        "agent_id": "deleteme",
    }, context)

    assert result.success is True
    assert not ws.exists()


@pytest.mark.asyncio
async def test_delete_running(tool, context, agents_dir):
    ws = agents_dir / "running-del"
    ws.mkdir()
    (ws / "agent.yaml").write_text("name: Running")

    mock_manager = MagicMock()
    mock_manager._agents = {"running-del": MagicMock()}
    mock_manager.stop_agent = AsyncMock()
    tool._agent_manager = mock_manager

    result = await tool.execute({
        "action": "delete",
        "agent_id": "running-del",
    }, context)

    assert result.success is True
    mock_manager.stop_agent.assert_called_once_with("running-del")
    assert not ws.exists()


@pytest.mark.asyncio
async def test_delete_nonexistent(tool, context):
    result = await tool.execute({
        "action": "delete",
        "agent_id": "nonexistent",
    }, context)

    assert result.success is False
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_delete_builder_prevented(tool, context, agents_dir):
    ws = agents_dir / "agent-builder"
    # Already exists from fixture

    result = await tool.execute({
        "action": "delete",
        "agent_id": "agent-builder",
    }, context)

    assert result.success is False
    assert "Cannot delete" in result.error


# --- VALIDATION ---

@pytest.mark.asyncio
async def test_invalid_sensor_config(tool, context):
    result = await tool.execute({
        "action": "create",
        "agent_id": "bad-sensor",
        "config": {
            "name": "Bad Sensor",
            "sensors": [{"name": "s1", "type": "poll"}],  # missing interval
        },
    }, context)

    assert result.success is False
    assert "interval" in result.error


@pytest.mark.asyncio
async def test_invalid_hot_state_type(tool, context):
    result = await tool.execute({
        "action": "create",
        "agent_id": "bad-hs",
        "config": {
            "name": "Bad HS",
            "hot_state": {"fields": {"f1": {"type": "invalid_type"}}},
        },
    }, context)

    assert result.success is False
    assert "type must be one of" in result.error


@pytest.mark.asyncio
async def test_invalid_agent_id_format(tool, context):
    result = await tool.execute({
        "action": "create",
        "agent_id": "Invalid Agent ID!",
        "config": {"name": "Bad ID"},
    }, context)

    assert result.success is False
    assert "kebab-case" in result.error


# --- SAFE DEFAULTS ---

@pytest.mark.asyncio
async def test_autonomy_defaults(tool, context, agents_dir):
    result = await tool.execute({
        "action": "create",
        "agent_id": "auto-defaults",
        "config": {
            "name": "Auto Defaults",
            "autonomy": {"enabled": True},
        },
    }, context)

    assert result.success is True
    with open(agents_dir / "auto-defaults" / "agent.yaml") as f:
        data = yaml.safe_load(f)
    assert data["autonomy"]["max_consecutive_turns"] == 50
    assert data["autonomy"]["token_budget_per_hour"] == 100000
    assert data["autonomy"]["max_actions_per_minute"] == 10
    assert data["autonomy"]["idle_timeout"] == 600


@pytest.mark.asyncio
async def test_hot_state_field_defaults(tool, context, agents_dir):
    result = await tool.execute({
        "action": "create",
        "agent_id": "hs-defaults",
        "config": {
            "name": "HS Defaults",
            "hot_state": {"fields": {"price": {"ttl": 30}}},
        },
    }, context)

    assert result.success is True
    with open(agents_dir / "hs-defaults" / "agent.yaml") as f:
        data = yaml.safe_load(f)
    assert data["hot_state"]["fields"]["price"]["type"] == "object"


@pytest.mark.asyncio
async def test_sensor_signal_defaults(tool, context, agents_dir):
    result = await tool.execute({
        "action": "create",
        "agent_id": "sig-defaults",
        "config": {
            "name": "Sig Defaults",
            "sensors": [{
                "name": "s1",
                "type": "poll",
                "interval": 5,
                "source": {"tool": "get_data"},
                "signals": [{"name": "alert", "model": "qwen3-1.7b", "prompt": "Is it bad?"}],
            }],
        },
    }, context)

    assert result.success is True
    with open(agents_dir / "sig-defaults" / "agent.yaml") as f:
        data = yaml.safe_load(f)
    signal = data["sensors"][0]["signals"][0]
    assert signal["threshold"] == 0.8
    assert signal["notify"] is True
