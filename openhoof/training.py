"""
Training data capture — every tool call becomes fine-tuning data.

## Architecture

Two models, two completely different training data formats:

### Router samples  →  router_YYYY-MM-DD.jsonl  (FunctionGemma 270M)

Single-turn. One routing question → one tool call. No chaining, no context.
FunctionGemma never sees multi-step plans — it just answers one question at a time.

    {"model": "router",
     "messages": [
         {"role": "user", "content": "scan for person"}
     ],
     "tool_call": {"name": "drone_scan", "arguments": {"lock_on_class": "person"}},
     "confidence": 0.95,   // from logprobs if available
     "timestamp": 1234}

### Reasoner samples  →  reasoner_YYYY-MM-DD.jsonl  (Qwen3 1.7B)

Multi-turn. Full conversation chain — task → tool calls → results → decision.
This is what Qwen3 learns from: how to chain 3 tool calls to complete a mission.

    {"model": "reasoner",
     "messages": [
         {"role": "system",    "content": "..."},
         {"role": "user",      "content": "find horses and follow them"},
         {"role": "assistant", "tool_calls": [...]},
         {"role": "tool",      "content": "..."},
         {"role": "assistant", "tool_calls": [...]},
         {"role": "tool",      "content": "..."},
         {"role": "assistant", "content": "Locked on 3 horses at bearing 045."}
     ],
     "turn_count": 3,
     "timestamp": 1234}

## Usage

The Agent loop calls these automatically:
  - _execute_with_router()  → training.capture_router()
  - reason() end of chain   → training.capture_reasoner()
  - call_tool() directly    → training.capture_tool_call() (legacy/misc)
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class TrainingDataCapture:
    """
    Capture tool calls and reasoning chains as JSONL training data.

    Writes to two separate files:
      - router_YYYY-MM-DD.jsonl   → FunctionGemma fine-tuning
      - reasoner_YYYY-MM-DD.jsonl → Qwen3 fine-tuning
    """

    def __init__(self, output_dir: str = ".microclaw/training"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        self._router_file = self.output_dir / f"router_{today}.jsonl"
        self._reasoner_file = self.output_dir / f"reasoner_{today}.jsonl"

        self.captured_count = 0
        self._router_count = 0
        self._reasoner_count = 0

    # ── Router samples (FunctionGemma) ─────────────────────────────────────────

    def capture_router(
        self,
        user_intent: str,
        tool_name: str,
        tool_params: Dict[str, Any],
        confidence: Optional[float] = None,
        agreed: Optional[bool] = None,
    ) -> None:
        """
        Capture a single-turn routing decision for FunctionGemma fine-tuning.

        FunctionGemma gets one routing question at a time:
          "scan for person" → drone_scan(lock_on_class="person")

        Never include multi-step context — FunctionGemma is tiny (270M) and
        should only learn to route a single intent to a single tool call.

        Args:
            user_intent: The immediate intent being routed (last user message
                         or extracted single-step from Reasoner's decision)
            tool_name:   Tool that was called
            tool_params: Parameters used
            confidence:  Router confidence score (from logprobs if available)
            agreed:      Whether router agreed with Reasoner's choice
        """
        entry: Dict[str, Any] = {
            "model": "router",
            "messages": [
                {"role": "user", "content": user_intent}
            ],
            "tool_call": {
                "name": tool_name,
                "arguments": tool_params,
            },
            "timestamp": time.time(),
        }
        if confidence is not None:
            entry["confidence"] = round(confidence, 4)
        if agreed is not None:
            entry["agreed"] = agreed

        self._write(self._router_file, entry)
        self._router_count += 1
        self.captured_count += 1

    # ── Reasoner samples (Qwen3) ───────────────────────────────────────────────

    def capture_reasoner(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> None:
        """
        Capture a complete multi-turn reasoning chain for Qwen3 fine-tuning.

        The full conversation from user task → tool calls → results → final
        response. This is what teaches Qwen3 to chain tool calls correctly.

        Call this at the END of agent.reason() once the full chain is complete.

        Args:
            messages:      Full conversation history (already stripped of metadata)
            system_prompt: System prompt to prepend (from SOUL.md)
        """
        full_messages: List[Dict[str, Any]] = []
        if system_prompt and (not messages or messages[0].get("role") != "system"):
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        # Count reasoning turns (assistant messages with tool_calls)
        turn_count = sum(
            1 for m in full_messages
            if m.get("role") == "assistant" and m.get("tool_calls")
        )

        entry: Dict[str, Any] = {
            "model": "reasoner",
            "messages": full_messages,
            "turn_count": turn_count,
            "timestamp": time.time(),
        }

        self._write(self._reasoner_file, entry)
        self._reasoner_count += 1
        self.captured_count += 1

    # ── Legacy / misc tool calls ───────────────────────────────────────────────

    def capture(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: Dict[str, Any],
        context: Optional[str] = None,
        system_prompt: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Capture a single tool call (legacy path / direct call_tool() calls).

        Used for:
        - Built-in tool calls (memory_search, log, etc.)
        - Router validation results
        - Any tool called outside of agent.reason()

        These go into the router file as single-turn samples.
        """
        entry: Dict[str, Any] = {
            "model": "router",
            "messages": [],
            "tool_call": {
                "name": tool_name,
                "arguments": params,
                "result": result,
            },
            "timestamp": time.time(),
        }

        if system_prompt:
            entry["messages"].append({"role": "system", "content": system_prompt})
        if context:
            entry["messages"].append({"role": "user", "content": context})
        if metadata:
            entry["metadata"] = metadata

        self._write(self._router_file, entry)
        self._router_count += 1
        self.captured_count += 1

    # ── Utilities ──────────────────────────────────────────────────────────────

    def _write(self, path: Path, entry: Dict[str, Any]) -> None:
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def load(
        self,
        model: str = "all",
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Load captured training data.

        Args:
            model: "router", "reasoner", or "all" (default)
            limit: Max samples to return
        """
        files = []
        if model in ("router", "all"):
            files.append(self._router_file)
        if model in ("reasoner", "all"):
            files.append(self._reasoner_file)

        data = []
        for f in files:
            if not f.exists():
                continue
            with open(f) as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        data.append(json.loads(line))
                        if limit and len(data) >= limit:
                            return data
                    except json.JSONDecodeError:
                        continue
        return data

    def stats(self) -> Dict[str, Any]:
        """Training data statistics — samples captured per model."""
        def count_lines(p: Path) -> int:
            if not p.exists():
                return 0
            with open(p) as f:
                return sum(1 for line in f if line.strip())

        router_total = count_lines(self._router_file)
        reasoner_total = count_lines(self._reasoner_file)

        return {
            "router_samples":   router_total,
            "reasoner_samples": reasoner_total,
            "total":            router_total + reasoner_total,
            "router_file":      str(self._router_file),
            "reasoner_file":    str(self._reasoner_file),
        }

    def __repr__(self) -> str:
        return (
            f"TrainingDataCapture("
            f"router={self._router_count}, "
            f"reasoner={self._reasoner_count})"
        )
