"""
Models — LlamaFarm integration for agent inference.

This module handles:
1. Loading llamafarm.yaml config
2. Calling LlamaFarm endpoint with tools + system prompt
3. Router model (FunctionGemma) for fast tool routing + param validation
4. Reasoning model (qwen/llama) for agent decisions
5. Fallback to OpenAI when needed

Two-model orchestration:
- Reasoner drives the loop (decides WHAT to do)
- Router validates/normalizes execution (decides HOW to do it precisely)
- Router is optional — single-model mode works identically to before
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class RouterResult:
    """
    Result from the router model (FunctionGemma) validation step.

    Confidence scoring (in priority order):
    1. Logprobs (real)  — exp(logprob) of the tool-name token in the response.
                          Requires LlamaFarm logprobs support. Most accurate.
    2. Heuristic        — fallback when logprobs unavailable:
                          agreed=True  → 0.95
                          agreed=False → 0.2
                          no tool call → 0.0
    """
    tool_name: str          # Tool FunctionGemma chose
    params: Dict[str, Any]  # Normalized/validated params
    confidence: float       # 0.0 – 1.0
    agreed: bool            # True if FunctionGemma picked same tool as Reasoner
    raw_response: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "params": self.params,
            "confidence": self.confidence,
            "agreed": self.agreed,
        }

try:
    import yaml
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False
    print("⚠️ PyYAML not installed - using minimal config")

try:
    import requests
    HAVE_REQUESTS = True
except ImportError:
    HAVE_REQUESTS = False
    print("⚠️ requests not installed - using mock responses")


class LlamaFarmConfig:
    """LlamaFarm configuration loaded from llamafarm.yaml."""
    
    def __init__(self, config_path: str = "llamafarm.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        
        # Extract key settings
        self.endpoint = self.config.get("endpoint", "http://localhost:8765/v1")
        self.models = self.config.get("models", {})
        self.tool_calling = self.config.get("tool_calling", {})
        self.inference = self.config.get("inference", {})
    
    def _load_config(self) -> Dict[str, Any]:
        """Load YAML config file."""
        if not self.config_path.exists():
            print(f"⚠️ Config not found: {self.config_path}, using defaults")
            return self._default_config()
        
        if not HAVE_YAML:
            print("⚠️ PyYAML not available, using defaults")
            return self._default_config()
        
        with open(self.config_path, "r") as f:
            return yaml.safe_load(f)
    
    def _default_config(self) -> Dict[str, Any]:
        """Default config when file missing or YAML unavailable."""
        return {
            "endpoint": "http://localhost:8765/v1",
            "models": {
                "router": {"model": "functiongemma:270m", "temperature": 0.1},
                "reasoning": {"model": "qwen2.5:8b", "temperature": 0.7}
            },
            "tool_calling": {"enabled": True, "pass_through": True},
            "inference": {"timeout_seconds": 30}
        }
    
    def get_model_config(self, model_type: str = "reasoning") -> Dict[str, Any]:
        """Get configuration for a specific model type."""
        return self.models.get(model_type, {})


class LlamaFarmClient:
    """Client for LlamaFarm inference API."""
    
    def __init__(self, config: LlamaFarmConfig):
        self.config = config
        self.endpoint = config.endpoint
        self.timeout = config.inference.get("timeout_seconds", 30)
    
    def call(
        self,
        prompt: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        model_type: str = "reasoning",
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        logprobs: bool = False,
        top_logprobs: int = 5,
    ) -> Dict[str, Any]:
        """
        Call LlamaFarm with tools + system prompt passed through.

        Args:
            prompt:        User message (simple mode)
            messages:      Full conversation history (advanced mode)
            model_type:    "router" | "reasoning" | "mobile" | "fallback"
            tools:         OpenAI-format tool definitions
            system_prompt: System prompt
            temperature:   Override default temperature
            logprobs:      Request log probabilities (for confidence scoring)
            top_logprobs:  How many top token candidates to return per position

        Returns:
            Response dict with content, tool_calls, logprobs, etc.
        """
        model_config = self.config.get_model_config(model_type)
        model_name = model_config.get("model", "qwen2.5:8b")
        temp = temperature or model_config.get("temperature", 0.7)
        max_tokens = model_config.get("max_tokens", 2048)

        # Build messages
        if messages is None:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
        else:
            if system_prompt and (not messages or messages[0].get("role") != "system"):
                messages = [{"role": "system", "content": system_prompt}] + messages

        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tokens,
        }

        if tools and self.config.tool_calling.get("pass_through", True):
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        # Logprobs — only when explicitly requested (router validation calls)
        if logprobs:
            payload["logprobs"] = True
            payload["top_logprobs"] = top_logprobs

        if not HAVE_REQUESTS:
            return self._mock_response(prompt, tools)

        try:
            response = requests.post(
                f"{self.endpoint}/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return self._parse_response(response.json())

        except requests.RequestException as e:
            print(f"⚠️ LlamaFarm API error: {e}")
            return {"error": str(e), "mock": True}
    
    def _parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse LlamaFarm response, including logprobs when present."""
        if "choices" not in response:
            return {"error": "Invalid response format"}

        choice = response["choices"][0]
        message = choice.get("message", {})

        return {
            "content": message.get("content", ""),
            "tool_calls": message.get("tool_calls", []),
            "finish_reason": choice.get("finish_reason", "stop"),
            "usage": response.get("usage", {}),
            # logprobs — present only when requested; None otherwise
            "logprobs": choice.get("logprobs"),
        }

    def _confidence_from_logprobs(
        self,
        logprobs_data: Optional[Dict[str, Any]],
        tool_name: str,
    ) -> Optional[float]:
        """
        Extract real confidence from logprobs for a specific tool name.

        Searches the token stream for the tool name and converts the log
        probability to a probability: confidence = exp(logprob).

        Handles two common cases:
        1. Tool name appears as a single token (e.g. "get_battery")
        2. Tool name is split across tokens (e.g. "get" + "_battery") —
           uses the first token's probability as a conservative estimate.

        Returns:
            float in [0, 1] if found, None if logprobs unavailable/unsupported.
        """
        if not logprobs_data:
            return None

        # Ollama/OpenAI format: logprobs.content is a list of token entries
        content = logprobs_data.get("content") or []

        for i, token_data in enumerate(content):
            token = token_data.get("token", "")
            logprob = token_data.get("logprob")

            # Full match — tool name is one token
            if tool_name in token and logprob is not None:
                return round(math.exp(logprob), 4)

            # Partial match — first token of a split tool name
            # Check if remaining tokens spell out the rest
            if tool_name.startswith(token.strip('"').strip()) and len(token.strip()) > 2:
                # Collect following tokens to see if they complete the name
                assembled = token.strip('"').strip()
                for j in range(i + 1, min(i + 5, len(content))):
                    assembled += content[j].get("token", "").strip('"')
                    if tool_name in assembled:
                        # Found it — use the first token's logprob
                        if logprob is not None:
                            return round(math.exp(logprob), 4)
                        break

        # Also check top_logprobs at each position for the tool name
        for token_data in content:
            for candidate in token_data.get("top_logprobs", []):
                if tool_name in candidate.get("token", ""):
                    lp = candidate.get("logprob")
                    if lp is not None:
                        return round(math.exp(lp), 4)

        return None  # logprobs present but tool name not found in token stream
    
    def validate_tool_call(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context_messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> "RouterResult":
        """
        Ask router model (FunctionGemma) to validate and normalize a tool call.

        The Reasoner has already decided WHAT to do. FunctionGemma's job here
        is to validate the params are correct and normalize any ambiguous values
        (e.g., "fly north 200m" → {"bearing": 0, "distance": 200, "unit": "meters"}).

        Args:
            tool_name: Tool the Reasoner decided to call
            params: Params the Reasoner provided
            context_messages: Recent conversation (last 3 messages for context)
            tools: All available tool schemas
            system_prompt: Optional system prompt

        Returns:
            RouterResult with confidence score and normalized params
        """
        # Request logprobs — real confidence scores when LlamaFarm supports them
        response = self.call(
            messages=context_messages,
            model_type="router",
            tools=tools,
            system_prompt=system_prompt,
            logprobs=True,
            top_logprobs=5,
        )

        tool_calls = response.get("tool_calls", [])

        if not tool_calls:
            # Router returned no tool call → zero confidence
            return RouterResult(
                tool_name=tool_name,
                params=params,
                confidence=0.0,
                agreed=False,
                raw_response=response,
            )

        fg_call = tool_calls[0]
        fg_func = fg_call.get("function", {})
        fg_name = fg_func.get("name", "")
        try:
            fg_params = json.loads(fg_func.get("arguments", "{}"))
        except (json.JSONDecodeError, TypeError):
            fg_params = params

        agreed = fg_name == tool_name

        # ── Confidence: real logprobs first, heuristic fallback ───────────────
        #
        # Real (logprobs available from LlamaFarm):
        #   confidence = exp(logprob of tool-name token)  → true probability
        #
        # Heuristic fallback (logprobs not yet supported):
        #   agreed  → 0.95   (FunctionGemma chose same tool, trust its params)
        #   disagreed → 0.2  (FunctionGemma chose differently, low trust)
        #
        logprobs_data = response.get("logprobs")
        real_confidence = self._confidence_from_logprobs(logprobs_data, fg_name)

        if real_confidence is not None:
            confidence = real_confidence
            source = "logprobs"
        else:
            confidence = 0.95 if agreed else 0.2
            source = "heuristic"

        print(
            f"   📊 Router confidence: {confidence:.0%} "
            f"({'✅ agreed' if agreed else '⚠️ disagreed'}, source={source})"
        )

        return RouterResult(
            tool_name=fg_name if agreed else tool_name,
            params=fg_params if agreed else params,
            confidence=confidence,
            agreed=agreed,
            raw_response=response,
        )

    def _mock_response(self, prompt: str, tools: Optional[List]) -> Dict[str, Any]:
        """Mock response when requests unavailable."""
        return {
            "content": f"[MOCK] Response to: {prompt[:50]}...",
            "tool_calls": [],
            "finish_reason": "stop",
            "mock": True
        }


class ModelLoader:
    """
    Unified model loader for MicroClaw.
    
    Handles:
    - Router model (FunctionGemma) for tool routing
    - Reasoning model (qwen/llama) for agent decisions
    - Fallback to OpenAI when needed
    """
    
    def __init__(self, config_path: str = "llamafarm.yaml"):
        self.config = LlamaFarmConfig(config_path)
        self.client = LlamaFarmClient(self.config)

        router_cfg = self.config.get_model_config("router")
        reasoning_model = self.config.get_model_config("reasoning").get("model", "")
        router_model = router_cfg.get("model", "")
        self._router_configured = bool(router_model and router_model != reasoning_model)
        # Read threshold from config; Agent.__init__ param overrides this if provided
        self.config_confidence_threshold: float = float(
            router_cfg.get("confidence_threshold", 0.85)
        )

        print("🦙 LlamaFarm initialized")
        print(f"   Endpoint: {self.config.endpoint}")
        if self._router_configured:
            print(f"   Router:    {router_model}  ← fast execution")
            print(f"   Reasoning: {reasoning_model}  ← agent loop")
        else:
            print(f"   Model:     {reasoning_model or router_model}  ← single-model mode")
    
    def route_tool(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Use router model (FunctionGemma) to route prompt to tool.
        Fast (<300ms) tool selection.
        """
        return self.client.call(
            prompt=prompt,
            model_type="router",
            tools=tools,
            system_prompt=system_prompt
        )
    
    def reason(
        self,
        prompt: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Use reasoning model for agent decisions.
        Can also make tool calls.
        
        Args:
            prompt: Simple user message (mutually exclusive with messages)
            messages: Full conversation history (for multi-turn reasoning)
            tools: Available tools
            system_prompt: System prompt
        """
        return self.client.call(
            prompt=prompt,
            messages=messages,
            model_type="reasoning",
            tools=tools,
            system_prompt=system_prompt
        )
    
    def has_router(self) -> bool:
        """True if a separate router model (FunctionGemma) is configured."""
        return self._router_configured

    def validate_tool_call(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context_messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> RouterResult:
        """
        Ask FunctionGemma to validate + normalize a tool call the Reasoner chose.
        Only call this when has_router() is True.
        """
        return self.client.validate_tool_call(
            tool_name=tool_name,
            params=params,
            context_messages=context_messages,
            tools=tools,
            system_prompt=system_prompt,
        )

    def fallback(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """Use fallback model (OpenAI) when local models fail or unavailable."""
        return self.client.call(
            prompt=prompt,
            model_type="fallback",
            tools=tools,
            system_prompt=system_prompt
        )

    def __repr__(self) -> str:
        mode = "two-model" if self._router_configured else "single-model"
        return f"ModelLoader(endpoint={self.config.endpoint}, mode={mode})"
