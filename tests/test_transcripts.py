"""Tests for transcript management."""

import pytest
from datetime import datetime

from openhoof.core.transcripts import TranscriptStore, Transcript, Message


def test_append_message(transcript_store):
    """Test appending messages to a transcript."""
    transcript = transcript_store.append_message(
        session_id="session-1",
        agent_id="test-agent",
        message=Message(role="user", content="Hello")
    )
    
    assert len(transcript.messages) == 1
    assert transcript.messages[0].role == "user"
    assert transcript.messages[0].content == "Hello"


def test_load_transcript(transcript_store):
    """Test loading a transcript."""
    # Create transcript with messages
    transcript_store.append_message(
        session_id="session-2",
        agent_id="test-agent",
        message=Message(role="user", content="Test 1")
    )
    transcript_store.append_message(
        session_id="session-2",
        agent_id="test-agent",
        message=Message(role="assistant", content="Response 1")
    )
    
    # Load it
    transcript = transcript_store.load("session-2")
    
    assert transcript is not None
    assert len(transcript.messages) == 2


def test_get_messages_for_context(transcript_store):
    """Test getting messages for context window."""
    # Add many messages
    for i in range(60):
        transcript_store.append_message(
            session_id="session-3",
            agent_id="test-agent",
            message=Message(role="user" if i % 2 == 0 else "assistant", content=f"Message {i}")
        )
    
    # Get limited messages
    messages = transcript_store.get_messages_for_context("session-3", max_messages=10)
    
    # Should have last 10 messages
    assert len(messages) == 10


def test_compact_transcript(transcript_store):
    """Test transcript compaction."""
    # Add messages
    for i in range(20):
        transcript_store.append_message(
            session_id="session-4",
            agent_id="test-agent",
            message=Message(role="user", content=f"Message {i}")
        )
    
    # Compact
    transcript = transcript_store.compact(
        session_id="session-4",
        keep_last=5,
        summary="Previous conversation about various topics."
    )
    
    assert transcript is not None
    assert len(transcript.messages) == 5
    assert transcript.summary is not None
    assert transcript.compaction_count == 1


def test_delete_transcript(transcript_store):
    """Test deleting a transcript."""
    transcript_store.append_message(
        session_id="session-5",
        agent_id="test-agent",
        message=Message(role="user", content="Delete me")
    )
    
    result = transcript_store.delete("session-5")
    
    assert result is True
    assert transcript_store.load("session-5") is None


def test_message_to_openai_format():
    """Test converting message to OpenAI format."""
    msg = Message(role="user", content="Hello world")
    openai_format = msg.to_openai_format()
    
    assert openai_format["role"] == "user"
    assert openai_format["content"] == "Hello world"


def test_tool_message_format():
    """Test tool message format."""
    msg = Message(
        role="tool",
        content="Tool result",
        tool_call_id="call_123"
    )
    openai_format = msg.to_openai_format()
    
    assert openai_format["role"] == "tool"
    assert openai_format["tool_call_id"] == "call_123"
