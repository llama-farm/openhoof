"""FunctionGemma-based tool routing experiment.

Uses the tiny FunctionGemma-270M model as a fast pre-filter to determine
which tools are relevant for a given user message. This creates a training
pipeline: as tools are added and used, we collect data to fine-tune the router.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from .adapter import InferenceAdapter

logger = logging.getLogger(__name__)

# Training data collection directory
TRAINING_DATA_DIR = Path.home() / ".openhoof" / "data" / "tool_training"


class ToolRouter:
    """Fast tool-call routing using a small specialist model.
    
    Architecture:
    1. User message arrives
    2. ToolRouter (FunctionGemma-270M) classifies which tools to invoke (~50ms)
    3. Main model gets the tool selection as a hint, reducing hallucinated tool calls
    4. Every routing decision is logged as training data
    5. Periodically, we can LoRA fine-tune the router on accumulated data
    """

    def __init__(
        self,
        inference: InferenceAdapter,
        router_model: str = "functiongemma",
        enabled: bool = True,
    ):
        self.inference = inference
        self.router_model = router_model
        self.enabled = enabled
        self._training_data_path = TRAINING_DATA_DIR / "routing_decisions.jsonl"
        TRAINING_DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _build_routing_prompt(
        self, user_message: str, tools: List[Dict[str, Any]]
    ) -> str:
        """Build a prompt for the router model."""
        tool_descriptions = []
        for t in tools:
            func = t.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "").split("\n")[0]
            params = list(func.get("parameters", {}).get("properties", {}).keys())
            tool_descriptions.append(
                f"- {name}({', '.join(params)}): {desc}"
            )

        tools_text = "\n".join(tool_descriptions)

        return f"""Available functions:
{tools_text}

User request: {user_message}

Which function(s) should be called? Respond with a JSON array of function names, or [] if none needed."""

    async def route(
        self,
        user_message: str,
        tools: List[Dict[str, Any]],
    ) -> Optional[List[str]]:
        """Route a user message to the most relevant tools.
        
        Returns a list of tool names that should be available, or None
        if routing fails (in which case all tools should be passed).
        """
        if not self.enabled or not tools:
            return None

        prompt = self._build_routing_prompt(user_message, tools)

        try:
            response = await self.inference.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.router_model,
                stateless=True,
                rag_enabled=False,
                max_tokens=256,
                temperature=0.1,
            )

            # Parse the response — expect a JSON array of tool names
            content = response.content.strip()
            
            # Try to extract JSON array from response
            if "[" in content:
                start = content.index("[")
                end = content.rindex("]") + 1
                tool_names = json.loads(content[start:end])
                
                if isinstance(tool_names, list):
                    # Validate tool names
                    valid_names = {
                        t.get("function", {}).get("name")
                        for t in tools
                    }
                    filtered = [n for n in tool_names if n in valid_names]
                    
                    # Log training data
                    self._log_routing_decision(user_message, tools, filtered)
                    
                    return filtered if filtered else None
            
            return None

        except Exception as e:
            logger.debug(f"Tool router failed (falling back to all tools): {e}")
            return None

    def _log_routing_decision(
        self,
        user_message: str,
        tools: List[Dict[str, Any]],
        selected_tools: List[str],
    ):
        """Log a routing decision for future training."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user_message": user_message[:500],
            "available_tools": [
                t.get("function", {}).get("name") for t in tools
            ],
            "selected_tools": selected_tools,
        }

        try:
            with open(self._training_data_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.debug(f"Failed to log routing decision: {e}")

    def log_tool_outcome(
        self,
        user_message: str,
        tool_name: str,
        was_useful: bool,
    ):
        """Log whether a tool call was actually useful (for training feedback).
        
        Call this after a tool is executed to improve future routing.
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "outcome",
            "user_message": user_message[:500],
            "tool_name": tool_name,
            "was_useful": was_useful,
        }

        try:
            with open(self._training_data_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.debug(f"Failed to log tool outcome: {e}")

    def get_training_stats(self) -> Dict[str, Any]:
        """Get statistics about collected training data."""
        if not self._training_data_path.exists():
            return {"total_entries": 0, "routing_decisions": 0, "outcomes": 0}

        total = 0
        routing = 0
        outcomes = 0

        for line in self._training_data_path.read_text().strip().split("\n"):
            if not line:
                continue
            total += 1
            try:
                entry = json.loads(line)
                if entry.get("type") == "outcome":
                    outcomes += 1
                else:
                    routing += 1
            except json.JSONDecodeError:
                pass

        return {
            "total_entries": total,
            "routing_decisions": routing,
            "outcomes": outcomes,
            "data_path": str(self._training_data_path),
        }
