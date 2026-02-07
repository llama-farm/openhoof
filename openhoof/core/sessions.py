"""Session management for agents."""

import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
import uuid
import logging

logger = logging.getLogger(__name__)


@dataclass
class SessionEntry:
    """Persistent session state."""
    session_id: str
    session_key: str
    updated_at: float  # Unix timestamp
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    
    # Agent context
    agent_id: Optional[str] = None
    workspace_dir: Optional[str] = None
    
    # Model configuration
    model_override: Optional[str] = None
    thinking_level: Optional[str] = None
    
    # Token tracking
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    
    # Heartbeat tracking
    last_heartbeat_at: Optional[float] = None
    last_heartbeat_text: Optional[str] = None
    
    # Sub-agent tracking
    spawned_by: Optional[str] = None  # Parent session key
    
    # Status
    status: str = "active"  # active, paused, completed, failed
    
    # Custom metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


class SessionStore:
    """Manages persistent session storage."""
    
    def __init__(self, store_path: Path):
        self.store_path = store_path
        self._cache: Dict[str, SessionEntry] = {}
        self._loaded = False
    
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text())
                for key, entry_dict in data.items():
                    self._cache[key] = SessionEntry(**entry_dict)
                logger.info(f"Loaded {len(self._cache)} sessions from {self.store_path}")
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Error loading sessions: {e}")
        self._loaded = True
    
    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {key: asdict(entry) for key, entry in self._cache.items()}
        self.store_path.write_text(json.dumps(data, indent=2))
    
    def get(self, session_key: str) -> Optional[SessionEntry]:
        """Get a session by key."""
        self._ensure_loaded()
        return self._cache.get(session_key)
    
    def get_or_create(
        self,
        session_key: str,
        agent_id: Optional[str] = None,
        **kwargs: Any
    ) -> SessionEntry:
        """Get existing session or create new one."""
        self._ensure_loaded()
        
        if session_key not in self._cache:
            now = datetime.now().timestamp()
            self._cache[session_key] = SessionEntry(
                session_id=str(uuid.uuid4()),
                session_key=session_key,
                created_at=now,
                updated_at=now,
                agent_id=agent_id,
                **kwargs
            )
            self._save()
            logger.info(f"Created new session: {session_key}")
        
        return self._cache[session_key]
    
    def update(self, session_key: str, **updates: Any) -> Optional[SessionEntry]:
        """Update a session's fields."""
        self._ensure_loaded()
        
        entry = self._cache.get(session_key)
        if entry is None:
            return None
        
        for key, value in updates.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
        
        entry.updated_at = datetime.now().timestamp()
        self._save()
        return entry
    
    def list_sessions(
        self,
        agent_id: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[SessionEntry]:
        """List sessions, optionally filtered."""
        self._ensure_loaded()
        
        sessions = list(self._cache.values())
        
        if agent_id:
            sessions = [s for s in sessions if s.agent_id == agent_id]
        
        if status:
            sessions = [s for s in sessions if s.status == status]
        
        return sorted(sessions, key=lambda s: s.updated_at, reverse=True)
    
    def delete(self, session_key: str) -> bool:
        """Delete a session."""
        self._ensure_loaded()
        
        if session_key in self._cache:
            del self._cache[session_key]
            self._save()
            logger.info(f"Deleted session: {session_key}")
            return True
        return False
    
    def cleanup_old(self, max_age_hours: int = 24 * 7) -> int:
        """Clean up old completed sessions."""
        self._ensure_loaded()
        
        cutoff = datetime.now().timestamp() - (max_age_hours * 3600)
        to_remove = [
            key for key, entry in self._cache.items()
            if entry.status in ("completed", "failed") and entry.updated_at < cutoff
        ]
        
        for key in to_remove:
            del self._cache[key]
        
        if to_remove:
            self._save()
            logger.info(f"Cleaned up {len(to_remove)} old sessions")
        
        return len(to_remove)
