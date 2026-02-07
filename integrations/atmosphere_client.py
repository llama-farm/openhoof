"""
Atmosphere Agents Integration Client

Drop-in client for integrating Atmosphere Agents into external applications.
HORIZON, Medical Wing, or any system can use this to trigger agents on events.

Usage:
    from atmosphere_client import AtmosphereClient
    
    # Initialize once
    client = AtmosphereClient("http://localhost:18765")
    
    # Fire trigger when anomaly detected
    response = await client.trigger(
        source="horizon",
        event_type="anomaly",
        category="fuel",
        severity="warning",
        title="Fuel Burn Rate Deviation",
        description="Current burn rate is 15% above planned",
        data={"burn_ratio": 1.15, "current_fuel_lbs": 145000}
    )
    
    # Track the spawned agent
    print(f"Agent {response['agent_id']} spawned: {response['session_id']}")
"""

import asyncio
import json
from typing import Any, Dict, Optional, Callable, Awaitable
from dataclasses import dataclass
import httpx


@dataclass
class TriggerResponse:
    """Response from a trigger request."""
    trigger_id: str
    status: str  # "accepted", "queued", "spawned", "error", "no_match"
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    message: str = ""
    
    @classmethod
    def from_dict(cls, data: dict) -> "TriggerResponse":
        return cls(
            trigger_id=data.get("trigger_id", ""),
            status=data.get("status", "error"),
            agent_id=data.get("agent_id"),
            session_id=data.get("session_id"),
            message=data.get("message", "")
        )


class AtmosphereClient:
    """
    Client for integrating with Atmosphere Agents.
    
    Provides async methods to:
    - Fire triggers (spawn agents on events)
    - Query agent status
    - Get session results
    - Manage routing rules
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:18765",
        timeout: float = 30.0,
        source_id: str = ""
    ):
        """
        Initialize client.
        
        Args:
            base_url: Atmosphere Agents API URL
            timeout: Request timeout in seconds
            source_id: Optional identifier for this client instance
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.source_id = source_id
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def health(self) -> Dict[str, Any]:
        """Check Atmosphere Agents health."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/api/health")
        response.raise_for_status()
        return response.json()
    
    async def trigger(
        self,
        source: str,
        event_type: str,
        title: str,
        category: str = "general",
        severity: str = "info",
        description: str = "",
        data: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        target_agent: Optional[str] = None
    ) -> TriggerResponse:
        """
        Fire a trigger event to spawn an agent.
        
        Args:
            source: Source system identifier (e.g., "horizon", "medical-wing")
            event_type: Type of event (e.g., "anomaly", "alert", "request")
            title: Brief title for the event
            category: Event category for routing (e.g., "fuel", "equipment")
            severity: Severity level ("info", "caution", "warning", "critical")
            description: Detailed description
            data: Event-specific data (anomaly details, etc.)
            context: Additional context for the agent
            target_agent: Explicitly route to this agent (overrides rules)
        
        Returns:
            TriggerResponse with trigger_id, spawned agent_id, session_id
        """
        client = await self._get_client()
        
        payload = {
            "source": source,
            "source_id": self.source_id,
            "event_type": event_type,
            "category": category,
            "severity": severity,
            "title": title,
            "description": description,
            "data": data or {},
            "context": context or {},
        }
        
        if target_agent:
            payload["target_agent"] = target_agent
        
        response = await client.post(
            f"{self.base_url}/api/triggers",
            json=payload
        )
        response.raise_for_status()
        return TriggerResponse.from_dict(response.json())
    
    async def test_trigger(
        self,
        source: str,
        event_type: str,
        category: str = "general",
        severity: str = "info"
    ) -> Dict[str, Any]:
        """
        Test trigger routing without spawning an agent.
        Returns which agent would be spawned.
        """
        client = await self._get_client()
        
        payload = {
            "source": source,
            "event_type": event_type,
            "category": category,
            "severity": severity,
            "title": "Test",
        }
        
        response = await client.post(
            f"{self.base_url}/api/triggers/test",
            json=payload
        )
        response.raise_for_status()
        return response.json()
    
    async def get_trigger_history(self, limit: int = 50) -> list:
        """Get recent trigger history."""
        client = await self._get_client()
        response = await client.get(
            f"{self.base_url}/api/triggers/history",
            params={"limit": limit}
        )
        response.raise_for_status()
        return response.json()
    
    async def get_session(self, agent_id: str, session_id: str) -> Dict[str, Any]:
        """Get session details including transcript."""
        client = await self._get_client()
        response = await client.get(
            f"{self.base_url}/api/agents/{agent_id}/sessions/{session_id}"
        )
        response.raise_for_status()
        return response.json()
    
    async def send_message(
        self,
        agent_id: str,
        session_id: str,
        message: str
    ) -> Dict[str, Any]:
        """Send a message to an active session."""
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/api/agents/{agent_id}/chat",
            json={
                "message": message,
                "session_id": session_id
            }
        )
        response.raise_for_status()
        return response.json()
    
    async def list_agents(self) -> list:
        """List all available agents."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/api/agents")
        response.raise_for_status()
        return response.json()


# ============================================================================
# Callback Adapter for HORIZON/Medical Wing
# ============================================================================

class AnomalyTriggerCallback:
    """
    Callback adapter for anomaly detection systems.
    
    Drop this into HORIZON's AnomalyEngine or Medical Wing's detector:
    
        from atmosphere_client import AnomalyTriggerCallback
        
        callback = AnomalyTriggerCallback(source="horizon")
        anomaly_engine.register_callback(callback)
    """
    
    def __init__(
        self,
        source: str,
        atmosphere_url: str = "http://localhost:18765",
        min_severity: str = "caution",
        async_fire: bool = True
    ):
        """
        Args:
            source: Source system name for routing
            atmosphere_url: Atmosphere Agents API URL
            min_severity: Minimum severity to trigger (filters noise)
            async_fire: If True, fire-and-forget (don't block on response)
        """
        self.source = source
        self.client = AtmosphereClient(atmosphere_url, source_id=source)
        self.min_severity = min_severity
        self.async_fire = async_fire
        self._severity_order = {"info": 0, "caution": 1, "warning": 2, "critical": 3}
    
    def _should_trigger(self, severity: str) -> bool:
        """Check if severity meets threshold."""
        level = self._severity_order.get(severity.lower(), 0)
        min_level = self._severity_order.get(self.min_severity.lower(), 0)
        return level >= min_level
    
    def __call__(self, anomaly):
        """
        Callback handler for anomaly detection.
        
        Works with HORIZON's Anomaly dataclass or any object with:
        - category (str or enum)
        - severity (str or enum)
        - title (str)
        - description (str)
        - source_data (dict)
        """
        # Extract values (handle enums)
        category = getattr(anomaly.category, "value", str(anomaly.category))
        severity = getattr(anomaly.severity, "value", str(anomaly.severity))
        
        if not self._should_trigger(severity):
            return
        
        # Build trigger event
        async def fire():
            try:
                response = await self.client.trigger(
                    source=self.source,
                    event_type="anomaly",
                    category=category,
                    severity=severity,
                    title=anomaly.title,
                    description=anomaly.description,
                    data=getattr(anomaly, "source_data", {}),
                    context={
                        "anomaly_id": getattr(anomaly, "id", None),
                        "detected_at": getattr(anomaly, "detected_at", None),
                        "ai_analysis": getattr(anomaly, "ai_analysis", None),
                    }
                )
                print(f"[Atmosphere] Triggered: {response.status} → {response.agent_id}")
            except Exception as e:
                print(f"[Atmosphere] Trigger failed: {e}")
        
        if self.async_fire:
            # Fire and forget
            asyncio.create_task(fire())
        else:
            # Block until complete
            asyncio.get_event_loop().run_until_complete(fire())


# ============================================================================
# Sync wrapper for non-async code
# ============================================================================

class AtmosphereClientSync:
    """
    Synchronous wrapper for AtmosphereClient.
    
    Use this if your code isn't async:
        client = AtmosphereClientSync("http://localhost:18765")
        response = client.trigger(source="horizon", ...)
    """
    
    def __init__(self, *args, **kwargs):
        self._client = AtmosphereClient(*args, **kwargs)
        self._loop = asyncio.new_event_loop()
    
    def _run(self, coro):
        return self._loop.run_until_complete(coro)
    
    def health(self):
        return self._run(self._client.health())
    
    def trigger(self, **kwargs) -> TriggerResponse:
        return self._run(self._client.trigger(**kwargs))
    
    def test_trigger(self, **kwargs):
        return self._run(self._client.test_trigger(**kwargs))
    
    def get_trigger_history(self, limit: int = 50):
        return self._run(self._client.get_trigger_history(limit))
    
    def list_agents(self):
        return self._run(self._client.list_agents())
    
    def close(self):
        self._run(self._client.close())
        self._loop.close()


# ============================================================================
# Example usage
# ============================================================================

if __name__ == "__main__":
    async def demo():
        client = AtmosphereClient()
        
        # Check health
        health = await client.health()
        print(f"Atmosphere status: {health}")
        
        # Test routing
        test = await client.test_trigger(
            source="horizon",
            event_type="anomaly", 
            category="fuel",
            severity="warning"
        )
        print(f"Would spawn: {test['would_spawn']}")
        
        # Fire a trigger
        response = await client.trigger(
            source="horizon",
            event_type="anomaly",
            category="fuel",
            severity="warning",
            title="Fuel Burn Rate Deviation",
            description="Current burn rate is 15% above planned",
            data={
                "burn_ratio": 1.15,
                "current_fuel_lbs": 145000,
                "hours_remaining": 4.2
            }
        )
        print(f"Trigger response: {response}")
        
        await client.close()
    
    asyncio.run(demo())
