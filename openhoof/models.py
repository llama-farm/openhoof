"""
Models — LlamaFarm integration for agent inference.

This module handles:
1. Loading llamafarm.yaml config
2. Calling LlamaFarm endpoint with tools + system prompt
3. Router model (FunctionGemma) for fast tool routing
4. Reasoning model (qwen/llama) for agent decisions
5. Fallback to OpenAI when needed

LlamaFarm now accepts tools + prompts passed through in the request,
so we just need to define models and make API calls.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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
        prompt: str,
        model_type: str = "reasoning",
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Call LlamaFarm with tools + system prompt passed through.
        
        Args:
            prompt: User message
            model_type: "router" or "reasoning" or "mobile" or "fallback"
            tools: OpenAI-format tool definitions (passed through)
            system_prompt: System prompt (passed through)
            temperature: Override default temperature
        
        Returns:
            Response dict with content, tool_calls, etc.
        """
        model_config = self.config.get_model_config(model_type)
        model_name = model_config.get("model", "qwen2.5:8b")
        temp = temperature or model_config.get("temperature", 0.7)
        max_tokens = model_config.get("max_tokens", 2048)
        
        # Build OpenAI-compatible request
        messages = []
        
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })
        
        messages.append({
            "role": "user",
            "content": prompt
        })
        
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tokens,
        }
        
        # Pass tools through if provided
        if tools and self.config.tool_calling.get("pass_through", True):
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        
        # Make API call
        if not HAVE_REQUESTS:
            return self._mock_response(prompt, tools)
        
        try:
            response = requests.post(
                f"{self.endpoint}/chat/completions",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            return self._parse_response(response.json())
        
        except requests.RequestException as e:
            print(f"⚠️ LlamaFarm API error: {e}")
            return {"error": str(e), "mock": True}
    
    def _parse_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse LlamaFarm response."""
        if "choices" not in response:
            return {"error": "Invalid response format"}
        
        choice = response["choices"][0]
        message = choice.get("message", {})
        
        return {
            "content": message.get("content", ""),
            "tool_calls": message.get("tool_calls", []),
            "finish_reason": choice.get("finish_reason", "stop"),
            "usage": response.get("usage", {}),
        }
    
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
        
        print(f"🦙 LlamaFarm initialized")
        print(f"   Endpoint: {self.config.endpoint}")
        print(f"   Router: {self.config.get_model_config('router').get('model', 'N/A')}")
        print(f"   Reasoning: {self.config.get_model_config('reasoning').get('model', 'N/A')}")
    
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
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Use reasoning model for agent decisions.
        Can also make tool calls.
        """
        return self.client.call(
            prompt=prompt,
            model_type="reasoning",
            tools=tools,
            system_prompt=system_prompt
        )
    
    def fallback(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Use fallback model (OpenAI) when local models fail or unavailable.
        """
        return self.client.call(
            prompt=prompt,
            model_type="fallback",
            tools=tools,
            system_prompt=system_prompt
        )
    
    def __repr__(self) -> str:
        return f"ModelLoader(endpoint={self.config.endpoint})"
