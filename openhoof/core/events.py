"""Event bus for real-time updates."""

import asyncio
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Callable, Awaitable, Dict, List, Any, Optional, Set
from collections import defaultdict
import logging
import json

logger = logging.getLogger(__name__)

# Event types
EVENT_AGENT_STARTED = "agent:started"
EVENT_AGENT_STOPPED = "agent:stopped"
EVENT_AGENT_MESSAGE = "agent:message"
EVENT_AGENT_THINKING = "agent:thinking"
EVENT_AGENT_TOOL_CALL = "agent:tool_call"
EVENT_AGENT_TOOL_RESULT = "agent:tool_result"
EVENT_AGENT_ERROR = "agent:error"
EVENT_APPROVAL_REQUESTED = "approval:requested"
EVENT_APPROVAL_RESOLVED = "approval:resolved"
EVENT_HEARTBEAT_RAN = "heartbeat:ran"
EVENT_SUBAGENT_SPAWNED = "subagent:spawned"
EVENT_SUBAGENT_COMPLETED = "subagent:completed"
EVENT_ACTIVITY = "activity"


@dataclass
class Event:
    """An event in the system."""
    type: str
    data: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    event_id: Optional[str] = None
    
    def to_json(self) -> str:
        return json.dumps(asdict(self))


class WebSocketClient:
    """Represents a connected WebSocket client."""
    
    def __init__(self, websocket: Any, subscribed_agents: Optional[Set[str]] = None):
        self.websocket = websocket
        self.subscribed_agents: Set[str] = subscribed_agents or set()
        self.subscribe_all: bool = not subscribed_agents
    
    def should_receive(self, event: Event) -> bool:
        """Check if this client should receive the event."""
        if self.subscribe_all:
            return True
        
        agent_id = event.data.get("agent_id")
        if agent_id and agent_id in self.subscribed_agents:
            return True
        
        # Always send system-level events
        if event.type in (EVENT_AGENT_STARTED, EVENT_AGENT_STOPPED):
            return True
        
        return False


class EventBus:
    """Pub/sub event bus for real-time updates."""
    
    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Event], Awaitable[None]]]] = defaultdict(list)
        self._websockets: List[WebSocketClient] = []
        self._event_history: List[Event] = []
        self._max_history = 1000
        self._lock = asyncio.Lock()
    
    def subscribe(self, event_type: str, callback: Callable[[Event], Awaitable[None]]) -> None:
        """Subscribe to an event type."""
        self._subscribers[event_type].append(callback)
    
    def unsubscribe(self, event_type: str, callback: Callable[[Event], Awaitable[None]]) -> None:
        """Unsubscribe from an event type."""
        if callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)
    
    async def emit(self, event_type: str, data: Dict[str, Any]) -> Event:
        """Emit an event to subscribers and WebSocket clients."""
        event = Event(
            type=event_type,
            data=data,
            event_id=f"{event_type}:{datetime.now().timestamp()}"
        )
        
        # Store in history
        async with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history:]
        
        # Notify local subscribers
        for callback in self._subscribers.get(event_type, []):
            try:
                await callback(event)
            except Exception as e:
                logger.error(f"Error in event subscriber for {event_type}: {e}")
        
        # Notify all-event subscribers
        for callback in self._subscribers.get("*", []):
            try:
                await callback(event)
            except Exception as e:
                logger.error(f"Error in wildcard event subscriber: {e}")
        
        # Notify WebSocket clients
        await self._broadcast_to_websockets(event)
        
        logger.debug(f"Emitted event: {event_type}")
        return event
    
    async def _broadcast_to_websockets(self, event: Event) -> None:
        """Broadcast event to connected WebSocket clients."""
        disconnected: List[WebSocketClient] = []
        
        for client in self._websockets:
            if not client.should_receive(event):
                continue
            
            try:
                await client.websocket.send_text(event.to_json())
            except Exception as e:
                logger.warning(f"WebSocket send failed: {e}")
                disconnected.append(client)
        
        # Remove disconnected clients
        for client in disconnected:
            self._websockets.remove(client)
    
    async def connect_websocket(
        self,
        websocket: Any,
        subscribed_agents: Optional[Set[str]] = None
    ) -> WebSocketClient:
        """Register a WebSocket connection."""
        client = WebSocketClient(websocket, subscribed_agents)
        self._websockets.append(client)
        logger.info(f"WebSocket client connected (total: {len(self._websockets)})")
        return client
    
    async def disconnect_websocket(self, client: WebSocketClient) -> None:
        """Remove a WebSocket connection."""
        if client in self._websockets:
            self._websockets.remove(client)
            logger.info(f"WebSocket client disconnected (total: {len(self._websockets)})")
    
    def get_recent_events(
        self,
        limit: int = 100,
        event_types: Optional[List[str]] = None,
        agent_id: Optional[str] = None
    ) -> List[Event]:
        """Get recent events from history."""
        events = self._event_history.copy()
        
        if event_types:
            events = [e for e in events if e.type in event_types]
        
        if agent_id:
            events = [e for e in events if e.data.get("agent_id") == agent_id]
        
        return events[-limit:]


# Global event bus instance
event_bus = EventBus()
