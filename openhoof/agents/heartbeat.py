"""Heartbeat runner for periodic agent checks."""

import asyncio
from datetime import datetime, time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable
import logging

logger = logging.getLogger(__name__)


@dataclass
class HeartbeatConfig:
    """Configuration for heartbeat."""
    enabled: bool = True
    every_seconds: int = 1800  # 30 minutes
    active_hours_start: Optional[time] = time(8, 0)   # 8 AM
    active_hours_end: Optional[time] = time(23, 0)    # 11 PM
    prompt: str = "Read HEARTBEAT.md if it exists. Follow instructions strictly. If nothing needs attention, reply HEARTBEAT_OK."


@dataclass
class HeartbeatResult:
    """Result of a heartbeat check."""
    status: str  # "ran", "skipped", "failed"
    reason: Optional[str] = None
    duration_ms: Optional[int] = None
    response: Optional[str] = None


class HeartbeatRunner:
    """Runs periodic heartbeat checks for agents."""
    
    def __init__(
        self,
        agent_id: str,
        workspace_dir: Path,
        config: HeartbeatConfig,
        run_callback: Callable[[str, str], Awaitable[str]],  # (agent_id, prompt) -> response
    ):
        self.agent_id = agent_id
        self.workspace_dir = workspace_dir
        self.config = config
        self.run_callback = run_callback
        self._task: Optional[asyncio.Task] = None
        self._stopped = False
        self._last_run_at: Optional[float] = None
        self._last_heartbeat_text: Optional[str] = None
    
    def _is_within_active_hours(self) -> bool:
        if not self.config.active_hours_start or not self.config.active_hours_end:
            return True
        
        now = datetime.now().time()
        start = self.config.active_hours_start
        end = self.config.active_hours_end
        
        if end > start:
            return start <= now < end
        else:  # Spans midnight
            return now >= start or now < end
    
    def _is_heartbeat_file_empty(self) -> bool:
        heartbeat_path = self.workspace_dir / "HEARTBEAT.md"
        if not heartbeat_path.exists():
            return True
        
        content = heartbeat_path.read_text().strip()
        # Consider empty if only comments and whitespace
        lines = [l for l in content.split('\n') if l.strip() and not l.strip().startswith('#')]
        return len(lines) == 0
    
    def _is_duplicate_response(self, response: str) -> bool:
        """Suppress duplicate heartbeat responses."""
        if not self._last_heartbeat_text:
            return False
        
        # OK responses are never duplicates
        cleaned = response.strip().upper()
        if "HEARTBEAT_OK" in cleaned or "HEARTBEAT OK" in cleaned:
            return False
        
        return response.strip() == self._last_heartbeat_text
    
    async def run_once(self, reason: str = "interval") -> HeartbeatResult:
        """Execute a single heartbeat check."""
        if not self.config.enabled:
            return HeartbeatResult(status="skipped", reason="disabled")
        
        if not self._is_within_active_hours():
            return HeartbeatResult(status="skipped", reason="quiet-hours")
        
        # Don't skip if heartbeat file is empty - agent might have tasks
        
        start_time = datetime.now()
        
        try:
            response = await self.run_callback(self.agent_id, self.config.prompt)
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            
            # Check for OK response
            if "HEARTBEAT_OK" in response.upper():
                return HeartbeatResult(
                    status="ran",
                    reason="ok",
                    duration_ms=duration_ms,
                )
            
            # Check for duplicate
            if self._is_duplicate_response(response):
                return HeartbeatResult(
                    status="skipped",
                    reason="duplicate",
                    duration_ms=duration_ms,
                )
            
            # Record and return alert
            self._last_heartbeat_text = response.strip()
            self._last_run_at = datetime.now().timestamp()
            
            return HeartbeatResult(
                status="ran",
                reason="alert",
                duration_ms=duration_ms,
                response=response,
            )
            
        except Exception as e:
            logger.error(f"Heartbeat failed for {self.agent_id}: {e}")
            return HeartbeatResult(status="failed", reason=str(e))
    
    async def _loop(self):
        """Background heartbeat loop."""
        while not self._stopped:
            await asyncio.sleep(self.config.every_seconds)
            if self._stopped:
                break
            
            result = await self.run_once(reason="interval")
            logger.info(f"Heartbeat {self.agent_id}: {result.status} ({result.reason})")
    
    def start(self):
        """Start the heartbeat background task."""
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Heartbeat started for {self.agent_id} (every {self.config.every_seconds}s)")
    
    def stop(self):
        """Stop the heartbeat background task."""
        self._stopped = True
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info(f"Heartbeat stopped for {self.agent_id}")
    
    async def wake(self, reason: str = "wake") -> HeartbeatResult:
        """Trigger an immediate heartbeat check."""
        return await self.run_once(reason=reason)
