"""Tests for event bus."""

import pytest
import asyncio

from openhoof.core.events import EventBus, Event


@pytest.mark.asyncio
async def test_emit_event(event_bus):
    """Test emitting an event."""
    events_received = []
    
    async def handler(event: Event):
        events_received.append(event)
    
    event_bus.subscribe("test:event", handler)
    
    await event_bus.emit("test:event", {"message": "hello"})
    
    assert len(events_received) == 1
    assert events_received[0].type == "test:event"
    assert events_received[0].data["message"] == "hello"


@pytest.mark.asyncio
async def test_wildcard_subscriber(event_bus):
    """Test wildcard subscription."""
    events_received = []
    
    async def handler(event: Event):
        events_received.append(event)
    
    event_bus.subscribe("*", handler)
    
    await event_bus.emit("event:one", {"n": 1})
    await event_bus.emit("event:two", {"n": 2})
    
    assert len(events_received) == 2


@pytest.mark.asyncio
async def test_get_recent_events(event_bus):
    """Test getting recent events."""
    for i in range(5):
        await event_bus.emit("test:event", {"i": i})
    
    recent = event_bus.get_recent_events(limit=3)
    
    assert len(recent) == 3


@pytest.mark.asyncio
async def test_filter_events_by_type(event_bus):
    """Test filtering events by type."""
    await event_bus.emit("type:a", {"value": 1})
    await event_bus.emit("type:b", {"value": 2})
    await event_bus.emit("type:a", {"value": 3})
    
    type_a_events = event_bus.get_recent_events(event_types=["type:a"])
    
    assert len(type_a_events) == 2


@pytest.mark.asyncio
async def test_filter_events_by_agent(event_bus):
    """Test filtering events by agent_id."""
    await event_bus.emit("test", {"agent_id": "agent-1"})
    await event_bus.emit("test", {"agent_id": "agent-2"})
    await event_bus.emit("test", {"agent_id": "agent-1"})
    
    agent1_events = event_bus.get_recent_events(agent_id="agent-1")
    
    assert len(agent1_events) == 2


def test_event_to_json():
    """Test event JSON serialization."""
    event = Event(
        type="test:event",
        data={"key": "value"},
    )
    
    json_str = event.to_json()
    
    assert "test:event" in json_str
    assert "key" in json_str
    assert "value" in json_str


@pytest.mark.asyncio
async def test_unsubscribe(event_bus):
    """Test unsubscribing from events."""
    events_received = []
    
    async def handler(event: Event):
        events_received.append(event)
    
    event_bus.subscribe("test:event", handler)
    await event_bus.emit("test:event", {})
    
    event_bus.unsubscribe("test:event", handler)
    await event_bus.emit("test:event", {})
    
    # Should only have received the first event
    assert len(events_received) == 1
