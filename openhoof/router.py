"""
FunctionGemma Router — first-class routing component for OpenHoof.

## Architecture

The Router is a 270M model that does ONE thing: map an intent to a tool call.
It is NOT the reasoning engine. The Reasoner (Qwen3) decides WHAT to do;
the Router validates and normalizes the parameters.

## Two operating modes

### Validation mode (default in agent.reason())
    Reasoner has already decided: "call get_flight_data with flight_id=MAY101"
    Router validates the params against the schema and normalizes if needed.
    High confidence → use Router's params. Low confidence → use Reasoner's params.

### Routing mode (direct use)
    Caller provides intent, Router picks the tool entirely.
    Used for: fast event-driven routing, streaming, direct tool dispatch.

## Output format

FunctionGemma outputs its native format:
    <start_function_call>call:tool_name{key:<escape>value<escape>}<end_function_call>

The Router parses this internally and returns a clean RouterResult.
Callers never see the raw model output.

## Fine-tuning

Router training data is captured automatically via TrainingDataCapture.
Use FinetuneManager to convert captures → LlamaFarm SFT job:

    from openhoof.finetune import FinetuneManager
    ft = FinetuneManager(endpoint="http://localhost:11540/v1")
    job_id = ft.finetune_router(".microclaw/training")
"""

from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class RouterResult:
    """Result from a Router call."""
    tool_name: str
    params: Dict[str, Any]
    confidence: float           # 0.0–1.0; from logprobs when available, else 0.0
    agreed: bool                # True if Router chose same tool as Reasoner
    raw_content: str = ""       # Raw text output from the model (for debugging)

    @property
    def trusted(self) -> bool:
        """True when confidence meets the default threshold (0.85)."""
        return self.confidence >= 0.85


# ── Parser ────────────────────────────────────────────────────────────────────

class FunctionGemmaOutputParser:
    """
    Parse FunctionGemma's native output format into structured RouterResult.

    FunctionGemma produces:
        <start_function_call>call:TOOL_NAME{key:<escape>VALUE<escape>,...}<end_function_call>

    Numbers may be bare (no <escape> tags). Only the first call is extracted
    (the Router is a single-dispatch model — one intent → one tool call).
    """

    # Matches the outermost <start_function_call>...<end_function_call> block
    _BLOCK = re.compile(
        r"<start_function_call>\s*call:(\w+)\{(.*?)\}\s*<end_function_call>",
        re.DOTALL,
    )
    # Matches individual key:value pairs inside the block
    _PARAM = re.compile(
        r"(\w+):\s*(?:<escape>(.*?)<escape>|(-?\d+(?:\.\d+)?))",
        re.DOTALL,
    )

    @classmethod
    def parse(cls, content: str) -> Optional[Dict[str, Any]]:
        """
        Parse the first tool call from FunctionGemma output.

        Returns:
            {"name": str, "arguments": dict} or None if no call found.
        """
        m = cls._BLOCK.search(content)
        if not m:
            return None

        tool_name = m.group(1)
        body = m.group(2)
        args: Dict[str, Any] = {}

        for pm in cls._PARAM.finditer(body):
            key = pm.group(1)
            str_val = pm.group(2)
            num_val = pm.group(3)
            if str_val is not None:
                args[key] = str_val
            elif num_val is not None:
                args[key] = float(num_val) if "." in num_val else int(num_val)

        return {"name": tool_name, "arguments": args}

    @classmethod
    def to_openai_tool_call(cls, parsed: Dict[str, Any]) -> Dict[str, Any]:
        """Convert parsed result to OpenAI tool_call format."""
        return {
            "id": f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {
                "name": parsed["name"],
                "arguments": json.dumps(parsed["arguments"]),
            },
        }


# ── Confidence extraction ─────────────────────────────────────────────────────

class ConfidenceExtractor:
    """
    Extract real confidence scores from logprobs for a given tool name.

    Searches the token stream for the tool name and converts logprob to
    probability: confidence = exp(logprob).

    Handles two cases:
    1. Tool name as a single token   → exact match
    2. Tool name split across tokens → assembles and uses first token's logprob
    """

    @staticmethod
    def extract(logprobs_data: Optional[Dict[str, Any]], tool_name: str) -> Optional[float]:
        if not logprobs_data:
            return None

        tokens = logprobs_data.get("content") or []

        for i, tok in enumerate(tokens):
            token = tok.get("token", "")
            logprob = tok.get("logprob")

            # Full match in one token
            if tool_name in token and logprob is not None:
                return round(math.exp(logprob), 4)

            # Possible first token of a split name
            clean = token.strip('"').strip()
            if tool_name.startswith(clean) and len(clean) > 2:
                assembled = clean
                for j in range(i + 1, min(i + 6, len(tokens))):
                    assembled += tokens[j].get("token", "").strip('"')
                    if tool_name in assembled:
                        if logprob is not None:
                            return round(math.exp(logprob), 4)
                        break

        # Check top_logprobs at each position
        for tok in tokens:
            for candidate in tok.get("top_logprobs", []):
                if tool_name in candidate.get("token", ""):
                    lp = candidate.get("logprob")
                    if lp is not None:
                        return round(math.exp(lp), 4)

        return None


# ── Router ────────────────────────────────────────────────────────────────────

class FunctionGemmaRouter:
    """
    FunctionGemma 270M router — validates and normalizes tool calls.

    Usage (validation mode — called from agent.reason()):
        result = router.validate(
            tool_name="get_flight_data",
            params={"flight_id": "MAY101"},
            intent="Get fuel state for flight MAY101",
            tools=tool_schemas,
        )
        if result.trusted:
            use result.params   # Router normalized them
        else:
            use reasoner_params # Router uncertain; keep Reasoner's choice

    Usage (routing mode — direct dispatch):
        result = router.route(
            intent="What is the fuel burn for MAY101?",
            tools=tool_schemas,
        )
        # result.tool_name, result.params
    """

    SYSTEM_PROMPT = (
        "You are a function router. "
        "Given a user request and available functions, select the correct function "
        "and return its parameters. Return a single function call only."
    )

    def __init__(
        self,
        endpoint: str,
        model: str = "unsloth/functiongemma-270m-it-GGUF",
        confidence_threshold: float = 0.85,
        timeout: int = 15,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.confidence_threshold = confidence_threshold
        self.timeout = timeout
        self._parser = FunctionGemmaOutputParser()

    # ── Public API ─────────────────────────────────────────────────────────────

    def validate(
        self,
        tool_name: str,
        params: Dict[str, Any],
        intent: str,
        tools: List[Dict[str, Any]],
    ) -> RouterResult:
        """
        Validate and optionally normalize params for an already-chosen tool.

        The Reasoner has decided WHAT tool to call. The Router's job is to
        check whether the params are correct and normalized. If the Router
        agrees and is confident, its normalized params are used. Otherwise
        the Reasoner's params are used as-is.

        Args:
            tool_name:  Tool the Reasoner chose
            params:     Parameters the Reasoner supplied
            intent:     Single-step intent (NOT the full task — just this step)
            tools:      Full list of available tool schemas

        Returns:
            RouterResult with confidence score and (possibly normalized) params
        """
        response = self._call(intent, tools)
        return self._build_result(response, tool_name, params)

    def route(
        self,
        intent: str,
        tools: List[Dict[str, Any]],
    ) -> RouterResult:
        """
        Route an intent directly to a tool call (no prior Reasoner decision).

        Args:
            intent: User intent or agent step description
            tools:  Full list of available tool schemas

        Returns:
            RouterResult with chosen tool and params
        """
        response = self._call(intent, tools)
        parsed = FunctionGemmaOutputParser.parse(response.get("content", ""))
        if not parsed:
            return RouterResult(
                tool_name="",
                params={},
                confidence=0.0,
                agreed=False,
                raw_content=response.get("content", ""),
            )
        confidence = (
            ConfidenceExtractor.extract(response.get("logprobs"), parsed["name"])
            or 0.0
        )
        return RouterResult(
            tool_name=parsed["name"],
            params=parsed["arguments"],
            confidence=confidence,
            agreed=True,
            raw_content=response.get("content", ""),
        )

    # ── Internal ───────────────────────────────────────────────────────────────

    def _call(
        self,
        intent: str,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Call FunctionGemma with a single-turn intent + tool schemas.

        Requests logprobs for real confidence scores.
        Returns the raw API response dict.
        """
        import requests  # lazy import — keep module weight low

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": intent},
            ],
            "tools": tools,
            "max_tokens": 256,
            "temperature": 0.1,
            "logprobs": True,
            "top_logprobs": 5,
        }

        try:
            r = requests.post(
                f"{self.endpoint}/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            content = msg.get("content") or ""

            # UR may have parsed tool_calls natively — check both paths
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                # Native OpenAI format from UR
                return {
                    "tool_calls": tool_calls,
                    "content": content,
                    "logprobs": choice.get("logprobs"),
                }
            else:
                # FunctionGemma native format — keep as content for _build_result
                return {
                    "tool_calls": [],
                    "content": content,
                    "logprobs": choice.get("logprobs"),
                }

        except Exception as e:
            return {"tool_calls": [], "content": "", "error": str(e), "logprobs": None}

    def _build_result(
        self,
        response: Dict[str, Any],
        reasoner_tool: str,
        reasoner_params: Dict[str, Any],
    ) -> RouterResult:
        """
        Build a RouterResult from the raw response, comparing to Reasoner's choice.
        """
        raw_content = response.get("content", "")
        logprobs = response.get("logprobs")

        # Path 1: UR returned native tool_calls
        tool_calls = response.get("tool_calls") or []
        if tool_calls:
            tc = tool_calls[0]
            func = tc.get("function", {})
            fg_name = func.get("name", "")
            try:
                fg_params = json.loads(func.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                fg_params = {}
            confidence = ConfidenceExtractor.extract(logprobs, fg_name) or 0.0
            agreed = fg_name == reasoner_tool
            return RouterResult(
                tool_name=fg_name if agreed else reasoner_tool,
                params=fg_params if agreed else reasoner_params,
                confidence=confidence,
                agreed=agreed,
                raw_content=raw_content,
            )

        # Path 2: FunctionGemma native format in content
        parsed = FunctionGemmaOutputParser.parse(raw_content)
        if parsed:
            fg_name = parsed["name"]
            fg_params = parsed["arguments"]
            confidence = ConfidenceExtractor.extract(logprobs, fg_name) or 0.0
            agreed = fg_name == reasoner_tool
            return RouterResult(
                tool_name=fg_name if agreed else reasoner_tool,
                params=fg_params if agreed else reasoner_params,
                confidence=confidence,
                agreed=agreed,
                raw_content=raw_content,
            )

        # Path 3: Router returned nothing useful — zero confidence, use Reasoner's
        return RouterResult(
            tool_name=reasoner_tool,
            params=reasoner_params,
            confidence=0.0,
            agreed=False,
            raw_content=raw_content,
        )

    def __repr__(self) -> str:
        return (
            f"FunctionGemmaRouter("
            f"model={self.model}, "
            f"threshold={self.confidence_threshold})"
        )
