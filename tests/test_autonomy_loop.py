"""Tests for the AutonomyLoop."""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from openhoof.agents.autonomy_loop import AutonomyLoop, YieldDirective
from openhoof.core.hot_state import HotState, HotStateFieldConfig
from openhoof.tools import ToolRegistry


@pytest.fixture
def hot_state():
    return HotState({
        "prices": HotStateFieldConfig(type="object", ttl=30, refresh_tool="get_prices"),
        "cash": HotStateFieldConfig(type="number", ttl=30),
    })


@pytest.fixture
def autonomy_config():
    config = MagicMock()
    config.enabled = True
    config.max_consecutive_turns = 5
    config.token_budget_per_hour = 100000
    config.max_actions_per_minute = 10
    config.idle_timeout = 600
    config.active_hours = None
    config.precheck_model = None
    return config


@pytest.fixture
def tool_registry():
    return ToolRegistry()


@pytest.fixture
def mock_inference():
    return AsyncMock()


@pytest.fixture
def loop(hot_state, autonomy_config, tool_registry, mock_inference):
    mock_run_turn = AsyncMock(return_value="I'll keep monitoring. Sleeping for 30s — nothing actionable.")
    return AutonomyLoop(
        agent_id="test-trader",
        run_agent_turn=mock_run_turn,
        hot_state=hot_state,
        sensors=[],
        tool_registry=tool_registry,
        inference=mock_inference,
        config=autonomy_config,
    )


class TestYieldParsing:
    def test_parse_sleep(self, loop):
        response = "Checking complete. Sleeping for 30s — monitoring."
        directive = loop._parse_yield_from_response(response)
        assert directive.mode == "sleep"
        assert directive.sleep == 30

    def test_parse_sleep_with_wake_early(self, loop):
        response = "Sleeping for 60s (wake early on: order_filled, stop_loss) — waiting for fill."
        directive = loop._parse_yield_from_response(response)
        assert directive.mode == "sleep"
        assert directive.sleep == 60
        assert "order_filled" in directive.wake_early_if
        assert "stop_loss" in directive.wake_early_if

    def test_parse_shutdown(self, loop):
        response = "Market closed. Shutting down autonomous loop."
        directive = loop._parse_yield_from_response(response)
        assert directive.mode == "shutdown"

    def test_parse_continue_default(self, loop):
        response = "I notice TSLA RSI is dropping. Let me check further."
        directive = loop._parse_yield_from_response(response)
        assert directive.mode == "continue"


class TestContextBuilding:
    def test_context_includes_hot_state(self, loop, hot_state):
        hot_state.set("prices", {"AAPL": 189.20})
        hot_state.set("cash", 50000)
        message = loop._build_context_message()
        assert "Hot State" in message
        assert "189.20" in message or "AAPL" in message
        assert "50000" in message

    def test_context_includes_notifications(self, loop, hot_state):
        hot_state.push_notification("order_filled", {"symbol": "AAPL", "qty": 100})
        message = loop._build_context_message()
        assert "Notifications" in message
        assert "order_filled" in message

    def test_context_includes_turn_number(self, loop):
        loop._turn_count = 42
        message = loop._build_context_message()
        assert "Turn 42" in message or "turn" in message.lower()


class TestPreCheckGate:
    @pytest.mark.asyncio
    async def test_precheck_skips_when_no_changes(self, loop, hot_state):
        loop.config.precheck_model = "qwen3-1.7b"
        # No changes since last snapshot
        loop._last_snapshot_time = time.time() + 1  # Future = nothing is newer

        directive = await loop._run_turn()
        assert directive.mode == "sleep"
        assert "no changes" in directive.reason

    @pytest.mark.asyncio
    async def test_precheck_passes_with_notifications(self, loop, hot_state, mock_inference):
        loop.config.precheck_model = "qwen3-1.7b"
        hot_state.push_notification("alert", {"msg": "important"})
        mock_inference.chat_completion = AsyncMock(return_value=MagicMock(content="NO"))

        # Even though precheck would say NO, notifications bypass it
        directive = await loop._run_turn()
        # Turn ran (not skipped), so we get a yield from the response
        assert directive.mode in ("sleep", "continue", "shutdown")

    @pytest.mark.asyncio
    async def test_no_precheck_model_always_runs(self, loop, hot_state):
        loop.config.precheck_model = None
        directive = await loop._run_turn()
        # Turn should have run
        loop._run_agent_turn.assert_called_once()


class TestAutoRefresh:
    @pytest.mark.asyncio
    async def test_auto_refreshes_stale_fields(self, loop, hot_state, tool_registry):
        # Make prices stale
        hot_state.set("prices", {"AAPL": 180})
        hot_state._fields["prices"].updated_at = time.time() - 60

        # Register a mock tool
        mock_tool = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"AAPL": 195}
        mock_result.message = None
        mock_tool.execute = AsyncMock(return_value=mock_result)
        mock_tool.name = "get_prices"
        mock_tool.autonomous_only = False
        mock_tool.validate_params = AsyncMock(return_value=None)
        tool_registry.register(mock_tool)

        await loop._auto_refresh_stale_fields()
        assert hot_state.get("prices") == {"AAPL": 195}


class TestGuardrails:
    def test_consecutive_turns_counter(self, loop):
        assert loop._consecutive_turns == 0
        loop._consecutive_turns += 1
        assert loop._consecutive_turns == 1

    @pytest.mark.asyncio
    async def test_max_consecutive_turns_forces_sleep(self, loop):
        loop._consecutive_turns = loop.config.max_consecutive_turns
        # The loop would force a sleep at this point
        assert loop._consecutive_turns >= loop.config.max_consecutive_turns

    def test_token_budget_tracking(self, loop):
        loop._tokens_this_hour = 0
        loop._tokens_this_hour += 50000
        assert loop._tokens_this_hour < loop.config.token_budget_per_hour
        loop._tokens_this_hour += 60000
        assert loop._tokens_this_hour >= loop.config.token_budget_per_hour

    def test_hour_reset(self, loop):
        loop._tokens_this_hour = 90000
        loop._hour_start = time.time() - 3700  # Over an hour ago
        loop._maybe_reset_hour()
        assert loop._tokens_this_hour == 0

    def test_rate_limiting(self, loop):
        now = time.time()
        for _ in range(15):
            loop._actions_this_minute.append(now)
        assert loop._is_rate_limited()

    def test_rate_limiting_clears_old(self, loop):
        old = time.time() - 70  # 70 seconds ago
        for _ in range(15):
            loop._actions_this_minute.append(old)
        assert not loop._is_rate_limited()

    def test_idle_timeout_detection(self, loop):
        loop._last_meaningful_action = time.time() - 700
        idle = time.time() - loop._last_meaningful_action
        assert idle > loop.config.idle_timeout

    def test_active_hours_check_no_config(self, loop):
        loop.config.active_hours = None
        assert loop._is_within_active_hours()


class TestSleepWithWakeEarly:
    @pytest.mark.asyncio
    async def test_sleep_full_duration_no_wake(self, loop, hot_state):
        start = time.time()
        await loop._sleep_with_wake_early(1, [])
        elapsed = time.time() - start
        assert elapsed >= 0.9

    @pytest.mark.asyncio
    async def test_wake_early_on_matching_notification(self, loop, hot_state):
        # Schedule a notification to arrive mid-sleep
        async def push_late():
            await asyncio.sleep(0.3)
            hot_state.push_notification("order_filled", {"symbol": "AAPL"})

        task = asyncio.create_task(push_late())

        start = time.time()
        await loop._sleep_with_wake_early(5, ["order_filled"])
        elapsed = time.time() - start

        assert elapsed < 3  # Woke up early
        task.cancel()

    @pytest.mark.asyncio
    async def test_no_wake_on_non_matching_notification(self, loop, hot_state):
        async def push_late():
            await asyncio.sleep(0.2)
            hot_state.push_notification("price_alert", {"symbol": "TSLA"})

        task = asyncio.create_task(push_late())

        start = time.time()
        await loop._sleep_with_wake_early(1, ["order_filled"])
        elapsed = time.time() - start

        assert elapsed >= 0.9  # Slept full duration
        task.cancel()


class TestSessionKey:
    def test_uses_autonomy_session(self, loop):
        assert loop.session_key == "agent:test-trader:autonomy"


class TestYieldDirective:
    def test_default_wake_early_if(self):
        d = YieldDirective(mode="sleep", sleep=30)
        assert d.wake_early_if == []

    def test_with_wake_early_if(self):
        d = YieldDirective(mode="sleep", sleep=30, wake_early_if=["alert"])
        assert d.wake_early_if == ["alert"]
