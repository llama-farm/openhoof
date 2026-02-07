"""Tests for session management."""

import pytest

from openhoof.core.sessions import SessionStore, SessionEntry


def test_create_session(session_store):
    """Test creating a new session."""
    session = session_store.get_or_create("test:session:1", agent_id="test-agent")
    
    assert session.session_key == "test:session:1"
    assert session.agent_id == "test-agent"
    assert session.status == "active"


def test_get_existing_session(session_store):
    """Test getting an existing session."""
    # Create first
    session1 = session_store.get_or_create("test:session:2", agent_id="test-agent")
    
    # Get again
    session2 = session_store.get_or_create("test:session:2")
    
    assert session1.session_id == session2.session_id


def test_update_session(session_store):
    """Test updating session fields."""
    session = session_store.get_or_create("test:session:3", agent_id="test-agent")
    
    session_store.update("test:session:3", total_tokens=100, status="completed")
    
    updated = session_store.get("test:session:3")
    assert updated.total_tokens == 100
    assert updated.status == "completed"


def test_list_sessions(session_store):
    """Test listing sessions."""
    session_store.get_or_create("test:session:a", agent_id="agent-1")
    session_store.get_or_create("test:session:b", agent_id="agent-1")
    session_store.get_or_create("test:session:c", agent_id="agent-2")
    
    # List all
    all_sessions = session_store.list_sessions()
    assert len(all_sessions) == 3
    
    # Filter by agent
    agent1_sessions = session_store.list_sessions(agent_id="agent-1")
    assert len(agent1_sessions) == 2


def test_delete_session(session_store):
    """Test deleting a session."""
    session_store.get_or_create("test:session:delete", agent_id="test-agent")
    
    result = session_store.delete("test:session:delete")
    
    assert result is True
    assert session_store.get("test:session:delete") is None


def test_session_persistence(temp_dir):
    """Test that sessions persist across store instances."""
    store_path = temp_dir / "sessions.json"
    
    # Create session in first store
    store1 = SessionStore(store_path)
    store1.get_or_create("persist:test", agent_id="agent")
    
    # Load in new store instance
    store2 = SessionStore(store_path)
    session = store2.get("persist:test")
    
    assert session is not None
    assert session.agent_id == "agent"
