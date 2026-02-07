"""LlamaFarm inference adapter."""

import aiohttp
from typing import List, Dict, Any, Optional, AsyncIterator
import logging
import json

from .adapter import InferenceAdapter, ChatResponse

logger = logging.getLogger(__name__)


class LlamaFarmAdapter(InferenceAdapter):
    """Adapter for LlamaFarm API."""
    
    def __init__(
        self,
        base_url: str = "http://localhost:14345",
        namespace: str = "atmosphere",
        project: str = "agents",
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.namespace = namespace
        self.project = project
        self.api_key = api_key
        self.default_model = default_model
    
    def _get_url(self) -> str:
        return f"{self.base_url}/v1/projects/{self.namespace}/{self.project}/chat/completions"
    
    def _get_headers(self, session_id: Optional[str] = None, stateless: bool = False) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        if session_id:
            headers["X-Session-ID"] = session_id
        elif stateless:
            headers["X-No-Session"] = "true"
        
        return headers
    
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> ChatResponse:
        """Send a chat completion request to LlamaFarm."""
        
        # Build request body
        body: Dict[str, Any] = {
            "messages": messages,
            "stream": False,
        }
        
        # Model selection
        if kwargs.get("model") or self.default_model:
            body["model"] = kwargs.get("model") or self.default_model
        
        # Temperature and sampling
        if "temperature" in kwargs:
            body["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            body["max_tokens"] = kwargs["max_tokens"]
        if "top_p" in kwargs:
            body["top_p"] = kwargs["top_p"]
        
        # RAG control (usually OFF for agents)
        body["rag_enabled"] = kwargs.get("rag_enabled", False)
        if kwargs.get("database"):
            body["database"] = kwargs["database"]
        if kwargs.get("rag_top_k"):
            body["rag_top_k"] = kwargs["rag_top_k"]
        
        # Thinking/reasoning (for Qwen3, etc.)
        if kwargs.get("think"):
            body["think"] = True
            body["thinking_budget"] = kwargs.get("thinking_budget", 512)
        
        # Variables for template substitution
        if kwargs.get("variables"):
            body["variables"] = kwargs["variables"]
        
        # Tools
        if tools:
            body["tools"] = tools
        
        # Make request
        headers = self._get_headers(
            session_id=kwargs.get("session_id"),
            stateless=kwargs.get("stateless", False)
        )
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._get_url(),
                    json=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"LlamaFarm error {resp.status}: {error_text}")
                        raise Exception(f"LlamaFarm error {resp.status}: {error_text}")
                    
                    data = await resp.json()
                    return ChatResponse.from_openai_format(data)
        
        except aiohttp.ClientError as e:
            logger.error(f"LlamaFarm connection error: {e}")
            raise
    
    async def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> AsyncIterator[str]:
        """Stream a chat completion request."""
        
        # Build request body (same as non-streaming)
        body: Dict[str, Any] = {
            "messages": messages,
            "stream": True,
        }
        
        if kwargs.get("model") or self.default_model:
            body["model"] = kwargs.get("model") or self.default_model
        
        body["rag_enabled"] = kwargs.get("rag_enabled", False)
        
        if kwargs.get("think"):
            body["think"] = True
            body["thinking_budget"] = kwargs.get("thinking_budget", 512)
        
        if tools:
            body["tools"] = tools
        
        headers = self._get_headers(
            session_id=kwargs.get("session_id"),
            stateless=kwargs.get("stateless", False)
        )
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._get_url(),
                    json=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=300)
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise Exception(f"LlamaFarm error {resp.status}: {error_text}")
                    
                    async for line in resp.content:
                        line_str = line.decode("utf-8").strip()
                        if line_str.startswith("data: "):
                            data_str = line_str[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
        
        except aiohttp.ClientError as e:
            logger.error(f"LlamaFarm streaming error: {e}")
            raise
    
    async def health_check(self) -> bool:
        """Check if LlamaFarm is available."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.warning(f"LlamaFarm health check failed: {e}")
            return False
