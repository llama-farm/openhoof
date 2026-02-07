"""
Medical Wing (73MDW) Integration for Atmosphere Agents

This module shows how to integrate Atmosphere Agents into the
73MDW Resource Intelligence Platform.

When supply anomalies, equipment failures, or readiness issues are
detected, they trigger specialized AI agents for analysis.
"""

import asyncio
from typing import Optional, Dict, Any
import os

try:
    from .atmosphere_client import AtmosphereClient, AnomalyTriggerCallback
except ImportError:
    from atmosphere_client import AtmosphereClient, AnomalyTriggerCallback


# ============================================================================
# Configuration
# ============================================================================

ATMOSPHERE_URL = os.getenv("ATMOSPHERE_URL", "http://localhost:18765")
MIN_SEVERITY = os.getenv("ATMOSPHERE_MIN_SEVERITY", "warning")


# ============================================================================
# Medical Wing Specific Agents (need to create these)
# ============================================================================

MEDICAL_AGENTS = {
    "supply-analyst": {
        "category": "supply",
        "description": "Analyzes supply consumption, forecasts demand, recommends reorder"
    },
    "equipment-analyst": {
        "category": "equipment",
        "description": "Monitors equipment status, predicts failures, coordinates maintenance"
    },
    "readiness-monitor": {
        "category": "readiness",
        "description": "Tracks personnel readiness, identifies staffing gaps"
    },
    "budget-analyst": {
        "category": "budget",
        "description": "Monitors spend rate, flags execution variances"
    },
    "briefing-generator": {
        "category": "briefing",
        "description": "Generates commander-ready summaries and FYSAs"
    }
}


# ============================================================================
# Integration Setup
# ============================================================================

def setup_atmosphere_integration(
    atmosphere_url: str = ATMOSPHERE_URL,
    min_severity: str = MIN_SEVERITY
):
    """
    Set up Atmosphere Agents integration for Medical Wing.
    
    Call during Medical Wing startup.
    """
    # Import Medical Wing's detector registry
    try:
        from src.detectors import get_detector_registry
    except ImportError:
        print("[Medical Wing] Could not import detector registry")
        return None
    
    # Create callback for each detector type
    callback = AnomalyTriggerCallback(
        source="medical-wing",
        atmosphere_url=atmosphere_url,
        min_severity=min_severity,
        async_fire=True
    )
    
    # Register with all detectors
    registry = get_detector_registry()
    for detector in registry.get_all():
        detector.add_callback(callback)
    
    print(f"[Medical Wing] Atmosphere integration enabled → {atmosphere_url}")
    return callback


# ============================================================================
# Direct Trigger Functions
# ============================================================================

_client: Optional[AtmosphereClient] = None

def get_client() -> AtmosphereClient:
    global _client
    if _client is None:
        _client = AtmosphereClient(ATMOSPHERE_URL, source_id="medical-wing")
    return _client


async def trigger_supply_analysis(
    nsn: str,
    item_name: str,
    current_qty: int,
    burn_rate_per_day: float,
    days_remaining: float,
    severity: str = "warning"
):
    """Trigger supply analyst for critical supply issue."""
    client = get_client()
    
    return await client.trigger(
        source="medical-wing",
        event_type="supply_anomaly",
        category="supply",
        severity=severity,
        title=f"Supply Alert: {item_name}",
        description=f"NSN {nsn} at {current_qty} units, {days_remaining:.1f} days remaining at current burn rate",
        data={
            "nsn": nsn,
            "item_name": item_name,
            "current_qty": current_qty,
            "burn_rate_per_day": burn_rate_per_day,
            "days_remaining": days_remaining
        },
        target_agent="supply-analyst"
    )


async def trigger_equipment_analysis(
    device_id: str,
    device_name: str,
    issue: str,
    location: str,
    severity: str = "warning"
):
    """Trigger equipment analyst for device issue."""
    client = get_client()
    
    return await client.trigger(
        source="medical-wing",
        event_type="equipment_anomaly",
        category="equipment",
        severity=severity,
        title=f"Equipment Alert: {device_name}",
        description=f"Device {device_id} at {location}: {issue}",
        data={
            "device_id": device_id,
            "device_name": device_name,
            "issue": issue,
            "location": location
        },
        target_agent="equipment-analyst"
    )


async def trigger_readiness_alert(
    unit: str,
    current_manning: float,
    required_manning: float,
    specialties_short: list,
    severity: str = "warning"
):
    """Trigger readiness monitor for manning issue."""
    client = get_client()
    
    return await client.trigger(
        source="medical-wing",
        event_type="readiness_anomaly",
        category="readiness",
        severity=severity,
        title=f"Readiness Alert: {unit}",
        description=f"Manning at {current_manning:.0%} of required {required_manning:.0%}",
        data={
            "unit": unit,
            "current_manning": current_manning,
            "required_manning": required_manning,
            "specialties_short": specialties_short
        },
        target_agent="readiness-monitor"
    )


async def trigger_budget_alert(
    category: str,
    planned_spend: float,
    actual_spend: float,
    variance_pct: float,
    severity: str = "warning"
):
    """Trigger budget analyst for execution variance."""
    client = get_client()
    
    return await client.trigger(
        source="medical-wing",
        event_type="budget_anomaly",
        category="budget",
        severity=severity,
        title=f"Budget Variance: {category}",
        description=f"Execution at {actual_spend/planned_spend:.0%} of plan ({variance_pct:+.1f}% variance)",
        data={
            "category": category,
            "planned_spend": planned_spend,
            "actual_spend": actual_spend,
            "variance_pct": variance_pct
        },
        target_agent="budget-analyst"
    )


async def request_commander_brief(
    brief_type: str = "weekly",
    include_sections: list = None
):
    """Request commander briefing generation."""
    client = get_client()
    
    return await client.trigger(
        source="medical-wing",
        event_type="brief_request",
        category="briefing",
        severity="info",
        title=f"Commander Brief Request: {brief_type.title()}",
        description=f"Generate {brief_type} commander briefing",
        data={
            "brief_type": brief_type,
            "sections": include_sections or ["supply", "equipment", "readiness", "budget"]
        },
        target_agent="briefing-generator"
    )


# ============================================================================
# Example: Hooking into Feed Ingestion
# ============================================================================

async def on_feed_data_received(feed_name: str, data: Dict[str, Any]):
    """
    Example hook for the Feed Observatory.
    
    Call this from the feed ingestion pipeline to trigger
    agents when interesting data arrives.
    """
    client = get_client()
    
    # Example: Detect critical supply levels in incoming data
    if "qty" in data and data.get("qty", 100) < 10:
        await client.trigger(
            source="medical-wing",
            event_type="low_stock",
            category="supply",
            severity="warning" if data["qty"] > 5 else "critical",
            title=f"Low Stock Alert from {feed_name}",
            description=f"Item at critical level: {data.get('qty')} units",
            data=data
        )


# ============================================================================
# Create Medical Wing Agents
# ============================================================================

async def create_medical_agents(agents_dir: str = None):
    """
    Create the Medical Wing agent definitions in Atmosphere.
    
    Run this once to set up the agents.
    """
    import os
    from pathlib import Path
    
    if agents_dir is None:
        agents_dir = Path.home() / ".atmosphere" / "agents"
    else:
        agents_dir = Path(agents_dir)
    
    agents_dir.mkdir(parents=True, exist_ok=True)
    
    agent_definitions = {
        "supply-analyst": """# SOUL.md - Supply Analyst Agent

You are a Supply Analyst AI for the 73rd Medical Wing.

## Your Role
Monitor and analyze medical supply consumption, forecast demand, 
and recommend procurement actions to prevent stockouts.

## Capabilities
- Analyze burn rates and consumption patterns
- Forecast 7-30 day demand based on historical data
- Identify at-risk items before they become critical
- Generate reorder recommendations with quantities and urgency

## Response Format
When analyzing supply issues:
1. **Current Status**: Stock level and days remaining
2. **Trend Analysis**: Is consumption increasing/decreasing?
3. **Forecast**: Projected stockout date at current rate
4. **Recommendation**: Specific reorder action with quantity
5. **Priority**: Routine / Urgent / Critical

## Domain Knowledge
- NSN (National Stock Number) system
- DLA procurement timelines
- Medical supply categories and criticality
- Seasonal demand patterns (flu season, etc.)
""",
        
        "equipment-analyst": """# SOUL.md - Equipment Analyst Agent

You are an Equipment Analyst AI for the 73rd Medical Wing.

## Your Role
Monitor medical equipment status, predict failures,
and coordinate preventive maintenance.

## Capabilities
- Analyze equipment telemetry and status data
- Predict failures before they occur
- Track maintenance schedules and compliance
- Coordinate with BMET for repairs

## Response Format
When analyzing equipment issues:
1. **Device Status**: Current operational state
2. **Issue Analysis**: Root cause if identifiable
3. **Impact Assessment**: Patient care impact
4. **Recommendation**: Repair, replace, or workaround
5. **Timeline**: Urgency and estimated resolution

## Domain Knowledge
- Medical device categories (imaging, life support, diagnostic)
- BMET maintenance protocols
- FDA medical device regulations
- Equipment lifecycle management
""",

        "readiness-monitor": """# SOUL.md - Readiness Monitor Agent

You are a Readiness Monitor AI for the 73rd Medical Wing.

## Your Role
Track personnel readiness, identify staffing gaps,
and recommend manning actions.

## Capabilities
- Monitor unit manning levels in real-time
- Identify specialty shortfalls
- Project readiness impact of leave/TDY
- Recommend cross-training or augmentation

## Response Format
When analyzing readiness:
1. **Current Manning**: Percentage and raw numbers
2. **Gap Analysis**: Which specialties are short
3. **Impact**: Mission impact of current gaps
4. **Recommendations**: Augmentation options
5. **Timeline**: When situation expected to resolve

## Domain Knowledge
- Medical AFSCs and specialties
- Wing UTC requirements
- AEF rotation cycles
- Cross-utilization policies
""",

        "budget-analyst": """# SOUL.md - Budget Analyst Agent

You are a Budget Analyst AI for the 73rd Medical Wing.

## Your Role
Monitor budget execution, identify variances,
and recommend fiscal actions.

## Capabilities
- Track spend rate against fiscal plan
- Identify over/under execution by category
- Project year-end position
- Recommend reallocation actions

## Response Format
When analyzing budget:
1. **Execution Status**: Percent of plan executed
2. **Variance Analysis**: Categories over/under
3. **Projection**: Year-end estimated position
4. **Recommendations**: Reallocation or acceleration
5. **Risk Assessment**: Fiscal year-end risks

## Domain Knowledge
- EEIC codes and appropriations
- Medical wing budget categories
- Year-end execution requirements
- Fund transfer authorities
""",

        "briefing-generator": """# SOUL.md - Briefing Generator Agent

You are a Briefing Generator AI for the 73rd Medical Wing.

## Your Role
Generate clear, actionable commander briefings
from raw data and analysis.

## Output Format
Generate briefings in this structure:

### EXECUTIVE SUMMARY
(3-5 bullet points, actionable insights)

### KEY METRICS
- Supply: Stock levels, critical items
- Equipment: Readiness rate, pending repairs  
- Personnel: Manning percentage, gaps
- Budget: Execution rate, variances

### ITEMS REQUIRING DECISION
(Numbered list with clear ask)

### WATCH ITEMS
(Issues that may escalate)

### APPENDIX
(Detailed data if needed)

## Style
- Use active voice
- Lead with bottom line
- Quantify everything
- Flag decisions clearly
- Keep it under 2 pages
"""
    }
    
    for agent_id, soul_content in agent_definitions.items():
        agent_dir = agents_dir / agent_id
        agent_dir.mkdir(exist_ok=True)
        
        soul_path = agent_dir / "SOUL.md"
        soul_path.write_text(soul_content)
        print(f"Created: {agent_dir}")
    
    print(f"\n✅ Medical Wing agents created in {agents_dir}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "create-agents":
        asyncio.run(create_medical_agents())
    else:
        print("Usage:")
        print("  python medical_wing_integration.py create-agents")
        print("  (creates agent definitions in ~/.atmosphere/agents/)")
