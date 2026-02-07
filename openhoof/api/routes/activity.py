"""Activity feed endpoints."""

from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter

from ...core.events import event_bus, Event

router = APIRouter()


class ActivityItem(BaseModel):
    """Activity feed item."""
    type: str
    timestamp: str
    agent_id: Optional[str] = None
    data: dict


@router.get("")
async def get_activity(
    limit: int = 100,
    agent_id: Optional[str] = None,
    event_type: Optional[str] = None,
) -> List[ActivityItem]:
    """Get recent activity."""
    event_types = [event_type] if event_type else None
    events = event_bus.get_recent_events(
        limit=limit,
        event_types=event_types,
        agent_id=agent_id,
    )
    
    return [
        ActivityItem(
            type=e.type,
            timestamp=e.timestamp,
            agent_id=e.data.get("agent_id"),
            data=e.data,
        )
        for e in events
    ]
