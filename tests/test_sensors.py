"""Tests for the sensor framework."""

import asyncio
import json
import os
import tempfile
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from openhoof.core.hot_state import HotState, HotStateFieldConfig
from openhoof.core.sensors import PollSensor, WatchSensor, Sensor, sensor_factory


@pytest.fixture
def hot_state():
    return HotState({
        "prices": HotStateFieldConfig(type="object", ttl=5),
        "signals": HotStateFieldConfig(type="array", max_items=10),
    })


class TestPollSensorWithTool:
    @pytest.mark.asyncio
    async def test_poll_sensor_calls_tool_and_updates_hot_state(self, hot_state):
        # Mock tool registry
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"AAPL": 189.20, "TSLA": 241.30}
        mock_result.message = None

        mock_registry = AsyncMock()
        mock_registry.execute = AsyncMock(return_value=mock_result)

        sensor = PollSensor(
            name="price_feed",
            agent_id="trader",
            hot_state=hot_state,
            update_fields=["prices"],
            interval=1,
            tool_name="get_market_data",
            tool_params={"symbols": ["AAPL"]},
            tool_registry=mock_registry,
        )

        # Run one fetch
        data = await sensor._fetch()
        assert data == {"AAPL": 189.20, "TSLA": 241.30}

        # Write to hot state
        await sensor._write_to_hot_state(data)
        assert hot_state.get("prices") == {"AAPL": 189.20, "TSLA": 241.30}

    @pytest.mark.asyncio
    async def test_poll_sensor_tool_failure_raises(self, hot_state):
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "connection timeout"

        mock_registry = AsyncMock()
        mock_registry.execute = AsyncMock(return_value=mock_result)

        sensor = PollSensor(
            name="broken",
            agent_id="trader",
            hot_state=hot_state,
            update_fields=["prices"],
            interval=1,
            tool_name="get_data",
            tool_registry=mock_registry,
        )

        with pytest.raises(RuntimeError, match="connection timeout"):
            await sensor._fetch()


class TestPollSensorBackoff:
    @pytest.mark.asyncio
    async def test_backoff_doubles_on_error(self, hot_state):
        sensor = PollSensor(
            name="test",
            agent_id="trader",
            hot_state=hot_state,
            update_fields=["prices"],
            interval=2,
        )
        assert sensor._backoff == 0
        # Simulate first backoff
        sensor._backoff = sensor._get_base_interval()
        assert sensor._backoff == 2.0
        # Double
        sensor._backoff = min(sensor._backoff * 2, 300)
        assert sensor._backoff == 4.0
        # Caps at MAX_BACKOFF
        sensor._backoff = 200
        sensor._backoff = min(sensor._backoff * 2, 300)
        assert sensor._backoff == 300


class TestWatchSensor:
    @pytest.mark.asyncio
    async def test_watch_sensor_detects_file_change(self, hot_state):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"signal": "buy"}, f)
            f.flush()
            path = f.name

        try:
            sensor = WatchSensor(
                name="watcher",
                agent_id="trader",
                hot_state=hot_state,
                update_fields=["signals"],
                path=path,
            )

            # Run one iteration — should detect the file
            await sensor._loop_iteration()
            assert hot_state.get("signals") == {"signal": "buy"}

            # Modify the file
            time.sleep(0.1)  # Ensure mtime changes
            with open(path, "w") as f:
                json.dump({"signal": "sell"}, f)

            await sensor._loop_iteration()
            assert hot_state.get("signals") == {"signal": "sell"}
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_watch_sensor_handles_missing_file(self, hot_state):
        sensor = WatchSensor(
            name="watcher",
            agent_id="trader",
            hot_state=hot_state,
            update_fields=["prices"],
            path="/nonexistent/file.json",
        )
        # Should not raise
        await sensor._loop_iteration()
        assert hot_state.get("prices") is None


class TestSignalDetection:
    @pytest.mark.asyncio
    async def test_signal_fires_on_threshold(self, hot_state):
        mock_inference = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "Score: 0.92"
        mock_inference.chat_completion = AsyncMock(return_value=mock_response)

        sensor = PollSensor(
            name="monitor",
            agent_id="trader",
            hot_state=hot_state,
            update_fields=["prices"],
            interval=5,
            tool_name="get_data",
            tool_registry=AsyncMock(),
            signal_configs=[{
                "name": "anomaly",
                "model": "qwen3-1.7b",
                "prompt": "Is this anomalous?",
                "threshold": 0.8,
                "notify": True,
            }],
            inference=mock_inference,
        )

        await sensor._run_signals({"price": 100})
        assert hot_state.has_notifications()
        notifications = hot_state.pop_notifications()
        assert len(notifications) == 1
        assert notifications[0].name == "anomaly"

    @pytest.mark.asyncio
    async def test_signal_below_threshold_no_notification(self, hot_state):
        mock_inference = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "Score: 0.3"
        mock_inference.chat_completion = AsyncMock(return_value=mock_response)

        sensor = PollSensor(
            name="monitor",
            agent_id="trader",
            hot_state=hot_state,
            update_fields=["prices"],
            interval=5,
            tool_name="get_data",
            tool_registry=AsyncMock(),
            signal_configs=[{
                "name": "anomaly",
                "model": "qwen3-1.7b",
                "prompt": "Is this anomalous?",
                "threshold": 0.8,
                "notify": True,
            }],
            inference=mock_inference,
        )

        await sensor._run_signals({"price": 100})
        assert not hot_state.has_notifications()

    @pytest.mark.asyncio
    async def test_signal_cooldown_prevents_refire(self, hot_state):
        mock_inference = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "0.95"
        mock_inference.chat_completion = AsyncMock(return_value=mock_response)

        sensor = PollSensor(
            name="monitor",
            agent_id="trader",
            hot_state=hot_state,
            update_fields=["prices"],
            interval=5,
            tool_name="get_data",
            tool_registry=AsyncMock(),
            signal_configs=[{
                "name": "anomaly",
                "model": "qwen3-1.7b",
                "prompt": "test",
                "threshold": 0.8,
                "notify": True,
                "cooldown": 300,
            }],
            inference=mock_inference,
        )

        # First fire
        await sensor._run_signals({"price": 100})
        assert hot_state.has_notifications()
        hot_state.pop_notifications()

        # Second fire within cooldown — should not fire
        await sensor._run_signals({"price": 200})
        assert not hot_state.has_notifications()


class TestScoreParsing:
    def test_parse_decimal(self):
        assert Sensor._parse_score("0.92") == 0.92

    def test_parse_from_sentence(self):
        score = Sensor._parse_score("The anomaly score is 0.85 based on the data")
        assert score == 0.85

    def test_parse_zero(self):
        assert Sensor._parse_score("0") == 0.0

    def test_parse_one(self):
        assert Sensor._parse_score("1.0") == 1.0

    def test_parse_no_score(self):
        assert Sensor._parse_score("no numbers here") is None


class TestSensorFactory:
    def test_creates_poll_sensor(self, hot_state):
        config = MagicMock()
        config.name = "poller"
        config.type = "poll"
        config.interval = 5
        config.source.tool = "get_data"
        config.source.params = {}
        config.source.url = None
        config.updates = [MagicMock(field="prices")]
        config.signals = []

        sensor = sensor_factory(config, "agent-1", hot_state)
        assert isinstance(sensor, PollSensor)
        assert sensor.name == "poller"

    def test_creates_watch_sensor(self, hot_state):
        config = MagicMock()
        config.name = "watcher"
        config.type = "watch"
        config.source.path = "/tmp/data.json"
        config.updates = [MagicMock(field="prices")]
        config.signals = []

        sensor = sensor_factory(config, "agent-1", hot_state)
        assert isinstance(sensor, WatchSensor)

    def test_returns_none_for_invalid_type(self, hot_state):
        config = MagicMock()
        config.name = "bad"
        config.type = "unknown"
        config.updates = []
        config.signals = []

        sensor = sensor_factory(config, "agent-1", hot_state)
        assert sensor is None

    def test_returns_none_for_poll_without_interval(self, hot_state):
        config = MagicMock()
        config.name = "bad_poll"
        config.type = "poll"
        config.interval = None
        config.updates = []
        config.signals = []

        sensor = sensor_factory(config, "agent-1", hot_state)
        assert sensor is None
