"""Tests for YieldTool."""

import pytest
from openhoof.tools.builtin.yield_tool import YieldTool
from openhoof.tools.base import ToolContext


@pytest.fixture
def yield_tool():
    return YieldTool()


@pytest.fixture
def context():
    return ToolContext(agent_id="test-agent", session_key="test:main", workspace_dir="/tmp")


class TestYieldTool:
    @pytest.mark.asyncio
    async def test_sleep_mode(self, yield_tool, context):
        result = await yield_tool.execute(
            {"mode": "sleep", "sleep": 30, "reason": "nothing happening"},
            context,
        )
        assert result.success
        assert "30s" in result.message
        assert "nothing happening" in result.message

    @pytest.mark.asyncio
    async def test_continue_mode(self, yield_tool, context):
        result = await yield_tool.execute(
            {"mode": "continue", "reason": "investigating"},
            context,
        )
        assert result.success
        assert "Continuing" in result.message

    @pytest.mark.asyncio
    async def test_shutdown_mode(self, yield_tool, context):
        result = await yield_tool.execute(
            {"mode": "shutdown", "reason": "market closed"},
            context,
        )
        assert result.success
        assert "Shutting down" in result.message

    @pytest.mark.asyncio
    async def test_sleep_with_wake_early_if(self, yield_tool, context):
        result = await yield_tool.execute(
            {"mode": "sleep", "sleep": 300, "wake_early_if": ["order_filled", "stop_loss"]},
            context,
        )
        assert result.success
        assert "order_filled" in result.message
        assert "stop_loss" in result.message

    @pytest.mark.asyncio
    async def test_invalid_mode(self, yield_tool, context):
        result = await yield_tool.execute(
            {"mode": "invalid"},
            context,
        )
        assert not result.success
        assert "Invalid mode" in result.error

    @pytest.mark.asyncio
    async def test_sleep_without_seconds(self, yield_tool, context):
        result = await yield_tool.execute(
            {"mode": "sleep"},
            context,
        )
        assert not result.success
        assert "positive integer" in result.error

    @pytest.mark.asyncio
    async def test_sleep_with_zero_seconds(self, yield_tool, context):
        result = await yield_tool.execute(
            {"mode": "sleep", "sleep": 0},
            context,
        )
        assert not result.success

    def test_autonomous_only_flag(self, yield_tool):
        assert yield_tool.autonomous_only is True

    def test_schema_has_mode_enum(self, yield_tool):
        schema = yield_tool.to_openai_schema()
        mode_prop = schema["function"]["parameters"]["properties"]["mode"]
        assert "enum" in mode_prop
        assert set(mode_prop["enum"]) == {"sleep", "continue", "shutdown"}
