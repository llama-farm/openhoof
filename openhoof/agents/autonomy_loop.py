"""Autonomy loop — brain-driven continuous agent execution."""

import asyncio
import json
import time
from collections import deque
from datetime import datetime, time as dt_time
from dataclasses import dataclass
from typing import Any, Callable, Awaitable, Dict, List, Optional
import logging

from ..core.hot_state import HotState, HotStateFieldConfig
from ..core.sensors import Sensor
from ..core.events import (
    event_bus,
    EVENT_AUTONOMY_TURN_STARTED,
    EVENT_AUTONOMY_TURN_COMPLETED,
    EVENT_AUTONOMY_PRECHECK_SKIPPED,
    EVENT_AUTONOMY_GUARDRAIL_TRIGGERED,
)
from ..tools import ToolRegistry, ToolContext

logger = logging.getLogger(__name__)

# Default yield when agent doesn't call yield tool
DEFAULT_YIELD = {"mode": "continue", "sleep": 0, "reason": "", "wake_early_if": []}
DEFAULT_FORCED_SLEEP = 60  # seconds, when guardrail forces a sleep


@dataclass
class YieldDirective:
    """Parsed yield from the agent's response."""
    mode: str  # "sleep", "continue", "shutdown"
    sleep: int = 0
    reason: str = ""
    wake_early_if: List[str] = None

    def __post_init__(self):
        if self.wake_early_if is None:
            self.wake_early_if = []


class AutonomyLoop:
    """Brain-driven autonomous agent loop."""

    def __init__(
        self,
        agent_id: str,
        run_agent_turn: Callable[[str, str, str], Awaitable[str]],
        hot_state: HotState,
        sensors: List[Sensor],
        tool_registry: ToolRegistry,
        inference: Any,
        config: Any,  # AutonomyConfig
    ):
        self.agent_id = agent_id
        self._run_agent_turn = run_agent_turn
        self.hot_state = hot_state
        self.sensors = sensors
        self.tool_registry = tool_registry
        self.inference = inference
        self.config = config

        self._task: Optional[asyncio.Task] = None
        self._stopped = False

        # Guardrail state
        self._turn_count = 0
        self._consecutive_turns = 0
        self._tokens_this_hour = 0
        self._hour_start = time.time()
        self._actions_this_minute: deque = deque()
        self._last_meaningful_action: float = time.time()
        self._last_snapshot_time: float = time.time()

        # Session key for autonomous turns
        self.session_key = f"agent:{agent_id}:autonomy"

    def start(self):
        """Start the autonomy loop and all sensors."""
        if self._task is not None:
            return
        self._stopped = False
        self._last_meaningful_action = time.time()

        # Start sensors
        for sensor in self.sensors:
            sensor.start()

        # Start the loop
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Autonomy loop started for {self.agent_id}")

    def stop(self):
        """Stop the loop and all sensors."""
        self._stopped = True
        if self._task:
            self._task.cancel()
            self._task = None

        for sensor in self.sensors:
            sensor.stop()

        logger.info(f"Autonomy loop stopped for {self.agent_id}")

    async def _loop(self):
        """Main autonomous loop: observe/think/act/yield."""
        while not self._stopped:
            try:
                # Check active hours
                if not self._is_within_active_hours():
                    sleep_until = self._seconds_until_active()
                    await self._emit_guardrail("active_hours", {
                        "message": f"Outside active hours, sleeping for {sleep_until}s",
                    })
                    await asyncio.sleep(sleep_until)
                    continue

                # Check token budget
                self._maybe_reset_hour()
                if self._tokens_this_hour >= self.config.token_budget_per_hour:
                    sleep_until = self._seconds_until_next_hour()
                    await self._emit_guardrail("token_budget", {
                        "tokens_used": self._tokens_this_hour,
                        "budget": self.config.token_budget_per_hour,
                        "sleep_seconds": sleep_until,
                    })
                    await asyncio.sleep(sleep_until)
                    continue

                # Check idle timeout
                idle_seconds = time.time() - self._last_meaningful_action
                if idle_seconds > self.config.idle_timeout:
                    await self._emit_guardrail("idle_timeout", {
                        "idle_seconds": idle_seconds,
                        "timeout": self.config.idle_timeout,
                    })
                    self.stop()
                    return

                # Run a turn
                yield_directive = await self._run_turn()

                # Act on yield
                if yield_directive.mode == "shutdown":
                    logger.info(f"Agent {self.agent_id} requested shutdown: {yield_directive.reason}")
                    self.stop()
                    return
                elif yield_directive.mode == "sleep":
                    self._consecutive_turns = 0
                    await self._sleep_with_wake_early(
                        yield_directive.sleep,
                        yield_directive.wake_early_if,
                    )
                else:  # continue
                    self._consecutive_turns += 1
                    # Check max consecutive turns
                    if self._consecutive_turns >= self.config.max_consecutive_turns:
                        await self._emit_guardrail("max_consecutive_turns", {
                            "turns": self._consecutive_turns,
                            "limit": self.config.max_consecutive_turns,
                        })
                        self._consecutive_turns = 0
                        await asyncio.sleep(DEFAULT_FORCED_SLEEP)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Autonomy loop error for {self.agent_id}: {e}")
                await asyncio.sleep(5)  # Brief pause on unexpected errors

    async def _run_turn(self) -> YieldDirective:
        """Execute a single autonomous turn."""
        self._turn_count += 1

        # 1. Collect notifications
        has_notifications = self.hot_state.has_notifications()

        # 2. Pre-check gate
        if not has_notifications and self.config.precheck_model:
            diff = self.hot_state.diff_since(self._last_snapshot_time)
            if not diff:
                await event_bus.emit(EVENT_AUTONOMY_PRECHECK_SKIPPED, {
                    "agent_id": self.agent_id,
                    "turn": self._turn_count,
                    "reason": "no_changes",
                })
                return YieldDirective(mode="sleep", sleep=10, reason="pre-check: no changes")

            # Run lightweight model to assess materiality
            should_proceed = await self._run_precheck(diff)
            if not should_proceed:
                await event_bus.emit(EVENT_AUTONOMY_PRECHECK_SKIPPED, {
                    "agent_id": self.agent_id,
                    "turn": self._turn_count,
                    "reason": "no_material_changes",
                })
                return YieldDirective(mode="sleep", sleep=10, reason="pre-check: no material changes")

        # 3. Auto-refresh stale fields
        await self._auto_refresh_stale_fields()

        # 4. Build context message
        message = self._build_context_message()

        # 5. Emit turn started
        await event_bus.emit(EVENT_AUTONOMY_TURN_STARTED, {
            "agent_id": self.agent_id,
            "turn": self._turn_count,
            "hot_state_summary": self._hot_state_summary(),
            "notifications_pending": has_notifications,
        })

        # 6. Clear notifications (agent is about to see them)
        notifications = self.hot_state.pop_notifications()

        # 7. Snapshot time for next diff
        self._last_snapshot_time = self.hot_state.snapshot_time()

        # 8. Run the turn
        response = await self._run_agent_turn(
            self.agent_id,
            self.session_key,
            message,
        )

        # 9. Parse yield from response
        yield_directive = self._parse_yield_from_response(response)

        # 10. Track meaningful actions
        if self._response_had_tool_calls(response):
            self._last_meaningful_action = time.time()
            self._record_action()

        # 11. Emit turn completed
        await event_bus.emit(EVENT_AUTONOMY_TURN_COMPLETED, {
            "agent_id": self.agent_id,
            "turn": self._turn_count,
            "yield_mode": yield_directive.mode,
            "yield_sleep": yield_directive.sleep,
            "yield_reason": yield_directive.reason,
        })

        return yield_directive

    async def _run_precheck(self, diff: Dict[str, Any]) -> bool:
        """Run lightweight model to determine if changes are material."""
        try:
            diff_str = json.dumps(diff, default=str)
            response = await self.inference.chat_completion(
                messages=[
                    {"role": "system", "content": (
                        "You are a pre-check gate. Given the following state changes, "
                        "determine if any are materially significant and require the agent's attention. "
                        "Reply with YES if the agent should wake up, NO if changes are insignificant."
                    )},
                    {"role": "user", "content": f"State changes:\n{diff_str}"},
                ],
                model=self.config.precheck_model,
                stateless=True,
                rag_enabled=False,
            )
            return "YES" in response.content.upper()
        except Exception as e:
            logger.warning(f"Pre-check gate failed, allowing turn: {e}")
            return True  # Fail open

    async def _auto_refresh_stale_fields(self):
        """Refresh stale hot state fields that have a refresh_tool configured."""
        refreshable = self.hot_state.get_refreshable_stale_fields()
        for field_name, tool_name in refreshable:
            try:
                context = ToolContext(
                    agent_id=self.agent_id,
                    session_key=self.session_key,
                    workspace_dir="",
                )
                result = await self.tool_registry.execute(tool_name, {}, context)
                if result.success:
                    data = result.data if result.data else result.message
                    self.hot_state.set(field_name, data)
            except Exception as e:
                logger.warning(f"Auto-refresh failed for {field_name} via {tool_name}: {e}")

    def _build_context_message(self) -> str:
        """Build the synthetic observe message for the LLM."""
        parts = []

        # Notifications section
        notifications = self.hot_state._notifications  # Peek without popping
        if notifications:
            parts.append("## Notifications\n")
            for n in notifications:
                data_str = json.dumps(n.data, default=str)
                parts.append(f"**{n.name}**: {data_str}")
            parts.append("")

        # Hot state section
        rendered = self.hot_state.render()
        if rendered:
            parts.append(rendered)
            parts.append("")

        # Turn prompt
        parts.append(f"## Turn {self._turn_count}")
        parts.append(
            "Observe the current state and decide your next action. "
            "When done, call the `yield` tool to control your pacing "
            "(sleep, continue, or shutdown)."
        )

        return "\n".join(parts)

    def _parse_yield_from_response(self, response: str) -> YieldDirective:
        """Parse yield tool call from the agent's response.

        The yield tool call is intercepted by the loop runner. Since _run_agent_turn
        executes tool calls internally, we look for the yield tool's confirmation
        message pattern in the response text.
        """
        # Look for yield confirmation patterns in the response
        response_lower = response.lower()
        if "shutting down" in response_lower:
            return YieldDirective(mode="shutdown", reason="agent requested shutdown")
        if "sleeping for" in response_lower:
            # Try to extract sleep duration
            import re
            match = re.search(r'sleeping for (\d+)s', response_lower)
            sleep_seconds = int(match.group(1)) if match else 30
            # Try to extract wake_early_if
            wake_match = re.search(r'wake early on: ([^)]+)\)', response_lower)
            wake_early = []
            if wake_match:
                wake_early = [s.strip() for s in wake_match.group(1).split(",")]
            return YieldDirective(mode="sleep", sleep=sleep_seconds, wake_early_if=wake_early)

        # Default: continue
        return YieldDirective(mode="continue")

    def _response_had_tool_calls(self, response: str) -> bool:
        """Heuristic: check if response indicates tool calls were made."""
        # Tool results show up in the response when tools are called
        indicators = ["Success", "Error:", "Tool", "executed"]
        return any(ind in response for ind in indicators)

    def _record_action(self):
        """Record an action for rate limiting."""
        now = time.time()
        self._actions_this_minute.append(now)
        # Clean old entries
        cutoff = now - 60
        while self._actions_this_minute and self._actions_this_minute[0] < cutoff:
            self._actions_this_minute.popleft()

    def _is_rate_limited(self) -> bool:
        """Check if we're over the actions-per-minute limit."""
        now = time.time()
        cutoff = now - 60
        while self._actions_this_minute and self._actions_this_minute[0] < cutoff:
            self._actions_this_minute.popleft()
        return len(self._actions_this_minute) >= self.config.max_actions_per_minute

    async def _sleep_with_wake_early(self, seconds: int, wake_early_if: List[str]):
        """Sleep for the given duration, but wake early if a matching notification arrives."""
        if not wake_early_if:
            await asyncio.sleep(seconds)
            return

        # Poll the notification queue during sleep
        interval = min(1.0, seconds / 10)  # Check ~10 times during sleep
        elapsed = 0.0
        while elapsed < seconds and not self._stopped:
            await asyncio.sleep(interval)
            elapsed += interval
            # Check for matching notifications
            for n in self.hot_state._notifications:
                if n.name in wake_early_if:
                    logger.info(
                        f"Agent {self.agent_id} woken early by notification: {n.name}"
                    )
                    return

    def _is_within_active_hours(self) -> bool:
        """Check if current time is within configured active hours."""
        if not self.config.active_hours:
            return True

        now = datetime.now().time()
        start = self._parse_time(self.config.active_hours.start)
        end = self._parse_time(self.config.active_hours.end)

        if end > start:
            return start <= now < end
        else:  # Spans midnight
            return now >= start or now < end

    def _seconds_until_active(self) -> int:
        """Calculate seconds until the next active hours window."""
        if not self.config.active_hours:
            return 0
        # Simple approximation: check every 5 minutes
        return 300

    def _maybe_reset_hour(self):
        """Reset hourly token counter if an hour has passed."""
        if time.time() - self._hour_start >= 3600:
            self._tokens_this_hour = 0
            self._hour_start = time.time()

    def _seconds_until_next_hour(self) -> int:
        """Seconds remaining in the current hour."""
        elapsed = time.time() - self._hour_start
        return max(1, int(3600 - elapsed))

    def _hot_state_summary(self) -> Dict[str, Any]:
        """Brief summary of hot state for events."""
        summary = {}
        for name in list(self.hot_state._fields.keys())[:5]:  # Limit to 5 fields
            val = self.hot_state.get(name)
            if val is not None:
                summary[name] = str(val)[:100]
        return summary

    @staticmethod
    def _parse_time(time_str: str) -> dt_time:
        """Parse HH:MM string to time object."""
        parts = time_str.split(":")
        return dt_time(int(parts[0]), int(parts[1]))

    async def _emit_guardrail(self, guardrail_type: str, details: Dict[str, Any]):
        """Emit a guardrail triggered event."""
        await event_bus.emit(EVENT_AUTONOMY_GUARDRAIL_TRIGGERED, {
            "agent_id": self.agent_id,
            "guardrail": guardrail_type,
            **details,
        })
        logger.warning(f"Guardrail triggered for {self.agent_id}: {guardrail_type}")
