"""
Heartbeat — Health checks, exit conditions, and sync timing.

The heartbeat system:
1. Runs every N seconds (configurable)
2. Checks exit conditions (battery, geofence, timeout, etc.)
3. Syncs buffered data when network available
4. Logs health status
5. Triggers memory updates

Exit conditions are user-defined lambdas:
    agent.on_exit("battery_low", lambda: agent.battery < 20)
    agent.on_exit("timeout", lambda: time.time() - agent.start_time > 300)
"""

from __future__ import annotations

import time
from typing import Callable, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import Agent


class ExitCondition:
    """A named exit condition with a check function."""
    
    def __init__(self, name: str, check: Callable[[], bool]):
        self.name = name
        self.check = check
        self.triggered = False
        self.triggered_at: Optional[float] = None
    
    def evaluate(self) -> bool:
        """Evaluate the condition. Returns True if should exit."""
        if self.triggered:
            return True
        
        try:
            if self.check():
                self.triggered = True
                self.triggered_at = time.time()
                return True
        except Exception as e:
            # Don't crash on bad exit conditions
            print(f"⚠️ Exit condition {self.name!r} raised exception: {e}")
        
        return False
    
    def __repr__(self) -> str:
        status = "TRIGGERED" if self.triggered else "active"
        return f"ExitCondition({self.name!r}, status={status})"


class Heartbeat:
    """Heartbeat system for agent health monitoring."""
    
    def __init__(self, agent: Agent, interval: float = 30.0):
        self.agent = agent
        self.interval = interval
        self.last_beat: float = 0.0
        self.beat_count: int = 0
        
        # Exit conditions
        self.exit_conditions: Dict[str, ExitCondition] = {}
        
        # Heartbeat callbacks
        self.callbacks: list[Callable[[], None]] = []
    
    def should_beat(self) -> bool:
        """Check if it's time for a heartbeat."""
        return (time.time() - self.last_beat) >= self.interval
    
    def beat(self):
        """Execute a heartbeat."""
        self.beat_count += 1
        self.last_beat = time.time()
        
        # Run all callbacks
        for callback in self.callbacks:
            try:
                callback()
            except Exception as e:
                print(f"⚠️ Heartbeat callback raised exception: {e}")
        
        # Log to memory
        if self.beat_count % 10 == 0:  # Every 10th heartbeat
            self.agent.memory.log_daily(
                f"Heartbeat #{self.beat_count} — "
                f"state={self.agent.state}, "
                f"events_processed={self.agent.events_processed}"
            )
    
    def add_exit_condition(self, name: str, check: Callable[[], bool]):
        """Register a new exit condition."""
        self.exit_conditions[name] = ExitCondition(name, check)
    
    def check_exit_conditions(self) -> Optional[str]:
        """
        Check all exit conditions.
        Returns the name of the first triggered condition, or None.
        """
        for condition in self.exit_conditions.values():
            if condition.evaluate():
                return condition.name
        return None
    
    def on_heartbeat(self, callback: Callable[[], None]):
        """Register a callback to run on every heartbeat."""
        self.callbacks.append(callback)
    
    def __repr__(self) -> str:
        return (
            f"Heartbeat(interval={self.interval}s, "
            f"count={self.beat_count}, "
            f"exit_conditions={len(self.exit_conditions)})"
        )
