"""Tests for HotState."""

import time
import pytest
from openhoof.core.hot_state import HotState, HotStateFieldConfig


@pytest.fixture
def hot_state():
    """Create a HotState with typical fields."""
    return HotState({
        "positions": HotStateFieldConfig(type="object", ttl=30, refresh_tool="get_positions"),
        "cash": HotStateFieldConfig(type="number", ttl=30),
        "signals_log": HotStateFieldConfig(type="array", max_items=5),
        "name": HotStateFieldConfig(type="string"),
    })


class TestSetGet:
    def test_set_and_get(self, hot_state):
        hot_state.set("cash", 50000)
        assert hot_state.get("cash") == 50000

    def test_get_unset_returns_none(self, hot_state):
        assert hot_state.get("cash") is None

    def test_get_unknown_field_returns_none(self, hot_state):
        assert hot_state.get("nonexistent") is None

    def test_set_unknown_field_returns_false(self, hot_state):
        assert hot_state.set("nonexistent", 123) is False

    def test_set_object_field(self, hot_state):
        positions = {"AAPL": {"qty": 100, "avg": 187.50}}
        hot_state.set("positions", positions)
        assert hot_state.get("positions") == positions

    def test_set_updates_timestamp(self, hot_state):
        before = time.time()
        hot_state.set("cash", 50000)
        after = time.time()
        f = hot_state._fields["cash"]
        assert before <= f.updated_at <= after


class TestMaxItems:
    def test_set_array_enforces_max_items(self, hot_state):
        hot_state.set("signals_log", [1, 2, 3, 4, 5, 6, 7])
        assert hot_state.get("signals_log") == [3, 4, 5, 6, 7]

    def test_set_array_within_limit(self, hot_state):
        hot_state.set("signals_log", [1, 2, 3])
        assert hot_state.get("signals_log") == [1, 2, 3]

    def test_append_enforces_max_items(self, hot_state):
        for i in range(7):
            hot_state.append("signals_log", i)
        assert hot_state.get("signals_log") == [2, 3, 4, 5, 6]

    def test_append_to_non_array_fails(self, hot_state):
        assert hot_state.append("cash", 100) is False


class TestStaleness:
    def test_field_within_ttl_not_stale(self, hot_state):
        hot_state.set("cash", 50000)
        assert hot_state.is_stale("cash") is False

    def test_field_past_ttl_is_stale(self, hot_state):
        hot_state.set("cash", 50000)
        hot_state._fields["cash"].updated_at = time.time() - 60  # 60s ago, ttl=30
        assert hot_state.is_stale("cash") is True

    def test_field_with_no_ttl_never_stale(self, hot_state):
        hot_state.set("name", "trader-1")
        hot_state._fields["name"].updated_at = time.time() - 9999
        assert hot_state.is_stale("name") is False

    def test_unset_field_with_ttl_is_stale(self, hot_state):
        # cash has ttl=30 but was never set
        assert hot_state.is_stale("cash") is True

    def test_get_stale_fields(self, hot_state):
        hot_state.set("positions", {"AAPL": 100})
        hot_state.set("cash", 50000)
        # Make positions stale
        hot_state._fields["positions"].updated_at = time.time() - 60
        stale = hot_state.get_stale_fields()
        assert "positions" in stale
        assert "cash" not in stale

    def test_get_refreshable_stale_fields(self, hot_state):
        hot_state.set("positions", {"AAPL": 100})
        hot_state.set("cash", 50000)
        # Make both stale
        hot_state._fields["positions"].updated_at = time.time() - 60
        hot_state._fields["cash"].updated_at = time.time() - 60
        refreshable = hot_state.get_refreshable_stale_fields()
        # Only positions has refresh_tool
        assert len(refreshable) == 1
        assert refreshable[0] == ("positions", "get_positions")


class TestRender:
    def test_render_empty_state(self, hot_state):
        rendered = hot_state.render()
        assert "(not yet loaded)" in rendered

    def test_render_fresh_values(self, hot_state):
        hot_state.set("cash", 50000)
        hot_state.set("name", "trader-1")
        rendered = hot_state.render()
        assert "50000" in rendered
        assert "trader-1" in rendered
        assert "stale" not in rendered

    def test_render_stale_marker(self, hot_state):
        hot_state.set("cash", 50000)
        hot_state._fields["cash"].updated_at = time.time() - 45
        rendered = hot_state.render()
        assert "stale:" in rendered
        assert "45s ago" in rendered or "stale" in rendered


class TestNotifications:
    def test_push_and_pop(self, hot_state):
        hot_state.push_notification("order_filled", {"symbol": "AAPL"})
        hot_state.push_notification("stop_loss", {"symbol": "TSLA"})
        assert hot_state.has_notifications()

        notifications = hot_state.pop_notifications()
        assert len(notifications) == 2
        assert notifications[0].name == "order_filled"
        assert notifications[1].name == "stop_loss"

        # Queue is cleared
        assert not hot_state.has_notifications()
        assert hot_state.pop_notifications() == []


class TestDiff:
    def test_diff_since(self, hot_state):
        t0 = hot_state.snapshot_time()
        time.sleep(0.01)
        hot_state.set("cash", 50000)
        diff = hot_state.diff_since(t0)
        assert "cash" in diff
        assert diff["cash"]["value"] == 50000

    def test_diff_excludes_old_updates(self, hot_state):
        hot_state.set("cash", 50000)
        time.sleep(0.01)
        t0 = hot_state.snapshot_time()
        time.sleep(0.01)
        hot_state.set("name", "trader-1")
        diff = hot_state.diff_since(t0)
        assert "name" in diff
        assert "cash" not in diff
