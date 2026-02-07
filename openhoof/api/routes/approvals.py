"""Approval queue endpoints."""

from typing import Optional, List
from datetime import datetime
from dataclasses import dataclass, field, asdict
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException
import uuid

router = APIRouter()

# In-memory approval store (could be persisted)
_approvals: dict = {}


@dataclass
class Approval:
    """Pending approval item."""
    approval_id: str
    agent_id: str
    session_key: str
    action: str
    description: str
    data: dict
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    status: str = "pending"  # pending, approved, rejected
    resolved_at: Optional[float] = None
    resolved_by: Optional[str] = None


class ApprovalResponse(BaseModel):
    """Approval response model."""
    approval_id: str
    agent_id: str
    action: str
    description: str
    data: dict
    created_at: float
    status: str


class ApprovalResolve(BaseModel):
    """Request to resolve an approval."""
    approved: bool
    resolved_by: Optional[str] = None


@router.get("")
async def list_approvals(
    status: str = "pending",
    agent_id: Optional[str] = None,
) -> List[ApprovalResponse]:
    """List pending approvals."""
    approvals = list(_approvals.values())
    
    if status:
        approvals = [a for a in approvals if a.status == status]
    
    if agent_id:
        approvals = [a for a in approvals if a.agent_id == agent_id]
    
    return [
        ApprovalResponse(
            approval_id=a.approval_id,
            agent_id=a.agent_id,
            action=a.action,
            description=a.description,
            data=a.data,
            created_at=a.created_at,
            status=a.status,
        )
        for a in sorted(approvals, key=lambda x: x.created_at, reverse=True)
    ]


@router.post("/{approval_id}/resolve")
async def resolve_approval(approval_id: str, body: ApprovalResolve):
    """Approve or reject a pending action."""
    if approval_id not in _approvals:
        raise HTTPException(status_code=404, detail=f"Approval not found: {approval_id}")
    
    approval = _approvals[approval_id]
    if approval.status != "pending":
        raise HTTPException(status_code=400, detail=f"Approval already resolved: {approval.status}")
    
    approval.status = "approved" if body.approved else "rejected"
    approval.resolved_at = datetime.now().timestamp()
    approval.resolved_by = body.resolved_by
    
    # TODO: Execute the action if approved
    
    return {
        "approval_id": approval_id,
        "status": approval.status,
        "resolved_at": approval.resolved_at,
    }


# Internal function to add approvals
async def add_approval(
    agent_id: str,
    session_key: str,
    action: str,
    description: str,
    data: dict,
) -> str:
    """Add a new pending approval."""
    approval_id = str(uuid.uuid4())[:8]
    
    approval = Approval(
        approval_id=approval_id,
        agent_id=agent_id,
        session_key=session_key,
        action=action,
        description=description,
        data=data,
    )
    
    _approvals[approval_id] = approval
    
    # Emit event
    from ...core.events import event_bus, EVENT_APPROVAL_REQUESTED
    await event_bus.emit(EVENT_APPROVAL_REQUESTED, {
        "approval_id": approval_id,
        "agent_id": agent_id,
        "action": action,
        "description": description,
    })
    
    return approval_id
