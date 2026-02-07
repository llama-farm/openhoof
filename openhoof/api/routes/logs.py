"""SSE endpoint for real-time agent logs."""

import asyncio
import json
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from ..dependencies import get_manager
from ...core.events import event_bus, Event

router = APIRouter()


async def event_generator(agent_id: Optional[str] = None):
    """Generate SSE events from the event bus."""
    queue: asyncio.Queue[Event] = asyncio.Queue()
    
    async def on_event(event: Event):
        # Filter by agent_id if specified
        if agent_id:
            event_agent = event.data.get("agent_id")
            if event_agent and event_agent != agent_id:
                return
        await queue.put(event)
    
    # Subscribe to all events
    event_bus.subscribe("*", on_event)
    
    try:
        # Send initial connection event
        yield f"data: {json.dumps({'type': 'connected', 'agent_id': agent_id})}\n\n"
        
        while True:
            try:
                # Wait for events with timeout (for heartbeat)
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {event.to_json()}\n\n"
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                yield f": heartbeat\n\n"
    finally:
        event_bus.unsubscribe("*", on_event)


@router.get("/logs/stream")
async def stream_logs(agent_id: Optional[str] = Query(None, description="Filter by agent ID")):
    """Stream real-time agent logs via Server-Sent Events."""
    return StreamingResponse(
        event_generator(agent_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/logs/recent")
async def get_recent_logs(
    limit: int = Query(100, description="Number of events to return"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
):
    """Get recent log events."""
    events = event_bus.get_recent_events(limit=limit, agent_id=agent_id)
    return [
        {
            "type": event.type,
            "data": event.data,
            "timestamp": event.timestamp,
            "event_id": event.event_id,
        }
        for event in events
    ]
