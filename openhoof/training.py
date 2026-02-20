"""
Training — Capture every tool call as JSONL training data.

Every tool call is logged in OpenAI chat completion format:
    {
        "messages": [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "", "tool_calls": [...]},
            {"role": "tool", "tool_call_id": "...", "content": "..."}
        ]
    }

This data can be used to:
1. Fine-tune FunctionGemma (fast tool routing)
2. Fine-tune reasoning models (task-specific behavior)
3. Analyze agent performance
4. Reproduce failures

Integration with LlamaFarm fine-tuning pipeline.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class TrainingDataCapture:
    """Capture every tool call as training data."""
    
    def __init__(self, output_dir: str = ".microclaw/training"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # One file per day
        today = datetime.now().strftime("%Y-%m-%d")
        self.output_file = self.output_dir / f"tool_calls_{today}.jsonl"
        
        self.captured_count = 0
    
    def capture(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: Dict[str, Any],
        context: Optional[str] = None,
        system_prompt: Optional[str] = None
    ):
        """
        Capture a tool call as training data.
        
        Args:
            tool_name: Name of the tool called
            params: Parameters passed to the tool
            result: Result returned by the tool
            context: Optional user message/context that triggered the call
            system_prompt: Optional system prompt (from Soul)
        """
        # Build OpenAI-style chat completion format
        messages = []
        
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })
        
        if context:
            messages.append({
                "role": "user",
                "content": context
            })
        
        # Assistant's tool call
        tool_call_id = f"call_{int(time.time() * 1000)}"
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(params)
                    }
                }
            ]
        })
        
        # Tool result
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(result)
        })
        
        # Write to JSONL
        entry = {
            "messages": messages,
            "timestamp": time.time(),
            "tool_name": tool_name,
            "success": result.get("status") != "error"
        }
        
        with open(self.output_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        
        self.captured_count += 1
    
    def load(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Load captured training data."""
        if not self.output_file.exists():
            return []
        
        data = []
        with open(self.output_file, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                
                try:
                    entry = json.loads(line)
                    data.append(entry)
                    
                    if limit and len(data) >= limit:
                        break
                except json.JSONDecodeError:
                    continue
        
        return data
    
    def stats(self) -> Dict[str, Any]:
        """Get training data statistics."""
        total_lines = 0
        if self.output_file.exists():
            with open(self.output_file, "r") as f:
                total_lines = sum(1 for _ in f)
        
        return {
            "output_file": str(self.output_file),
            "captured_today": total_lines,
            "total_captured": self.captured_count,
        }
    
    def __repr__(self) -> str:
        return f"TrainingDataCapture(captured={self.captured_count}, file={self.output_file.name})"
