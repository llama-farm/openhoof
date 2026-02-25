"""Tool schema helper - create rich tool descriptions."""

from typing import Dict, Any, List, Optional


def create_tool_schema(
    name: str,
    summary: str,
    when_to_use: Optional[str] = None,
    prerequisites: Optional[List[str]] = None,
    best_practices: Optional[List[str]] = None,
    safety: Optional[List[str]] = None,
    parameters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create rich tool schema with embedded usage guidance.
    
    This helper generates OpenAI-compatible tool schemas with enhanced
    descriptions that include operational context for autonomous agents.
    
    Args:
        name: Tool name (snake_case)
        summary: One-line summary of what the tool does
        when_to_use: When to use this tool (vs alternatives)
        prerequisites: List of prerequisites (e.g. ["GPS lock", "Battery > 40%"])
        best_practices: List of best practices (e.g. ["Wait 3s after return"])
        safety: List of safety constraints (e.g. ["Abort if wind > 15 m/s"])
        parameters: JSON Schema parameter definition
    
    Returns:
        OpenAI-compatible tool schema with rich description
    
    Example:
        >>> create_tool_schema(
        ...     name="drone_takeoff",
        ...     summary="Arm motors and take off to hover altitude",
        ...     when_to_use="Mission start after telemetry check",
        ...     prerequisites=["GPS lock >= 8 sats", "Battery > 40%"],
        ...     best_practices=["Wait 3s after return before next command"],
        ...     safety=["Abort if wind > 15 m/s"]
        ... )
    """
    # Build rich description from parts
    parts = [summary]
    
    if when_to_use:
        parts.append(f"When to use: {when_to_use}.")
    
    if prerequisites:
        prereq_str = ", ".join(prerequisites)
        parts.append(f"Prerequisites: {prereq_str}.")
    
    if best_practices:
        practice_str = " ".join(best_practices)
        parts.append(f"Best practice: {practice_str}.")
    
    if safety:
        safety_str = " ".join(safety)
        parts.append(f"Safety: {safety_str}.")
    
    description = " ".join(parts)
    
    # Build OpenAI-compatible schema
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters or {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
