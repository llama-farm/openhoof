"""
Trigger API - Event-driven agent spawning.

External systems (HORIZON, Medical Wing, etc.) POST events here
to automatically spawn appropriate agents with full context.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, BackgroundTasks

from ...core.events import event_bus

router = APIRouter(prefix="/triggers", tags=["triggers"])


# ============================================================================
# Models
# ============================================================================

class TriggerEvent(BaseModel):
    """Incoming trigger event from external system."""
    
    # Source identification
    source: str = Field(..., description="Source system (horizon, medical-wing, etc.)")
    source_id: str = Field(default="", description="Source system instance ID")
    
    # Event classification
    event_type: str = Field(..., description="Type of event (anomaly, alert, request, etc.)")
    category: str = Field(default="general", description="Event category")
    severity: str = Field(default="info", description="Severity level (info, caution, warning, critical)")
    
    # Event data
    title: str = Field(..., description="Brief title")
    description: str = Field(default="", description="Detailed description")
    data: Dict[str, Any] = Field(default_factory=dict, description="Event-specific data")
    
    # Agent routing
    target_agent: Optional[str] = Field(None, description="Specific agent to spawn (auto-routes if not specified)")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context for agent")


class TriggerResponse(BaseModel):
    """Response to trigger request."""
    trigger_id: str
    status: str  # "accepted", "queued", "spawned", "error"
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    message: str = ""


class TriggerRule(BaseModel):
    """Rule for automatic agent routing."""
    name: str
    source: str  # Source system pattern (e.g., "horizon", "*")
    event_type: str  # Event type pattern
    category: str = "*"  # Category pattern
    min_severity: str = "info"  # Minimum severity to trigger
    agent_id: str  # Agent to spawn
    enabled: bool = True


# ============================================================================
# Trigger Engine
# ============================================================================

class TriggerEngine:
    """Processes incoming triggers and spawns appropriate agents."""
    
    SEVERITY_ORDER = {"info": 0, "caution": 1, "warning": 2, "critical": 3}
    
    def __init__(self):
        self.rules: List[TriggerRule] = []
        self.trigger_history: List[Dict[str, Any]] = []
        self._trigger_counter = 0
        self._load_default_rules()
    
    def _load_default_rules(self):
        """Load default routing rules."""
        self.rules = [
            # HORIZON rules
            TriggerRule(
                name="horizon-fuel-anomaly",
                source="horizon",
                event_type="anomaly",
                category="fuel",
                min_severity="caution",
                agent_id="fuel-analyst"
            ),
            TriggerRule(
                name="horizon-intel-alert",
                source="horizon",
                event_type="anomaly",
                category="threat",
                min_severity="warning",
                agent_id="intel-analyst"
            ),
            TriggerRule(
                name="horizon-mx-issue",
                source="horizon",
                event_type="anomaly",
                category="equipment",
                min_severity="warning",
                agent_id="mx-specialist"
            ),
            TriggerRule(
                name="horizon-critical-orchestrator",
                source="horizon",
                event_type="anomaly",
                category="*",
                min_severity="critical",
                agent_id="horizon-orchestrator"
            ),
            # Medical Wing rules
            TriggerRule(
                name="medical-supply-anomaly",
                source="medical-wing",
                event_type="anomaly",
                category="supply",
                min_severity="warning",
                agent_id="supply-analyst"
            ),
            TriggerRule(
                name="medical-equipment-failure",
                source="medical-wing",
                event_type="anomaly",
                category="equipment",
                min_severity="warning",
                agent_id="equipment-analyst"
            ),
            # Catch-all for critical events
            TriggerRule(
                name="critical-catch-all",
                source="*",
                event_type="*",
                category="*",
                min_severity="critical",
                agent_id="horizon-orchestrator"  # Default orchestrator
            ),
        ]
    
    def _generate_trigger_id(self) -> str:
        self._trigger_counter += 1
        return f"TRG-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{self._trigger_counter:04d}"
    
    def _severity_meets_threshold(self, event_severity: str, min_severity: str) -> bool:
        """Check if event severity meets or exceeds minimum."""
        event_level = self.SEVERITY_ORDER.get(event_severity.lower(), 0)
        min_level = self.SEVERITY_ORDER.get(min_severity.lower(), 0)
        return event_level >= min_level
    
    def _matches_pattern(self, value: str, pattern: str) -> bool:
        """Simple pattern matching (* = wildcard)."""
        if pattern == "*":
            return True
        return value.lower() == pattern.lower()
    
    def find_matching_agent(self, event: TriggerEvent) -> Optional[str]:
        """Find the best matching agent for an event."""
        # If explicit target specified, use it
        if event.target_agent:
            return event.target_agent
        
        # Find best matching rule (most specific first)
        best_match: Optional[TriggerRule] = None
        best_score = -1
        
        for rule in self.rules:
            if not rule.enabled:
                continue
            
            # Check all conditions
            if not self._matches_pattern(event.source, rule.source):
                continue
            if not self._matches_pattern(event.event_type, rule.event_type):
                continue
            if not self._matches_pattern(event.category, rule.category):
                continue
            if not self._severity_meets_threshold(event.severity, rule.min_severity):
                continue
            
            # Calculate specificity score (non-wildcard matches score higher)
            score = 0
            if rule.source != "*":
                score += 10
            if rule.event_type != "*":
                score += 5
            if rule.category != "*":
                score += 3
            score += self.SEVERITY_ORDER.get(rule.min_severity, 0)
            
            if score > best_score:
                best_score = score
                best_match = rule
        
        return best_match.agent_id if best_match else None
    
    async def process_trigger(
        self,
        event: TriggerEvent,
        manager: Any = None
    ) -> TriggerResponse:
        """Process a trigger event and spawn appropriate agent."""
        import uuid
        
        trigger_id = self._generate_trigger_id()
        
        # Find target agent
        agent_id = self.find_matching_agent(event)
        
        if not agent_id:
            # Log but don't fail - might be intentional
            self.trigger_history.append({
                "trigger_id": trigger_id,
                "event": event.model_dump(),
                "status": "no_match",
                "timestamp": datetime.utcnow().isoformat()
            })
            return TriggerResponse(
                trigger_id=trigger_id,
                status="no_match",
                message=f"No matching agent rule for event from {event.source}"
            )
        
        # Check if agent exists via manager
        if manager:
            agents = await manager.list_agents() if asyncio.iscoroutinefunction(manager.list_agents) else manager.list_agents()
            agent_ids = [a.get("agent_id", a.get("id", a.get("name"))) for a in agents]
            if agent_id not in agent_ids:
                return TriggerResponse(
                    trigger_id=trigger_id,
                    status="error",
                    message=f"Agent '{agent_id}' not found (available: {agent_ids[:5]}...)"
                )
        
        # Build initial message with context
        initial_message = self._build_agent_message(event, trigger_id)
        
        # Generate session ID (actual session creation would go here)
        session_id = str(uuid.uuid4())
        
        # Emit event
        await event_bus.emit(
            "trigger:spawned",
            {
                "trigger_id": trigger_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "source": event.source,
                "event_type": event.event_type,
                "category": event.category,
                "severity": event.severity,
                "initial_message": initial_message
            }
        )
        
        # Store in history
        self.trigger_history.append({
            "trigger_id": trigger_id,
            "event": event.model_dump(),
            "agent_id": agent_id,
            "session_id": session_id,
            "status": "spawned",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return TriggerResponse(
            trigger_id=trigger_id,
            status="spawned",
            agent_id=agent_id,
            session_id=session_id,
            message=f"Agent '{agent_id}' spawned to handle {event.event_type}"
        )
    
    def _build_agent_message(self, event: TriggerEvent, trigger_id: str) -> str:
        """Build the initial message for the spawned agent."""
        lines = [
            f"## TRIGGER: {event.title}",
            f"**Trigger ID:** {trigger_id}",
            f"**Source:** {event.source}",
            f"**Type:** {event.event_type}",
            f"**Category:** {event.category}",
            f"**Severity:** {event.severity.upper()}",
            "",
            "### Description",
            event.description or "(No description provided)",
            "",
        ]
        
        if event.data:
            lines.extend([
                "### Source Data",
                "```json",
                str(event.data),
                "```",
                "",
            ])
        
        if event.context:
            lines.extend([
                "### Additional Context",
                "```json", 
                str(event.context),
                "```",
                "",
            ])
        
        lines.extend([
            "---",
            "**Analyze this event and provide recommendations.**",
            "If this requires coordination with other specialists, use spawn_agent.",
        ])
        
        return "\n".join(lines)
    
    def get_rules(self) -> List[TriggerRule]:
        return self.rules
    
    def add_rule(self, rule: TriggerRule):
        self.rules.append(rule)
    
    def remove_rule(self, name: str) -> bool:
        original_len = len(self.rules)
        self.rules = [r for r in self.rules if r.name != name]
        return len(self.rules) < original_len
    
    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.trigger_history[-limit:]


# Singleton
_trigger_engine: Optional[TriggerEngine] = None

def get_trigger_engine() -> TriggerEngine:
    global _trigger_engine
    if _trigger_engine is None:
        _trigger_engine = TriggerEngine()
    return _trigger_engine


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("", response_model=TriggerResponse)
async def create_trigger(
    event: TriggerEvent,
    background_tasks: BackgroundTasks
):
    """
    Receive a trigger event from an external system.
    
    The trigger engine will:
    1. Match the event to appropriate agent rules
    2. Spawn the agent with full event context
    3. Return session info for tracking
    
    Example from HORIZON:
    ```
    POST /api/triggers
    {
        "source": "horizon",
        "event_type": "anomaly",
        "category": "fuel",
        "severity": "warning",
        "title": "Fuel Burn Rate Deviation",
        "description": "Current burn rate is 15% above planned",
        "data": {
            "burn_ratio": 1.15,
            "current_fuel_lbs": 145000,
            "hours_remaining": 4.2
        }
    }
    ```
    """
    from ..dependencies import get_manager
    
    engine = get_trigger_engine()
    manager = get_manager()
    
    response = await engine.process_trigger(event, manager)
    return response


@router.get("/rules", response_model=List[TriggerRule])
async def list_rules():
    """List all trigger routing rules."""
    engine = get_trigger_engine()
    return engine.get_rules()


@router.post("/rules", response_model=TriggerRule)
async def add_rule(rule: TriggerRule):
    """Add a new trigger routing rule."""
    engine = get_trigger_engine()
    engine.add_rule(rule)
    return rule


@router.delete("/rules/{name}")
async def delete_rule(name: str):
    """Delete a trigger rule by name."""
    engine = get_trigger_engine()
    if engine.remove_rule(name):
        return {"status": "deleted", "name": name}
    raise HTTPException(status_code=404, detail=f"Rule '{name}' not found")


@router.get("/history")
async def get_trigger_history(limit: int = 50):
    """Get recent trigger history."""
    engine = get_trigger_engine()
    return engine.get_history(limit)


@router.post("/test")
async def test_trigger(event: TriggerEvent):
    """
    Test trigger routing without actually spawning an agent.
    Returns which agent would be spawned.
    """
    engine = get_trigger_engine()
    agent_id = engine.find_matching_agent(event)
    
    return {
        "event": event.model_dump(),
        "would_spawn": agent_id,
        "matching_rules": [
            r.model_dump() for r in engine.get_rules()
            if engine._matches_pattern(event.source, r.source)
            and engine._matches_pattern(event.event_type, r.event_type)
            and engine._matches_pattern(event.category, r.category)
            and engine._severity_meets_threshold(event.severity, r.min_severity)
        ]
    }
