"""Hot state — structured in-memory state for autonomous agents."""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class HotStateFieldConfig:
    """Configuration for a hot state field (mirrors lifecycle.HotStateFieldConfig)."""
    type: str = "object"
    ttl: Optional[int] = None
    refresh_tool: Optional[str] = None
    max_items: Optional[int] = None


@dataclass
class HotStateField:
    """A single field in the hot state store."""
    config: HotStateFieldConfig
    value: Any = None
    updated_at: Optional[float] = None  # time.time() timestamp


@dataclass
class Notification:
    """A high-priority alert pushed by a sensor."""
    name: str
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class HotState:
    """Structured in-memory state with TTL tracking and notification queue."""

    def __init__(self, field_configs: Dict[str, HotStateFieldConfig]):
        self._fields: Dict[str, HotStateField] = {}
        for name, config in field_configs.items():
            self._fields[name] = HotStateField(config=config)
        self._notifications: List[Notification] = []

    def set(self, field_name: str, value: Any) -> bool:
        """Update a field's value and timestamp. Returns False if field not in schema."""
        f = self._fields.get(field_name)
        if f is None:
            logger.warning(f"Hot state field not in schema: {field_name}")
            return False

        # Enforce max_items on arrays
        if f.config.type == "array" and f.config.max_items and isinstance(value, list):
            if len(value) > f.config.max_items:
                value = value[-f.config.max_items:]

        f.value = value
        f.updated_at = time.time()
        return True

    def append(self, field_name: str, item: Any) -> bool:
        """Append an item to an array field, enforcing max_items."""
        f = self._fields.get(field_name)
        if f is None:
            logger.warning(f"Hot state field not in schema: {field_name}")
            return False
        if f.config.type != "array":
            logger.warning(f"Cannot append to non-array field: {field_name}")
            return False

        if f.value is None:
            f.value = []

        f.value.append(item)

        # Enforce max_items
        if f.config.max_items and len(f.value) > f.config.max_items:
            f.value = f.value[-f.config.max_items:]

        f.updated_at = time.time()
        return True

    def get(self, field_name: str) -> Any:
        """Get a field's current value. Returns None if not set or not in schema."""
        f = self._fields.get(field_name)
        if f is None:
            return None
        return f.value

    def is_stale(self, field_name: str) -> bool:
        """Check if a field is past its TTL."""
        f = self._fields.get(field_name)
        if f is None:
            return False
        if f.config.ttl is None:
            return False
        if f.updated_at is None:
            return True  # never been set = stale
        return (time.time() - f.updated_at) > f.config.ttl

    def get_stale_fields(self) -> List[str]:
        """Get names of all stale fields."""
        return [name for name in self._fields if self.is_stale(name)]

    def get_refreshable_stale_fields(self) -> List[Tuple[str, str]]:
        """Get stale fields that have a refresh_tool. Returns [(field_name, tool_name)]."""
        result = []
        for name, f in self._fields.items():
            if self.is_stale(name) and f.config.refresh_tool:
                result.append((name, f.config.refresh_tool))
        return result

    def render(self) -> str:
        """Serialize hot state to a structured text block for LLM context injection."""
        if not self._fields:
            return ""

        lines = ["## Hot State", ""]
        now = time.time()

        for name, f in self._fields.items():
            if f.value is None:
                lines.append(f"**{name}**: (not yet loaded)")
            else:
                # Format value
                if isinstance(f.value, (dict, list)):
                    try:
                        val_str = json.dumps(f.value, default=str)
                    except (TypeError, ValueError):
                        val_str = str(f.value)
                else:
                    val_str = str(f.value)

                # Add staleness marker
                if f.config.ttl and f.updated_at:
                    age = now - f.updated_at
                    if age > f.config.ttl:
                        if age < 60:
                            age_str = f"{int(age)}s ago"
                        elif age < 3600:
                            age_str = f"{int(age / 60)}m ago"
                        else:
                            age_str = f"{int(age / 3600)}h ago"
                        lines.append(f"**{name}**: {val_str} (stale: {age_str})")
                    else:
                        lines.append(f"**{name}**: {val_str}")
                else:
                    lines.append(f"**{name}**: {val_str}")

        return "\n".join(lines)

    def push_notification(self, name: str, data: Dict[str, Any]) -> None:
        """Push a high-priority notification to the queue."""
        self._notifications.append(Notification(name=name, data=data))

    def pop_notifications(self) -> List[Notification]:
        """Pop all pending notifications, clearing the queue."""
        notifications = list(self._notifications)
        self._notifications.clear()
        return notifications

    def has_notifications(self) -> bool:
        """Check if there are pending notifications."""
        return len(self._notifications) > 0

    def diff_since(self, timestamp: float) -> Dict[str, Any]:
        """Return a summary of fields that changed since the given timestamp."""
        changed = {}
        for name, f in self._fields.items():
            if f.updated_at is not None and f.updated_at > timestamp:
                changed[name] = {
                    "value": f.value,
                    "updated_at": f.updated_at,
                }
        return changed

    def snapshot_time(self) -> float:
        """Return current time for use with diff_since later."""
        return time.time()
