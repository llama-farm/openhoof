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
    # Model-facing description: summary ONLY.
    # FunctionGemma 270M reads ~8 tokens — long descriptions hurt accuracy.
    # when_to_use is stored as metadata (x-guidance) for the SyntheticDataGenerator;
    # it is NOT included in the description sent to the model.
    description = summary.rstrip(".")

    # Safety constraints go into the description (they're model-relevant).
    if safety:
        safety_str = " ".join(safety)
        description += f" Safety: {safety_str}"

    # Normalize parameters: ensure every property has a 'description' field.
    # Some model templates (e.g. FunctionGemma) require description on each
    # property and will fail / fall back to text mode without it.
    normalized = parameters or {"type": "object", "properties": {}, "required": []}
    if "properties" in normalized:
        for prop_name, prop_def in normalized["properties"].items():
            if "description" not in prop_def:
                prop_def["description"] = prop_name.replace("_", " ")

    # Build OpenAI-compatible schema with metadata sidecar.
    # x-guidance is ignored by model inference but used by SyntheticDataGenerator
    # to understand intent when building teacher prompts.
    schema: Dict[str, Any] = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": normalized,
        }
    }

    guidance_parts = []
    if when_to_use:
        guidance_parts.append(when_to_use)
    if prerequisites:
        guidance_parts.append("Prerequisites: " + ", ".join(prerequisites))
    if best_practices:
        guidance_parts.append("Best practice: " + " ".join(best_practices))
    if guidance_parts:
        schema["x-guidance"] = " | ".join(guidance_parts)

    return schema
