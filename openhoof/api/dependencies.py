"""API dependencies."""

from typing import Optional
from ..agents import AgentManager

# Global manager instance
_manager: Optional[AgentManager] = None

def get_manager() -> AgentManager:
    """Get the global agent manager."""
    global _manager
    if _manager is None:
        raise RuntimeError("AgentManager not initialized")
    return _manager

def set_manager(manager: AgentManager) -> None:
    """Set the global agent manager."""
    global _manager
    _manager = manager
