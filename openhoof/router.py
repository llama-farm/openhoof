"""
ToolRouter — model-agnostic tool routing for OpenHoof.

## Architecture

The Router is a small, fast model that does ONE thing: map an intent to a
tool call. It is NOT the reasoning engine. The Reasoner decides WHAT to do;
the Router validates and normalizes the parameters.

Any model can serve as the router — not just FunctionGemma. The router
auto-detects the output format and parses it accordingly:

    Format 1 — OpenAI native tool_calls (returned directly by UR for most models)
    Format 2 — <tool_call>{"name":...,"arguments":...}</tool_call>  (JSON-in-tag)
    Format 3 — <start_function_call>call:name{...}<end_function_call> (FunctionGemma native)

## Two operating modes

### Validation mode (default in agent.reason())
    Reasoner chose tool + params. Router validates/normalizes.
    High confidence → use Router's params.
    Low confidence  → fall back to Reasoner's params as-is.

### Routing mode (direct dispatch)
    Caller provides intent only. Router picks tool + params entirely.
    Used for: fast event-driven routing, streaming, keyword dispatch.

## Configuring the router model

In llamafarm.yaml:

    models:
      router:
        model: "unsloth/functiongemma-270m-it-GGUF"   # default
        # model: "unsloth/Qwen3-0.6B-GGUF"            # any small model
        # model: "local/my-finetuned-router"           # fine-tuned local model
        temperature: 0.1
        confidence_threshold: 0.85

Or directly:

    from openhoof.router import ToolRouter
    router = ToolRouter(endpoint="http://localhost:11540/v1", model="unsloth/Qwen3-0.6B-GGUF")

## Fine-tuning

Router training data is captured automatically via TrainingDataCapture.
Use FinetuneManager to convert captures → LlamaFarm SFT job:

    from openhoof.finetune import FinetuneManager
    ft = FinetuneManager(endpoint="http://localhost:11540/v1")
    job_id = ft.finetune_router(".microclaw/training", model="unsloth/functiongemma-270m-it")
"""

from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class RouterResult:
    """Result from a router model call."""
    tool_name: str
    params: Dict[str, Any]
    confidence: float           # 0.0–1.0; from logprobs when available, else 0.0
    agreed: bool                # True if Router chose same tool as Reasoner
    raw_content: str = ""       # Raw text output (for debugging / training capture)

    @property
    def trusted(self) -> bool:
        """True when confidence meets the router's configured threshold."""
        return self.confidence >= 0.85  # Agent overrides this via router.confidence_threshold


# ── Output parsers ────────────────────────────────────────────────────────────

class OutputParser:
    """
    Format-agnostic output parser — tries all known formats in order.

    Format priority:
      1. OpenAI tool_calls field      (structured, most reliable)
      2. <tool_call> JSON tags        (Qwen3, generic fine-tuned models)
      3. FunctionGemma native         (<start_function_call>call:name{...})
      4. Text function call syntax    (FunctionGemma fine-tuned with text format)
                                       e.g. drone_move(yaw_deg=-90)

    Format 4 is produced by FunctionGemma models fine-tuned with the "text"
    output format from SyntheticDataGenerator. Empirically the most accurate
    format for 270M models — simpler output pattern = better routing accuracy.

    Returns the first successful parse, or None if nothing matches.
    """

    @staticmethod
    def parse(response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse a router model response into {"name": str, "arguments": dict}.

        Args:
            response: Raw response dict from the model API

        Returns:
            {"name": tool_name, "arguments": params_dict} or None
        """
        # 1. OpenAI tool_calls field (UR returns this for most models natively)
        tool_calls = response.get("tool_calls") or []
        if tool_calls:
            tc = tool_calls[0]
            func = tc.get("function", {})
            name = func.get("name", "")
            try:
                args = json.loads(func.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                args = {}
            if name:
                return {"name": name, "arguments": args}

        content = response.get("content", "") or ""

        # 2. <tool_call>{...}</tool_call> JSON tags
        if "<tool_call>" in content:
            result = ToolCallTagParser.parse(content)
            if result:
                return result

        # 3. FunctionGemma native <start_function_call>call:name{...}
        if "<start_function_call>" in content:
            result = FunctionGemmaOutputParser.parse(content)
            if result:
                return result

        # 4. Text function call syntax: tool_name(param=value, ...)
        # Used by FunctionGemma models fine-tuned with text output format
        if content and re.match(r"^\w+\(", content.strip()):
            from .synth import parse_text_call
            result = parse_text_call(content.strip())
            if result and result.get("name"):
                return result

        return None


class ToolCallTagParser:
    """
    Parse <tool_call>{"name": ..., "arguments": ...}</tool_call> format.

    Used by: Qwen3, generic fine-tuned models, any model trained to output
    JSON tool calls in tag format.
    """

    _PATTERN = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)

    @classmethod
    def parse(cls, content: str) -> Optional[Dict[str, Any]]:
        m = cls._PATTERN.search(content)
        if not m:
            return None
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            return None
        name = data.get("name")
        if not name:
            return None
        args = data.get("arguments", data.get("parameters", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        return {"name": name, "arguments": args}

    @classmethod
    def parse_all(cls, content: str) -> List[Dict[str, Any]]:
        """Parse all <tool_call> blocks (for multi-call content)."""
        results = []
        for m in cls._PATTERN.finditer(content):
            try:
                data = json.loads(m.group(1).strip())
                name = data.get("name")
                if name:
                    args = data.get("arguments", {})
                    results.append({"name": name, "arguments": args})
            except json.JSONDecodeError:
                continue
        return results

    @classmethod
    def strip(cls, content: str) -> str:
        """Remove all <tool_call> blocks from content."""
        return cls._PATTERN.sub("", content).strip()


class FunctionGemmaOutputParser:
    """
    Parse FunctionGemma's native output format.

    Format:
        <start_function_call>call:TOOL_NAME{key:<escape>VALUE<escape>,...}<end_function_call>

    <escape>VALUE<escape> wraps string values; bare numbers are also supported.
    Only the first call is returned (router is single-dispatch by design).
    """

    _BLOCK = re.compile(
        r"<start_function_call>\s*call:(\w+)\{(.*?)\}\s*<end_function_call>",
        re.DOTALL,
    )
    _PARAM = re.compile(
        r"(\w+):\s*(?:<escape>(.*?)<escape>|(-?\d+(?:\.\d+)?))",
        re.DOTALL,
    )

    @classmethod
    def parse(cls, content: str) -> Optional[Dict[str, Any]]:
        m = cls._BLOCK.search(content)
        if not m:
            return None
        tool_name = m.group(1)
        args: Dict[str, Any] = {}
        for pm in cls._PARAM.finditer(m.group(2)):
            key = pm.group(1)
            str_val = pm.group(2)
            num_val = pm.group(3)
            if str_val is not None:
                args[key] = str_val
            elif num_val is not None:
                args[key] = float(num_val) if "." in num_val else int(num_val)
        return {"name": tool_name, "arguments": args}


# ── Confidence extraction ─────────────────────────────────────────────────────

class ConfidenceExtractor:
    """
    Extract real confidence from logprobs for a specific tool name.

    Works for any model that returns logprobs — model-agnostic.
    Searches the token stream for the tool name token(s) and converts
    the log probability to a probability: confidence = exp(logprob).
    """

    @staticmethod
    def extract(logprobs_data: Optional[Dict[str, Any]], tool_name: str) -> Optional[float]:
        if not logprobs_data:
            return None

        tokens = logprobs_data.get("content") or []

        for i, tok in enumerate(tokens):
            token = tok.get("token", "")
            logprob = tok.get("logprob")

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

        for tok in tokens:
            for candidate in tok.get("top_logprobs", []):
                if tool_name in candidate.get("token", ""):
                    lp = candidate.get("logprob")
                    if lp is not None:
                        return round(math.exp(lp), 4)

        return None


# ── ToolRouter ────────────────────────────────────────────────────────────────

class ToolRouter:
    """
    Model-agnostic tool router — validates and normalizes tool calls.

    Works with any model that can output tool calls in one of the
    supported formats (OpenAI tool_calls, <tool_call> JSON, or
    FunctionGemma native). The model is configured via llamafarm.yaml
    or passed directly.

    Typical usage (validation mode — called from agent.reason()):

        router = ToolRouter(
            endpoint="http://localhost:11540/v1",
            model="unsloth/functiongemma-270m-it-GGUF",   # or any other model
        )
        result = router.validate(
            tool_name="get_flight_data",
            params={"flight_id": "MAY101"},
            intent="Get fuel state for flight MAY101",
            tools=tool_schemas,
        )
        if result.trusted:
            use result.params      # Router normalized them
        else:
            use reasoner_params    # Router uncertain

    Direct routing mode:

        result = router.route(intent="Get fuel data for MAY101", tools=tool_schemas)
        print(result.tool_name, result.params)
    """

    DEFAULT_SYSTEM_PROMPT = (
        "You are a function router. "
        "Given a user request and available functions, select the correct function "
        "and return its parameters. Return a single function call only."
    )

    def __init__(
        self,
        endpoint: str,
        model: str,
        confidence_threshold: float = 0.85,
        temperature: float = 0.1,
        max_tokens: int = 128,
        timeout: int = 15,
        system_prompt: Optional[str] = None,
        strip_tool_descriptions: bool = True,
    ):
        """
        Args:
            endpoint:                LlamaFarm/UR base URL (e.g. http://localhost:11540/v1)
            model:                   Any model ID supported by the endpoint
                                     Examples:
                                       "unsloth/functiongemma-270m-it-GGUF"  (default router)
                                       "unsloth/Qwen3-0.6B-GGUF"            (small general model)
                                       "local/my-finetuned-router"           (custom fine-tune)
            confidence_threshold:    Min confidence to trust Router's params (default 0.85)
            temperature:             Sampling temperature (low = deterministic; default 0.1)
            max_tokens:              Max tokens for router response (default 128)
                                     Keep low — single tool calls are < 30 tokens.
                                     Low max_tokens prevents the base FunctionGemma model from
                                     chaining multiple <start_function_call> blocks.
            timeout:                 HTTP timeout in seconds
            system_prompt:           Override the default router system prompt
            strip_tool_descriptions: Remove description fields before sending to model.
                                     Default True for FunctionGemma 270M — the model learns
                                     routing purely from (input → output) pairs during SFT;
                                     long descriptions in the prompt cause hallucination.
                                     Set False for larger models that benefit from context.
        """
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.confidence_threshold = confidence_threshold
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT
        self.strip_tool_descriptions = strip_tool_descriptions

    @staticmethod
    def _slim_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Strip description fields from tool schemas for FunctionGemma inference.

        FunctionGemma 270M is a router — it learns the mapping purely from
        fine-tuning data, NOT from reading descriptions at inference time.
        Long descriptions cause the model to echo them back (hallucination).

        What we keep: name + parameter names/types (enough to format the call).
        What we drop: description, x-guidance, property descriptions.
        """
        slim = []
        for tool in tools:
            fn = tool.get("function", tool)
            slimmed_params: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}
            raw_params = fn.get("parameters", {})
            for prop_name, prop_def in raw_params.get("properties", {}).items():
                slimmed_params["properties"][prop_name] = {
                    k: v for k, v in prop_def.items()
                    if k in ("type", "enum")          # name + type only
                }
            slimmed_params["required"] = raw_params.get("required", [])

            slim.append({
                "type": "function",
                "function": {
                    "name": fn["name"],
                    # Single-word summary keeps the Jinja2 template sane
                    # but gives the model a minimal function registry to index from.
                    "description": fn.get("name", "").replace("_", " "),
                    "parameters": slimmed_params,
                },
            })
        return slim

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

        The Reasoner has decided WHAT tool to call. The Router checks whether
        the params are correct. If the Router agrees and is confident, its
        normalized params are used. Otherwise the Reasoner's params are kept.

        Args:
            tool_name:  Tool the Reasoner chose
            params:     Params the Reasoner supplied
            intent:     Single-step intent for this call (NOT the full task)
            tools:      All available tool schemas

        Returns:
            RouterResult — use .trusted to check whether to prefer Router's params
        """
        response = self._call(intent, tools)
        return self._build_result(response, reasoner_tool=tool_name, reasoner_params=params)

    def route(
        self,
        intent: str,
        tools: List[Dict[str, Any]],
    ) -> RouterResult:
        """
        Route an intent directly to a tool call without a prior Reasoner decision.

        Args:
            intent: User intent or agent step description
            tools:  All available tool schemas

        Returns:
            RouterResult with chosen tool and params
        """
        response = self._call(intent, tools)
        parsed = OutputParser.parse(response)
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

    def _call(self, intent: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Call the router model with a single-turn intent + tool schemas."""
        import requests

        inference_tools = self._slim_tools(tools) if self.strip_tool_descriptions else tools

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user",   "content": intent},
            ],
            "tools":       inference_tools,
            "max_tokens":  self.max_tokens,
            "temperature": self.temperature,
            "logprobs":    True,
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
            return {
                "tool_calls": msg.get("tool_calls") or [],
                "content":    msg.get("content") or "",
                "logprobs":   choice.get("logprobs"),
            }
        except Exception as e:
            return {"tool_calls": [], "content": "", "error": str(e), "logprobs": None}

    def _build_result(
        self,
        response: Dict[str, Any],
        reasoner_tool: str,
        reasoner_params: Dict[str, Any],
    ) -> RouterResult:
        """Build RouterResult from raw response, comparing to Reasoner's choice."""
        raw_content = response.get("content", "")
        parsed = OutputParser.parse(response)

        if not parsed:
            # Router returned nothing useful — zero confidence, Reasoner wins
            return RouterResult(
                tool_name=reasoner_tool,
                params=reasoner_params,
                confidence=0.0,
                agreed=False,
                raw_content=raw_content,
            )

        fg_name = parsed["name"]
        fg_params = parsed["arguments"]
        agreed = fg_name == reasoner_tool
        confidence = (
            ConfidenceExtractor.extract(response.get("logprobs"), fg_name)
            or 0.0
        )

        return RouterResult(
            tool_name=fg_name if agreed else reasoner_tool,
            params=fg_params if agreed else reasoner_params,
            confidence=confidence,
            agreed=agreed,
            raw_content=raw_content,
        )

    def __repr__(self) -> str:
        return (
            f"ToolRouter(model={self.model!r}, "
            f"threshold={self.confidence_threshold})"
        )


# ── Backward-compat alias ─────────────────────────────────────────────────────

#: Alias for callers that still reference FunctionGemmaRouter by name.
#: ToolRouter is the correct name going forward.
FunctionGemmaRouter = ToolRouter
