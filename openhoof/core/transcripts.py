"""Conversation transcript persistence."""

import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Literal, Any, Dict
import logging

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A single message in a conversation."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    
    # For tool messages
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    
    # For assistant messages with tool calls
    tool_calls: Optional[List[Dict[str, Any]]] = None
    
    # Thinking content (for models that support it)
    thinking: Optional[str] = None
    
    # Metadata
    metadata: Optional[Dict[str, Any]] = None
    
    def to_openai_format(self) -> Dict[str, Any]:
        """Convert to OpenAI message format."""
        msg: Dict[str, Any] = {
            "role": self.role,
            "content": self.content
        }
        
        if self.role == "tool" and self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        
        if self.role == "assistant" and self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        
        return msg


@dataclass
class Transcript:
    """A conversation transcript."""
    session_id: str
    agent_id: str
    messages: List[Message] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    updated_at: float = field(default_factory=lambda: datetime.now().timestamp())
    compaction_count: int = 0
    summary: Optional[str] = None  # Summary of compacted messages


class TranscriptStore:
    """Manages conversation transcripts on disk."""
    
    def __init__(self, transcripts_dir: Path):
        self.transcripts_dir = transcripts_dir
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
    
    def _path_for(self, session_id: str) -> Path:
        return self.transcripts_dir / f"{session_id}.json"
    
    def load(self, session_id: str) -> Optional[Transcript]:
        """Load a transcript from disk."""
        path = self._path_for(session_id)
        if not path.exists():
            return None
        
        try:
            data = json.loads(path.read_text())
            messages = [Message(**m) for m in data.get("messages", [])]
            return Transcript(
                session_id=data["session_id"],
                agent_id=data["agent_id"],
                messages=messages,
                created_at=data["created_at"],
                updated_at=data["updated_at"],
                compaction_count=data.get("compaction_count", 0),
                summary=data.get("summary"),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Error loading transcript {session_id}: {e}")
            return None
    
    def save(self, transcript: Transcript) -> None:
        """Save a transcript to disk."""
        path = self._path_for(transcript.session_id)
        transcript.updated_at = datetime.now().timestamp()
        
        data = {
            "session_id": transcript.session_id,
            "agent_id": transcript.agent_id,
            "messages": [asdict(m) for m in transcript.messages],
            "created_at": transcript.created_at,
            "updated_at": transcript.updated_at,
            "compaction_count": transcript.compaction_count,
            "summary": transcript.summary,
        }
        
        path.write_text(json.dumps(data, indent=2))
    
    def get_or_create(self, session_id: str, agent_id: str) -> Transcript:
        """Get existing transcript or create new one."""
        transcript = self.load(session_id)
        if transcript is None:
            now = datetime.now().timestamp()
            transcript = Transcript(
                session_id=session_id,
                agent_id=agent_id,
                created_at=now,
                updated_at=now,
            )
        return transcript
    
    def append_message(
        self,
        session_id: str,
        agent_id: str,
        message: Message
    ) -> Transcript:
        """Append a message to a transcript."""
        transcript = self.get_or_create(session_id, agent_id)
        transcript.messages.append(message)
        self.save(transcript)
        return transcript
    
    def get_messages_for_context(
        self,
        session_id: str,
        max_messages: int = 50
    ) -> List[Message]:
        """Get recent messages for context window."""
        transcript = self.load(session_id)
        if transcript is None:
            return []
        
        # Get system messages and recent conversation
        system_msgs = [m for m in transcript.messages if m.role == "system"]
        other_msgs = [m for m in transcript.messages if m.role != "system"]
        
        # Take last N non-system messages
        recent = other_msgs[-max_messages:] if len(other_msgs) > max_messages else other_msgs
        
        # Prepend summary if we have one
        result = system_msgs.copy()
        if transcript.summary:
            result.append(Message(
                role="system",
                content=f"[Previous conversation summary]\n{transcript.summary}",
                metadata={"compaction": True}
            ))
        result.extend(recent)
        
        return result
    
    def compact(
        self,
        session_id: str,
        keep_last: int = 10,
        summary: Optional[str] = None
    ) -> Optional[Transcript]:
        """Compact transcript by summarizing old messages."""
        transcript = self.load(session_id)
        if transcript is None or len(transcript.messages) <= keep_last:
            return transcript
        
        # Keep system messages and recent messages
        system_msgs = [m for m in transcript.messages if m.role == "system"]
        other_msgs = [m for m in transcript.messages if m.role != "system"]
        recent_msgs = other_msgs[-keep_last:]
        
        # Create compacted transcript
        transcript.messages = system_msgs + recent_msgs
        transcript.summary = summary
        transcript.compaction_count += 1
        
        self.save(transcript)
        logger.info(f"Compacted transcript {session_id}, kept {len(transcript.messages)} messages")
        
        return transcript
    
    def delete(self, session_id: str) -> bool:
        """Delete a transcript."""
        path = self._path_for(session_id)
        if path.exists():
            path.unlink()
            return True
        return False
