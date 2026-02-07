"""
HORIZON Integration for Atmosphere Agents

This module shows how to integrate Atmosphere Agents into HORIZON.
When anomalies are detected, they trigger AI agents for analysis.

INSTALLATION:
1. Copy atmosphere_client.py to HORIZON's src directory
2. Add this integration code to HORIZON's anomaly.py or run.py

QUICK START:
    # In HORIZON's startup (run.py or main):
    from horizon_integration import setup_atmosphere_integration
    setup_atmosphere_integration()
"""

import asyncio
from typing import Optional
import os

# Import the client (adjust path as needed)
try:
    from .atmosphere_client import AtmosphereClient, AnomalyTriggerCallback
except ImportError:
    from atmosphere_client import AtmosphereClient, AnomalyTriggerCallback


# ============================================================================
# Configuration
# ============================================================================

ATMOSPHERE_URL = os.getenv("ATMOSPHERE_URL", "http://localhost:18765")
MIN_SEVERITY = os.getenv("ATMOSPHERE_MIN_SEVERITY", "caution")  # Filter noise


# ============================================================================
# Integration Setup
# ============================================================================

def setup_atmosphere_integration(
    atmosphere_url: str = ATMOSPHERE_URL,
    min_severity: str = MIN_SEVERITY
):
    """
    Set up Atmosphere Agents integration for HORIZON.
    
    This registers a callback with HORIZON's anomaly engine that
    fires triggers to Atmosphere when anomalies are detected.
    
    Call this once during HORIZON startup.
    """
    # Import HORIZON's anomaly engine
    try:
        from src.core.anomaly import get_anomaly_engine
    except ImportError:
        from core.anomaly import get_anomaly_engine
    
    # Create callback
    callback = AnomalyTriggerCallback(
        source="horizon",
        atmosphere_url=atmosphere_url,
        min_severity=min_severity,
        async_fire=True  # Don't block anomaly processing
    )
    
    # Register with engine
    engine = get_anomaly_engine()
    engine.register_callback(callback)
    
    print(f"[HORIZON] Atmosphere integration enabled → {atmosphere_url}")
    print(f"[HORIZON] Triggering agents for severity >= {min_severity}")
    
    return callback


# ============================================================================
# Direct Trigger Functions
# ============================================================================

_client: Optional[AtmosphereClient] = None

def get_client() -> AtmosphereClient:
    """Get or create Atmosphere client singleton."""
    global _client
    if _client is None:
        _client = AtmosphereClient(ATMOSPHERE_URL, source_id="horizon")
    return _client


async def trigger_fuel_analysis(
    burn_ratio: float,
    current_fuel_lbs: int,
    hours_remaining: float,
    description: str = ""
):
    """
    Directly trigger fuel analysis agent.
    
    Use this for programmatic triggers (not anomaly-based).
    """
    client = get_client()
    
    severity = "critical" if burn_ratio >= 1.35 else \
               "warning" if burn_ratio >= 1.20 else \
               "caution" if burn_ratio >= 1.10 else "info"
    
    return await client.trigger(
        source="horizon",
        event_type="analysis_request",
        category="fuel",
        severity=severity,
        title="Fuel Analysis Request",
        description=description or f"Analyze fuel status: {burn_ratio:.1%} burn rate",
        data={
            "burn_ratio": burn_ratio,
            "current_fuel_lbs": current_fuel_lbs,
            "hours_remaining": hours_remaining
        }
    )


async def trigger_threat_assessment(
    threat_data: dict,
    severity: str = "warning"
):
    """Trigger intel analyst for threat assessment."""
    client = get_client()
    
    return await client.trigger(
        source="horizon",
        event_type="threat_alert",
        category="threat",
        severity=severity,
        title="Threat Assessment Request",
        description="Analyze current threat environment",
        data=threat_data
    )


async def trigger_maintenance_analysis(
    equipment: str,
    issue: str,
    severity: str = "warning"
):
    """Trigger maintenance specialist for equipment issue."""
    client = get_client()
    
    return await client.trigger(
        source="horizon",
        event_type="equipment_issue",
        category="equipment",
        severity=severity,
        title=f"Equipment Issue: {equipment}",
        description=issue,
        data={"equipment": equipment, "issue": issue}
    )


async def request_mission_brief(
    mission_data: dict,
    target_agent: str = "horizon-orchestrator"
):
    """Request comprehensive mission brief from orchestrator."""
    client = get_client()
    
    return await client.trigger(
        source="horizon",
        event_type="brief_request",
        category="mission",
        severity="info",
        title="Mission Brief Request",
        description="Generate comprehensive mission briefing",
        data=mission_data,
        target_agent=target_agent
    )


# ============================================================================
# Example: Patching HORIZON's Anomaly Engine
# ============================================================================

def patch_anomaly_engine():
    """
    Alternative: Monkey-patch the anomaly engine to include triggers.
    
    Use this if you can't modify HORIZON's source directly.
    """
    try:
        from src.core.anomaly import AnomalyEngine
    except ImportError:
        from core.anomaly import AnomalyEngine
    
    original_run = AnomalyEngine.run_all_detectors
    
    async def patched_run_all_detectors(self):
        """Run detectors and trigger Atmosphere for significant anomalies."""
        anomalies = await original_run(self)
        
        client = get_client()
        for anomaly in anomalies:
            category = getattr(anomaly.category, "value", str(anomaly.category))
            severity = getattr(anomaly.severity, "value", str(anomaly.severity))
            
            # Only trigger for caution+ severity
            if severity in ("warning", "critical", "caution"):
                try:
                    await client.trigger(
                        source="horizon",
                        event_type="anomaly",
                        category=category,
                        severity=severity,
                        title=anomaly.title,
                        description=anomaly.description,
                        data=anomaly.source_data
                    )
                except Exception as e:
                    print(f"[Atmosphere] Trigger failed: {e}")
        
        return anomalies
    
    AnomalyEngine.run_all_detectors = patched_run_all_detectors
    print("[HORIZON] Anomaly engine patched for Atmosphere integration")


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    async def demo():
        # Method 1: Setup callback integration
        # (This is the preferred approach)
        # setup_atmosphere_integration()
        
        # Method 2: Direct triggers
        response = await trigger_fuel_analysis(
            burn_ratio=1.18,
            current_fuel_lbs=142000,
            hours_remaining=4.2,
            description="Mission REACH 421 showing elevated fuel consumption"
        )
        print(f"Fuel analysis triggered: {response}")
        
        # Method 3: Full orchestrator engagement
        response = await request_mission_brief({
            "callsign": "REACH 421",
            "route": "KDOV → OKBK",
            "current_position": "N32.5 E045.2",
            "fuel_remaining_lbs": 142000,
            "eta_destination": "4.2 hours"
        })
        print(f"Mission brief requested: {response}")
    
    asyncio.run(demo())
