"""Sensor framework — background data collectors for autonomous agents."""

import asyncio
import json
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import logging

import aiohttp

from .hot_state import HotState
from .events import (
    event_bus,
    EVENT_AUTONOMY_SENSOR_UPDATED,
    EVENT_AUTONOMY_SENSOR_ERROR,
    EVENT_AUTONOMY_NOTIFICATION_PUSHED,
)

logger = logging.getLogger(__name__)

MAX_BACKOFF = 300  # 5 minutes


class Sensor(ABC):
    """Abstract base class for sensors."""

    def __init__(
        self,
        name: str,
        agent_id: str,
        hot_state: HotState,
        update_fields: List[str],
        signal_configs: Optional[List[Dict[str, Any]]] = None,
        inference: Optional[Any] = None,
    ):
        self.name = name
        self.agent_id = agent_id
        self.hot_state = hot_state
        self.update_fields = update_fields
        self.signal_configs = signal_configs or []
        self.inference = inference
        self._task: Optional[asyncio.Task] = None
        self._stopped = False
        self._backoff: float = 0
        self._signal_last_fired: Dict[str, float] = {}

    def start(self):
        """Start the sensor background task."""
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Sensor started: {self.name} (agent={self.agent_id})")

    def stop(self):
        """Stop the sensor background task."""
        self._stopped = True
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info(f"Sensor stopped: {self.name} (agent={self.agent_id})")

    async def _run_loop(self):
        """Main loop with error handling and backoff."""
        while not self._stopped:
            try:
                await self._loop_iteration()
                # Reset backoff on success
                self._backoff = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Sensor {self.name} error: {e}")
                await event_bus.emit(EVENT_AUTONOMY_SENSOR_ERROR, {
                    "agent_id": self.agent_id,
                    "sensor_name": self.name,
                    "error": str(e),
                })
                # Exponential backoff
                if self._backoff == 0:
                    self._backoff = self._get_base_interval()
                else:
                    self._backoff = min(self._backoff * 2, MAX_BACKOFF)
                await asyncio.sleep(self._backoff)

    def _get_base_interval(self) -> float:
        """Get the base interval for backoff. Override in subclasses."""
        return 5.0

    @abstractmethod
    async def _loop_iteration(self):
        """Single iteration of the sensor loop. Subclasses implement this."""
        pass

    async def _write_to_hot_state(self, data: Any):
        """Write fetched data to configured hot state fields."""
        for field_name in self.update_fields:
            self.hot_state.set(field_name, data)
            await event_bus.emit(EVENT_AUTONOMY_SENSOR_UPDATED, {
                "agent_id": self.agent_id,
                "sensor_name": self.name,
                "field": field_name,
                "timestamp": time.time(),
            })

    async def _run_signals(self, data: Any):
        """Run ML signal detection on fetched data."""
        if not self.signal_configs or not self.inference:
            return

        for signal_cfg in self.signal_configs:
            signal_name = signal_cfg["name"]
            cooldown = signal_cfg.get("cooldown")

            # Check cooldown
            if cooldown and signal_name in self._signal_last_fired:
                elapsed = time.time() - self._signal_last_fired[signal_name]
                if elapsed < cooldown:
                    continue

            try:
                # Call lightweight model
                model = signal_cfg["model"]
                prompt = signal_cfg["prompt"]
                threshold = signal_cfg.get("threshold", 0.8)

                data_str = json.dumps(data, default=str) if not isinstance(data, str) else data
                response = await self.inference.chat_completion(
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": data_str},
                    ],
                    model=model,
                    stateless=True,
                    rag_enabled=False,
                )

                # Parse score from response
                score = self._parse_score(response.content)
                if score is not None and score >= threshold:
                    self._signal_last_fired[signal_name] = time.time()
                    if signal_cfg.get("notify", True):
                        self.hot_state.push_notification(signal_name, {
                            "signal": signal_name,
                            "score": score,
                            "data": data,
                            "sensor": self.name,
                        })
                        await event_bus.emit(EVENT_AUTONOMY_NOTIFICATION_PUSHED, {
                            "agent_id": self.agent_id,
                            "sensor_name": self.name,
                            "signal_name": signal_name,
                            "score": score,
                        })
            except Exception as e:
                logger.warning(f"Signal {signal_name} evaluation failed: {e}")

    @staticmethod
    def _parse_score(text: str) -> Optional[float]:
        """Extract a float score from model response text."""
        import re
        # Look for a decimal number between 0 and 1
        matches = re.findall(r'\b(0(?:\.\d+)?|1(?:\.0+)?)\b', text)
        if matches:
            return float(matches[-1])
        # Try to find any float
        matches = re.findall(r'(\d+\.?\d*)', text)
        for m in matches:
            val = float(m)
            if 0 <= val <= 1:
                return val
        return None


class PollSensor(Sensor):
    """Sensor that polls a data source at a fixed interval."""

    def __init__(
        self,
        name: str,
        agent_id: str,
        hot_state: HotState,
        update_fields: List[str],
        interval: int,
        tool_name: Optional[str] = None,
        tool_params: Optional[Dict[str, Any]] = None,
        url: Optional[str] = None,
        tool_registry: Optional[Any] = None,
        signal_configs: Optional[List[Dict[str, Any]]] = None,
        inference: Optional[Any] = None,
    ):
        super().__init__(name, agent_id, hot_state, update_fields, signal_configs, inference)
        self.interval = interval
        self.tool_name = tool_name
        self.tool_params = tool_params or {}
        self.url = url
        self.tool_registry = tool_registry

    def _get_base_interval(self) -> float:
        return float(self.interval)

    async def _loop_iteration(self):
        """Poll the data source and update hot state."""
        data = await self._fetch()
        await self._write_to_hot_state(data)
        await self._run_signals(data)
        await asyncio.sleep(self.interval)

    async def _fetch(self) -> Any:
        """Fetch data from the configured source."""
        if self.tool_name and self.tool_registry:
            from ..tools.base import ToolContext
            context = ToolContext(
                agent_id=self.agent_id,
                session_key=f"sensor:{self.agent_id}:{self.name}",
                workspace_dir="",
            )
            result = await self.tool_registry.execute(self.tool_name, self.tool_params, context)
            if result.success:
                return result.data if result.data else result.message
            raise RuntimeError(f"Tool {self.tool_name} failed: {result.error}")
        elif self.url:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url) as resp:
                    resp.raise_for_status()
                    content_type = resp.content_type or ""
                    if "json" in content_type:
                        return await resp.json()
                    return await resp.text()
        else:
            raise RuntimeError(f"Sensor {self.name}: no tool or URL configured")


class WatchSensor(Sensor):
    """Sensor that monitors a file/directory for changes."""

    def __init__(
        self,
        name: str,
        agent_id: str,
        hot_state: HotState,
        update_fields: List[str],
        path: str,
        signal_configs: Optional[List[Dict[str, Any]]] = None,
        inference: Optional[Any] = None,
    ):
        super().__init__(name, agent_id, hot_state, update_fields, signal_configs, inference)
        self.path = path
        self._last_mtime: Optional[float] = None

    async def _loop_iteration(self):
        """Check for file changes and update hot state."""
        if not os.path.exists(self.path):
            await asyncio.sleep(2)
            return

        mtime = os.path.getmtime(self.path)
        if self._last_mtime is None or mtime > self._last_mtime:
            self._last_mtime = mtime
            with open(self.path) as f:
                content = f.read()
            # Try to parse as JSON
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                data = content
            await self._write_to_hot_state(data)
            await self._run_signals(data)

        await asyncio.sleep(1)  # Check every second


class StreamSensor(Sensor):
    """Sensor that connects to a streaming data source (WebSocket or SSE)."""

    def __init__(
        self,
        name: str,
        agent_id: str,
        hot_state: HotState,
        update_fields: List[str],
        url: str,
        signal_configs: Optional[List[Dict[str, Any]]] = None,
        inference: Optional[Any] = None,
    ):
        super().__init__(name, agent_id, hot_state, update_fields, signal_configs, inference)
        self.url = url

    async def _loop_iteration(self):
        """Connect to stream and process messages."""
        async with aiohttp.ClientSession() as session:
            if self.url.startswith("ws://") or self.url.startswith("wss://"):
                async with session.ws_connect(self.url) as ws:
                    async for msg in ws:
                        if self._stopped:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                            except (json.JSONDecodeError, ValueError):
                                data = msg.data
                            await self._write_to_hot_state(data)
                            await self._run_signals(data)
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            break
            else:
                # SSE: treat as line-delimited stream
                async with session.get(self.url) as resp:
                    resp.raise_for_status()
                    async for line in resp.content:
                        if self._stopped:
                            break
                        text = line.decode().strip()
                        if text.startswith("data:"):
                            text = text[5:].strip()
                        if not text:
                            continue
                        try:
                            data = json.loads(text)
                        except (json.JSONDecodeError, ValueError):
                            data = text
                        await self._write_to_hot_state(data)
                        await self._run_signals(data)


def sensor_factory(
    config: Any,  # SensorConfig from lifecycle
    agent_id: str,
    hot_state: HotState,
    tool_registry: Optional[Any] = None,
    inference: Optional[Any] = None,
) -> Optional[Sensor]:
    """Create a sensor from config. Returns None if config is invalid."""
    update_fields = [u.field for u in config.updates]

    signal_configs = [
        {
            "name": s.name,
            "model": s.model,
            "prompt": s.prompt,
            "threshold": s.threshold,
            "notify": s.notify,
            "cooldown": s.cooldown,
        }
        for s in config.signals
    ]

    if config.type == "poll":
        if config.interval is None:
            logger.error(f"Poll sensor '{config.name}' missing interval")
            return None
        return PollSensor(
            name=config.name,
            agent_id=agent_id,
            hot_state=hot_state,
            update_fields=update_fields,
            interval=config.interval,
            tool_name=config.source.tool,
            tool_params=config.source.params,
            url=config.source.url,
            tool_registry=tool_registry,
            signal_configs=signal_configs if signal_configs else None,
            inference=inference,
        )
    elif config.type == "watch":
        path = config.source.path
        if not path:
            logger.error(f"Watch sensor '{config.name}' missing path")
            return None
        return WatchSensor(
            name=config.name,
            agent_id=agent_id,
            hot_state=hot_state,
            update_fields=update_fields,
            path=path,
            signal_configs=signal_configs if signal_configs else None,
            inference=inference,
        )
    elif config.type == "stream":
        url = config.source.url
        if not url:
            logger.error(f"Stream sensor '{config.name}' missing source URL")
            return None
        return StreamSensor(
            name=config.name,
            agent_id=agent_id,
            hot_state=hot_state,
            update_fields=update_fields,
            url=url,
            signal_configs=signal_configs if signal_configs else None,
            inference=inference,
        )
    else:
        logger.error(f"Unknown sensor type: {config.type}")
        return None
