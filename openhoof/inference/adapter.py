"""Base inference adapter interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, AsyncIterator
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """A tool call from the model."""
    id: str
    name: str
    arguments: Dict[str, Any]
    
    def to_openai_format(self) -> Dict[str, Any]:
        import json
        args = self.arguments
        if isinstance(args, dict):
            args = json.dumps(args)
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": args
            }
        }


@dataclass
class ChatResponse:
    """Response from a chat completion request."""
    content: str
    model: str
    finish_reason: str = "stop"
    
    # Tool calls (if any)
    tool_calls: List[ToolCall] = field(default_factory=list)
    
    # Thinking content (for models that support it)
    thinking: Optional[str] = None
    
    # Token usage
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0
    
    @classmethod
    def from_openai_format(cls, data: Dict[str, Any]) -> "ChatResponse":
        """Parse from OpenAI API response format."""
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        usage = data.get("usage", {})
        thinking = data.get("thinking", {})
        
        # Parse tool calls
        tool_calls: List[ToolCall] = []
        for tc in message.get("tool_calls", []):
            func = tc.get("function", {})
            args = func.get("arguments", "{}")
            # Try to parse arguments as JSON
            import json
            try:
                args_dict = json.loads(args) if isinstance(args, str) else args
            except json.JSONDecodeError:
                args_dict = {"raw": args}
            
            tool_calls.append(ToolCall(
                id=tc.get("id", ""),
                name=func.get("name", ""),
                arguments=args_dict
            ))
        
        return cls(
            content=message.get("content", ""),
            model=data.get("model", "unknown"),
            finish_reason=choice.get("finish_reason", "stop"),
            tool_calls=tool_calls,
            thinking=thinking.get("content") if thinking else None,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )


class InferenceAdapter(ABC):
    """Abstract base class for inference adapters."""
    
    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> ChatResponse:
        """Send a chat completion request."""
        pass
    
    @abstractmethod
    async def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> AsyncIterator[str]:
        """Stream a chat completion request."""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the inference backend is available."""
        pass
