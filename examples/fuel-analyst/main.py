#!/usr/bin/env python3
"""
fuel-analyst — C-17 fuel consumption analyst.

Demonstrates:
- Domain-specific tool chaining (get data → calculate → project → recommend)
- Structured output per SOUL.md protocol (STATUS/TREND/PROJECTION/RECOMMENDATIONS)
- Multi-step analysis in a single agent.reason() call

Usage:
    cd examples/fuel-analyst
    pip install openhoof
    python main.py
"""

from pathlib import Path
from openhoof import Agent, get_builtin_tool_schemas, builtin_executor, create_tool_schema

HERE = Path(__file__).parent

# ── Simulated flight data backend ─────────────────────────────────────────────

_FLIGHTS = {
    "MAY101": {
        "callsign": "MAY101", "origin": "KDOV", "destination": "OKBK",
        "fuel_onload_lbs": 180000, "fuel_current_lbs": 145000,
        "time_elapsed_min": 120, "distance_remaining_nm": 3200,
        "airspeed_ktas": 440, "altitude_ft": 33000,
        "lat": 42.5, "lon": -30.2,
        "planned_burn_lbs_per_hr": 18000,
    },
}

_WEATHER = {
    "MAY101_route": {"headwind_kt": 45, "temp_deviation_c": 8, "turbulence": False},
}

_ALTERNATES = [
    {"icao": "LPPD",  "name": "Ponta Delgada", "distance_nm": 180, "fuel_required_lbs": 12000},
    {"icao": "GCFV",  "name": "Fuerteventura",  "distance_nm": 320, "fuel_required_lbs": 20000},
    {"icao": "LPMA",  "name": "Madeira",         "distance_nm": 290, "fuel_required_lbs": 18000},
]


def get_flight_data(flight_id: str) -> dict:
    f = _FLIGHTS.get(flight_id.upper())
    if not f:
        return {"error": f"Flight {flight_id} not found"}
    elapsed_hr = f["time_elapsed_min"] / 60
    fuel_used = f["fuel_onload_lbs"] - f["fuel_current_lbs"]
    actual_burn = fuel_used / elapsed_hr if elapsed_hr else 0
    return {
        **f,
        "fuel_used_lbs": fuel_used,
        "actual_burn_lbs_per_hr": round(actual_burn, 0),
        "burn_ratio": round(actual_burn / f["planned_burn_lbs_per_hr"], 3),
    }


def calculate_burn_rate(fuel_used_lbs: float, time_elapsed_min: float) -> dict:
    if time_elapsed_min <= 0:
        return {"error": "time_elapsed_min must be > 0"}
    rate = fuel_used_lbs / (time_elapsed_min / 60)
    return {"burn_rate_lbs_per_hr": round(rate, 0)}


def project_fuel_at_destination(
    current_fuel_lbs: float, burn_rate_lbs_per_hr: float,
    distance_nm: float, airspeed_ktas: float
) -> dict:
    time_remaining_hr = distance_nm / airspeed_ktas
    fuel_required = burn_rate_lbs_per_hr * time_remaining_hr
    fuel_at_dest = current_fuel_lbs - fuel_required
    reserve_pct = (fuel_at_dest / current_fuel_lbs) * 100 if current_fuel_lbs else 0
    status = "GREEN" if reserve_pct >= 15 else ("AMBER" if reserve_pct >= 10 else "RED")
    return {
        "time_remaining_hr": round(time_remaining_hr, 2),
        "fuel_required_lbs": round(fuel_required, 0),
        "fuel_at_destination_lbs": round(fuel_at_dest, 0),
        "reserve_pct": round(reserve_pct, 1),
        "status": status,
    }


def get_weather_impact(route_id: str) -> dict:
    w = _WEATHER.get(route_id)
    if not w:
        return {"error": f"No weather data for route {route_id}"}
    headwind_impact = (w["headwind_kt"] / 20) * 0.04  # +4% per 20kt headwind
    temp_impact = (w["temp_deviation_c"] / 10) * 0.02  # +2% per 10°C above ISA
    total_impact_pct = round((headwind_impact + temp_impact) * 100, 1)
    return {
        **w,
        "burn_increase_pct": total_impact_pct,
        "explanation": f"Headwind {w['headwind_kt']}kt (+{headwind_impact*100:.1f}%) + Temp +{w['temp_deviation_c']}°C ISA (+{temp_impact*100:.1f}%)",
    }


def search_alternates(lat: float, lon: float, min_fuel_lbs: float) -> dict:
    viable = [a for a in _ALTERNATES if a["fuel_required_lbs"] <= min_fuel_lbs]
    return {"alternates": viable, "count": len(viable)}


# ── Tool schemas ──────────────────────────────────────────────────────────────

FUEL_TOOLS = [
    create_tool_schema(
        name="get_flight_data",
        summary="Get current flight telemetry: position, fuel state, burn rate vs planned",
        when_to_use="First step of any fuel analysis",
        parameters={"type": "object", "properties": {"flight_id": {"type": "string"}}, "required": ["flight_id"]},
    ),
    create_tool_schema(
        name="calculate_burn_rate",
        summary="Calculate actual fuel burn rate from fuel used and time elapsed",
        when_to_use="When you have raw fuel_used and time data",
        parameters={
            "type": "object",
            "properties": {
                "fuel_used_lbs":    {"type": "number"},
                "time_elapsed_min": {"type": "number"},
            },
            "required": ["fuel_used_lbs", "time_elapsed_min"],
        },
    ),
    create_tool_schema(
        name="project_fuel_at_destination",
        summary="Project fuel remaining at destination given current burn rate",
        when_to_use="After calculating burn rate — projects end state and assigns GREEN/AMBER/RED",
        parameters={
            "type": "object",
            "properties": {
                "current_fuel_lbs":    {"type": "number"},
                "burn_rate_lbs_per_hr": {"type": "number"},
                "distance_nm":         {"type": "number"},
                "airspeed_ktas":       {"type": "number"},
            },
            "required": ["current_fuel_lbs", "burn_rate_lbs_per_hr", "distance_nm", "airspeed_ktas"],
        },
    ),
    create_tool_schema(
        name="get_weather_impact",
        summary="Get weather factor on fuel burn (headwind, temp deviation)",
        when_to_use="When burn ratio is elevated — check if weather explains it",
        parameters={"type": "object", "properties": {"route_id": {"type": "string"}}, "required": ["route_id"]},
    ),
    create_tool_schema(
        name="search_alternates",
        summary="Find viable alternate airfields given current fuel state",
        when_to_use="When status is AMBER or RED — need divert options",
        parameters={
            "type": "object",
            "properties": {
                "lat":              {"type": "number"},
                "lon":              {"type": "number"},
                "min_fuel_lbs":     {"type": "number", "description": "Fuel available for divert"},
            },
            "required": ["lat", "lon", "min_fuel_lbs"],
        },
    ),
]

ALL_TOOLS = get_builtin_tool_schemas() + FUEL_TOOLS
TOOL_FNS = {
    "get_flight_data": get_flight_data,
    "calculate_burn_rate": calculate_burn_rate,
    "project_fuel_at_destination": project_fuel_at_destination,
    "get_weather_impact": get_weather_impact,
    "search_alternates": search_alternates,
}


def executor(agent, tool_name, params):
    if tool_name in TOOL_FNS:
        return TOOL_FNS[tool_name](**params)
    return builtin_executor(agent, tool_name, params)


def main():
    agent = Agent(
        soul=str(HERE / "SOUL.md"),
        memory=str(HERE / "MEMORY.md"),
        tools=ALL_TOOLS,
        executor=lambda name, params: executor(agent, name, params),
        workspace=str(HERE),
        max_turns=10,
    )

    print("⛽ Fuel Analyst ready. Available flight: MAY101\n")
    print("Try: 'Analyze fuel state for MAY101'\n")

    while True:
        try:
            user_input = input("Request: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession ended.")
            break
        if not user_input or user_input.lower() in ("quit", "exit"):
            break
        response = agent.reason(user_input)
        print(f"\n{response.get('content', '')}\n")


if __name__ == "__main__":
    main()
