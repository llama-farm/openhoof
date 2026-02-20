"""
Events — Event-driven "data wake up" system.

The event queue enables:
1. Push-based activation (detector pushes event → agent wakes)
2. Non-polling architecture (sleep until event arrives)
3. Priority handling (high-priority events first)
4. Event buffering when agent is busy

Events are simple dicts with:
    {
        "type": "drone.detection",
        "data": {...},
        "priority": 1.0,  # 0.0 = low, 1.0 = high
        "timestamp": 1234567890.0
    }
"""

from __future__ import annotations

import queue
import time
from typing import Any, Dict, List, Optional


class Event:
    """A single event in the queue."""
    
    def __init__(
        self,
        event_type: str,
        data: Dict[str, Any],
        priority: float = 0.5,
        timestamp: Optional[float] = None
    ):
        self.type = event_type
        self.data = data
        self.priority = priority
        self.timestamp = timestamp or time.time()
    
    def __lt__(self, other: Event) -> bool:
        """Higher priority first, then older events."""
        if self.priority != other.priority:
            return self.priority > other.priority
        return self.timestamp < other.timestamp
    
    def __repr__(self) -> str:
        return f"Event(type={self.type!r}, priority={self.priority}, ts={self.timestamp:.1f})"


class EventQueue:
    """Priority queue for agent events."""
    
    def __init__(self, maxsize: int = 1000):
        self.queue: queue.PriorityQueue = queue.PriorityQueue(maxsize=maxsize)
        self.total_pushed = 0
        self.total_popped = 0
    
    def push(self, event_type: str, data: Dict[str, Any], priority: float = 0.5):
        """Push an event onto the queue."""
        event = Event(event_type, data, priority)
        try:
            self.queue.put_nowait(event)
            self.total_pushed += 1
        except queue.Full:
            print(f"⚠️ Event queue full, dropping event: {event}")
    
    def poll(self, timeout: float = 0.0) -> List[Event]:
        """
        Poll for events. Returns all available events (up to a limit).
        
        Args:
            timeout: How long to wait for first event (seconds). 0 = non-blocking.
        
        Returns:
            List of events (may be empty if no events available).
        """
        events = []
        
        # Wait for first event with timeout
        try:
            event = self.queue.get(timeout=timeout)
            events.append(event)
            self.total_popped += 1
        except queue.Empty:
            return events
        
        # Drain any additional events (non-blocking)
        while not self.queue.empty() and len(events) < 100:
            try:
                event = self.queue.get_nowait()
                events.append(event)
                self.total_popped += 1
            except queue.Empty:
                break
        
        return events
    
    def size(self) -> int:
        """Current queue size."""
        return self.queue.qsize()
    
    def clear(self):
        """Clear all events."""
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
    
    def __repr__(self) -> str:
        return (
            f"EventQueue(size={self.size()}, "
            f"pushed={self.total_pushed}, "
            f"popped={self.total_popped})"
        )
