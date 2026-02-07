"""Chat endpoints for agent conversations."""

from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..dependencies import get_manager
from ...core.transcripts import Message

router = APIRouter()


class ChatRequest(BaseModel):
    """Chat request model."""
    message: str
    session_key: Optional[str] = None
    stream: bool = False


class ChatResponse(BaseModel):
    """Chat response model."""
    response: str
    session_key: str
    agent_id: str
    thinking: Optional[str] = None


class MessageResponse(BaseModel):
    """Message in transcript."""
    role: str
    content: str
    timestamp: float
    thinking: Optional[str] = None


class TranscriptResponse(BaseModel):
    """Transcript response model."""
    session_id: str
    agent_id: str
    messages: List[MessageResponse]


@router.post("/{agent_id}/chat")
async def chat_with_agent(agent_id: str, request: ChatRequest) -> ChatResponse:
    """Send a message to an agent."""
    manager = get_manager()
    
    try:
        response = await manager.chat(
            agent_id=agent_id,
            message=request.message,
            session_key=request.session_key,
        )
        
        session_key = request.session_key or f"agent:{agent_id}:main"
        
        return ChatResponse(
            response=response,
            session_key=session_key,
            agent_id=agent_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{agent_id}/sessions")
async def list_sessions(agent_id: str) -> List[dict]:
    """List sessions for an agent."""
    manager = get_manager()
    sessions = manager.session_store.list_sessions(agent_id=agent_id)
    
    return [
        {
            "session_id": s.session_id,
            "session_key": s.session_key,
            "status": s.status,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "total_tokens": s.total_tokens,
        }
        for s in sessions
    ]


@router.get("/{agent_id}/chat/{session_key:path}")
async def get_transcript(agent_id: str, session_key: str) -> TranscriptResponse:
    """Get conversation transcript for a session."""
    manager = get_manager()
    
    # Find session
    session = manager.session_store.get(session_key)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_key}")
    
    # Get transcript
    transcript = manager.transcript_store.load(session.session_id)
    if not transcript:
        return TranscriptResponse(
            session_id=session.session_id,
            agent_id=agent_id,
            messages=[]
        )
    
    return TranscriptResponse(
        session_id=session.session_id,
        agent_id=agent_id,
        messages=[
            MessageResponse(
                role=m.role,
                content=m.content,
                timestamp=m.timestamp,
                thinking=m.thinking,
            )
            for m in transcript.messages
        ]
    )


@router.delete("/{agent_id}/chat/{session_key:path}")
async def delete_session(agent_id: str, session_key: str):
    """Delete a session and its transcript."""
    manager = get_manager()
    
    session = manager.session_store.get(session_key)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_key}")
    
    # Delete transcript
    manager.transcript_store.delete(session.session_id)
    
    # Delete session
    manager.session_store.delete(session_key)
    
    return {"status": "deleted", "session_key": session_key}
