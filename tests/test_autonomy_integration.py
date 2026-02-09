"""Integration tests for autonomous agent lifecycle."""

import asyncio
import tempfile
from pathlib import Path
import pytest
import yaml
from unittest.mock import AsyncMock, MagicMock

from openhoof.agents.lifecycle import AgentConfig, AgentHandle, AgentManager
from openhoof.core.hot_state import HotState
from openhoof.agents.autonomy_loop import AutonomyLoop


class TestAgentConfigParsing:
    def test_parse_minimal_autonomy(self, tmp_path):
        config_path = tmp_path / "agent.yaml"
        config_path.write_text(yaml.dump({
            "id": "trader",
            "name": "Stock Trader",
            "autonomy": {"enabled": True},
        }))
        config = AgentConfig.from_yaml(config_path)
        assert config.autonomy is not None
        assert config.autonomy.enabled is True
        assert config.autonomy.max_consecutive_turns == 50
        assert config.autonomy.token_budget_per_hour == 100000

    def test_parse_full_autonomy(self, tmp_path):
        config_path = tmp_path / "agent.yaml"
        config_path.write_text(yaml.dump({
            "id": "trader",
            "name": "Stock Trader",
            "autonomy": {
                "enabled": True,
                "max_consecutive_turns": 20,
                "token_budget_per_hour": 50000,
                "idle_timeout": 300,
                "active_hours": {"start": "09:30", "end": "16:00"},
                "precheck_model": "qwen3-1.7b",
            },
        }))
        config = AgentConfig.from_yaml(config_path)
        assert config.autonomy.max_consecutive_turns == 20
        assert config.autonomy.active_hours.start == "09:30"
        assert config.autonomy.precheck_model == "qwen3-1.7b"

    def test_parse_hot_state(self, tmp_path):
        config_path = tmp_path / "agent.yaml"
        config_path.write_text(yaml.dump({
            "id": "trader",
            "name": "Trader",
            "hot_state": {
                "fields": {
                    "positions": {"type": "object", "ttl": 30, "refresh_tool": "get_positions"},
                    "cash": {"type": "number", "ttl": 30},
                    "log": {"type": "array", "max_items": 20},
                }
            },
        }))
        config = AgentConfig.from_yaml(config_path)
        assert config.hot_state is not None
        assert len(config.hot_state.fields) == 3
        assert config.hot_state.fields["positions"].refresh_tool == "get_positions"
        assert config.hot_state.fields["log"].max_items == 20

    def test_parse_sensors(self, tmp_path):
        config_path = tmp_path / "agent.yaml"
        config_path.write_text(yaml.dump({
            "id": "trader",
            "name": "Trader",
            "sensors": [
                {
                    "name": "price_feed",
                    "type": "poll",
                    "interval": 5,
                    "source": {"tool": "get_market_data", "params": {"symbols": ["AAPL"]}},
                    "updates": [{"field": "prices"}],
                    "signals": [{
                        "name": "anomaly",
                        "model": "qwen3-1.7b",
                        "prompt": "Is this anomalous?",
                        "threshold": 0.8,
                    }],
                },
            ],
        }))
        config = AgentConfig.from_yaml(config_path)
        assert len(config.sensors) == 1
        assert config.sensors[0].name == "price_feed"
        assert config.sensors[0].source.tool == "get_market_data"
        assert len(config.sensors[0].signals) == 1

    def test_no_autonomy_config(self, tmp_path):
        config_path = tmp_path / "agent.yaml"
        config_path.write_text(yaml.dump({
            "id": "basic",
            "name": "Basic Agent",
        }))
        config = AgentConfig.from_yaml(config_path)
        assert config.autonomy is None
        assert config.hot_state is None
        assert config.sensors == []

    def test_invalid_sensor_skipped(self, tmp_path):
        config_path = tmp_path / "agent.yaml"
        config_path.write_text(yaml.dump({
            "id": "trader",
            "name": "Trader",
            "sensors": [
                {"bad": "config"},  # Missing required fields
                {
                    "name": "good",
                    "type": "poll",
                    "interval": 5,
                    "source": {"tool": "get_data"},
                    "updates": [{"field": "data"}],
                },
            ],
        }))
        config = AgentConfig.from_yaml(config_path)
        # Bad sensor was skipped, good one was parsed
        assert len(config.sensors) == 1
        assert config.sensors[0].name == "good"


class TestAgentHandleFields:
    def test_handle_has_autonomy_fields(self):
        config = AgentConfig(agent_id="test", name="test")
        handle = AgentHandle(
            agent_id="test",
            config=config,
            workspace=MagicMock(),
            session=MagicMock(),
        )
        assert handle.autonomy_loop is None
        assert handle.hot_state is None
        assert handle.sensors == []


class TestYieldToolFiltering:
    def test_yield_excluded_from_non_autonomous_schemas(self):
        from openhoof.tools import ToolRegistry
        from openhoof.tools.builtin import register_builtin_tools

        registry = ToolRegistry()
        register_builtin_tools(registry)

        # Non-autonomous: yield should be excluded
        schemas = registry.get_openai_schemas(include_autonomous=False)
        tool_names = [s["function"]["name"] for s in schemas]
        assert "yield" not in tool_names

        # Autonomous: yield should be included
        schemas = registry.get_openai_schemas(include_autonomous=True)
        tool_names = [s["function"]["name"] for s in schemas]
        assert "yield" in tool_names
