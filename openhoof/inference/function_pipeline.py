"""Two-stage function calling pipeline.

Architecture:
  Stage 1: FunctionGemma-270M (tiny, fast) → "Which tool(s) to call and with what args?"
  Stage 2: Bigger model (Qwen3-8B etc) → "Given the tool results, produce the final response"

This is the killer feature for edge devices:
- The 270M model handles ALL tool selection (runs in <100ms even on phones)
- The bigger model only needs to reason about results, not figure out tools
- As we collect data, we fine-tune the 270M to get better at OUR specific tools
- On tiny devices, the 270M can even run standalone with pre-defined tool chains

Pipeline modes:
  1. ROUTER: FunctionGemma picks tools → main model gets hint (current)
  2. FULL_DELEGATION: FunctionGemma handles entire tool selection + arg extraction
  3. CASCADE: FunctionGemma fast-path for simple calls, main model for complex ones
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

from .adapter import InferenceAdapter, ChatResponse, ToolCall

logger = logging.getLogger(__name__)

PIPELINE_DATA_DIR = Path.home() / ".openhoof" / "data" / "function_pipeline"


@dataclass
class PipelineResult:
    """Result from the two-stage pipeline."""
    tool_calls: List[ToolCall]
    confidence: float  # 0-1, how confident the router was
    router_latency_ms: float
    mode: str  # "router", "delegation", "cascade", "fallback"
    raw_router_output: str = ""


@dataclass
class ToolDefinition:
    """Simplified tool definition for the router."""
    name: str
    description: str
    parameters: Dict[str, Any]
    examples: List[Dict[str, Any]] = field(default_factory=list)  # Few-shot examples


class FunctionCallingPipeline:
    """Two-stage function calling: tiny router + big reasoner.
    
    The key insight: tool selection is a CLASSIFICATION problem, not a
    generation problem. A 270M model can learn to classify "which tool?"
    much faster than an 8B model can generate the full tool call from scratch.
    
    On edge devices (phones, Raspberry Pi, etc):
    - FunctionGemma runs locally (~50ms)
    - Tool execution happens locally
    - Only the final reasoning step needs a bigger model (or can be skipped
      for simple tool chains)
    """

    def __init__(
        self,
        inference: InferenceAdapter,
        router_model: str = "functiongemma",
        reasoner_model: str = "qwen3-8b",
        data_dir: Optional[Path] = None,
    ):
        self.inference = inference
        self.router_model = router_model
        self.reasoner_model = reasoner_model
        self.data_dir = data_dir or PIPELINE_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Training data paths
        self.training_path = self.data_dir / "training_data.jsonl"
        self.outcomes_path = self.data_dir / "outcomes.jsonl"
        self.stats_path = self.data_dir / "stats.json"
        
        # In-memory stats
        self._stats = self._load_stats()

    def _load_stats(self) -> Dict[str, Any]:
        if self.stats_path.exists():
            try:
                return json.loads(self.stats_path.read_text())
            except:
                pass
        return {
            "total_calls": 0,
            "router_successes": 0,
            "router_failures": 0,
            "fallbacks": 0,
            "avg_router_latency_ms": 0,
            "tool_selection_accuracy": 0,
        }

    def _save_stats(self):
        self.stats_path.write_text(json.dumps(self._stats, indent=2))

    def _build_router_prompt(
        self,
        user_message: str,
        tools: List[ToolDefinition],
        system_context: str = "",
    ) -> str:
        """Build optimized prompt for the tiny router model.
        
        FunctionGemma was trained on function calling, so we use its
        expected format: list functions, then ask which to call.
        """
        tool_specs = []
        for t in tools:
            props = t.parameters.get("properties", {})
            required = t.parameters.get("required", [])
            
            param_strs = []
            for pname, pspec in props.items():
                ptype = pspec.get("type", "string")
                req = " (required)" if pname in required else ""
                param_strs.append(f"    - {pname}: {ptype}{req}")
            
            params_text = "\n".join(param_strs) if param_strs else "    (no parameters)"
            
            tool_specs.append(
                f"  {t.name}: {t.description.split(chr(10))[0]}\n"
                f"  Parameters:\n{params_text}"
            )
        
        tools_block = "\n\n".join(tool_specs)
        
        # Add few-shot examples if available
        examples_block = ""
        for t in tools:
            for ex in t.examples[:2]:  # Max 2 examples per tool
                examples_block += f'\nExample: "{ex["input"]}" → {json.dumps(ex["output"])}'
        
        prompt = f"""You are a function calling assistant. Given the user's message and available functions, determine which function(s) to call with what arguments.

Available functions:
{tools_block}
{examples_block}

Respond ONLY with a JSON array of function calls. Each call has "name" and "arguments".
If no function is needed, respond with [].

User message: {user_message}

Function calls:"""
        
        return prompt

    async def route_tools(
        self,
        user_message: str,
        tools: List[ToolDefinition],
        system_context: str = "",
    ) -> PipelineResult:
        """Stage 1: Use tiny model to determine tool calls.
        
        Returns PipelineResult with tool_calls and metadata.
        """
        self._stats["total_calls"] = self._stats.get("total_calls", 0) + 1
        
        prompt = self._build_router_prompt(user_message, tools, system_context)
        
        start_time = time.time()
        
        try:
            response = await self.inference.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.router_model,
                stateless=True,
                rag_enabled=False,
                max_tokens=512,
                temperature=0.1,  # Low temp for deterministic tool selection
            )
            
            latency_ms = (time.time() - start_time) * 1000
            
            # Parse tool calls from response
            content = response.content.strip()
            tool_calls = self._parse_tool_calls(content, tools)
            
            if tool_calls is not None:
                self._stats["router_successes"] = self._stats.get("router_successes", 0) + 1
                
                # Update running average latency
                n = self._stats["router_successes"]
                avg = self._stats.get("avg_router_latency_ms", 0)
                self._stats["avg_router_latency_ms"] = avg + (latency_ms - avg) / n
                
                self._save_stats()
                
                # Log training data
                self._log_training_example(
                    user_message, tools, tool_calls, content, latency_ms, True
                )
                
                return PipelineResult(
                    tool_calls=tool_calls,
                    confidence=self._estimate_confidence(content),
                    router_latency_ms=latency_ms,
                    mode="delegation",
                    raw_router_output=content,
                )
            else:
                # Router failed to produce valid output
                self._stats["router_failures"] = self._stats.get("router_failures", 0) + 1
                self._save_stats()
                
                self._log_training_example(
                    user_message, tools, [], content, latency_ms, False
                )
                
                return PipelineResult(
                    tool_calls=[],
                    confidence=0.0,
                    router_latency_ms=latency_ms,
                    mode="fallback",
                    raw_router_output=content,
                )
                
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self._stats["fallbacks"] = self._stats.get("fallbacks", 0) + 1
            self._save_stats()
            
            logger.warning(f"Router failed ({latency_ms:.0f}ms): {e}")
            return PipelineResult(
                tool_calls=[],
                confidence=0.0,
                router_latency_ms=latency_ms,
                mode="fallback",
            )

    def _parse_tool_calls(
        self, content: str, tools: List[ToolDefinition]
    ) -> Optional[List[ToolCall]]:
        """Parse tool calls from router output."""
        # Extract JSON array
        try:
            # Find the JSON array in the response
            if "[" in content:
                start = content.index("[")
                # Find matching closing bracket
                depth = 0
                for i in range(start, len(content)):
                    if content[i] == "[":
                        depth += 1
                    elif content[i] == "]":
                        depth -= 1
                        if depth == 0:
                            json_str = content[start:i+1]
                            break
                else:
                    return None
                
                calls_data = json.loads(json_str)
                
                if not isinstance(calls_data, list):
                    return None
                
                # Validate against known tools
                valid_tool_names = {t.name for t in tools}
                tool_calls = []
                
                for i, call in enumerate(calls_data):
                    if isinstance(call, dict):
                        name = call.get("name", "")
                        args = call.get("arguments", call.get("args", call.get("parameters", {})))
                        
                        if name in valid_tool_names:
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except:
                                    args = {"raw": args}
                            
                            tool_calls.append(ToolCall(
                                id=f"router_{i}",
                                name=name,
                                arguments=args if isinstance(args, dict) else {},
                            ))
                
                return tool_calls if tool_calls else None
            
            return None
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"Failed to parse router output: {e}")
            return None

    def _estimate_confidence(self, content: str) -> float:
        """Estimate confidence based on output quality signals."""
        confidence = 0.5
        
        # Clean JSON output → higher confidence
        content = content.strip()
        if content.startswith("[") and content.endswith("]"):
            confidence += 0.3
        
        # Very short or very long → lower confidence
        if len(content) < 5 or len(content) > 2000:
            confidence -= 0.2
        
        # Contains explanation text → might be confused
        if any(word in content.lower() for word in ["however", "alternatively", "i think"]):
            confidence -= 0.2
        
        return max(0.0, min(1.0, confidence))

    def _log_training_example(
        self,
        user_message: str,
        tools: List[ToolDefinition],
        tool_calls: List[ToolCall],
        raw_output: str,
        success: bool,
        latency_ms: float = 0,
    ):
        """Log a training example for future fine-tuning."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "input": {
                "user_message": user_message[:500],
                "tools": [{"name": t.name, "description": t.description[:100]} for t in tools],
            },
            "output": {
                "tool_calls": [{"name": tc.name, "arguments": tc.arguments} for tc in tool_calls],
                "raw": raw_output[:500],
            },
            "metadata": {
                "success": success,
                "latency_ms": latency_ms,
                "model": self.router_model,
            }
        }
        
        try:
            with open(self.training_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.debug(f"Failed to log training example: {e}")

    def log_outcome(
        self,
        user_message: str,
        tool_name: str,
        args: Dict[str, Any],
        result_useful: bool,
        actual_tool_needed: Optional[str] = None,
    ):
        """Log whether a routed tool call was actually useful.
        
        This is CRITICAL for training — it tells us when the router was wrong.
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user_message": user_message[:500],
            "predicted_tool": tool_name,
            "predicted_args": args,
            "result_useful": result_useful,
            "actual_tool_needed": actual_tool_needed,
        }
        
        try:
            with open(self.outcomes_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.debug(f"Failed to log outcome: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        stats = dict(self._stats)
        
        # Count training examples
        if self.training_path.exists():
            stats["training_examples"] = sum(
                1 for _ in self.training_path.open() if _.strip()
            )
        else:
            stats["training_examples"] = 0
        
        if self.outcomes_path.exists():
            stats["outcome_examples"] = sum(
                1 for _ in self.outcomes_path.open() if _.strip()
            )
        else:
            stats["outcome_examples"] = 0
        
        # Readiness for fine-tuning
        stats["ready_for_training"] = stats["training_examples"] >= 100
        stats["training_data_path"] = str(self.training_path)
        
        return stats


class SyntheticTrainingGenerator:
    """Generate synthetic training data for the tool router.
    
    Uses the big model (Qwen3-8B) to generate diverse tool-calling examples,
    then formats them for FunctionGemma fine-tuning.
    """

    def __init__(
        self,
        inference: InferenceAdapter,
        teacher_model: str = "qwen3-8b",
        data_dir: Optional[Path] = None,
    ):
        self.inference = inference
        self.teacher_model = teacher_model
        self.data_dir = data_dir or PIPELINE_DATA_DIR
        self.synthetic_path = self.data_dir / "synthetic_training.jsonl"

    async def generate_examples(
        self,
        tools: List[ToolDefinition],
        num_examples: int = 50,
        categories: Optional[List[str]] = None,
    ) -> int:
        """Generate synthetic tool-calling examples using the teacher model.
        
        The teacher (big model) generates realistic user messages and the
        correct tool calls. These become training data for the student (tiny model).
        """
        if not categories:
            categories = [
                "simple direct request",
                "ambiguous request needing tool",
                "multi-tool request",
                "request that needs NO tools",
                "request with complex parameters",
                "conversational request hiding a tool need",
                "urgent/critical request",
                "follow-up question",
            ]

        tool_specs = []
        for t in tools:
            props = t.parameters.get("properties", {})
            required = t.parameters.get("required", [])
            param_list = [
                f"{k} ({v.get('type', 'string')}{'*' if k in required else ''})"
                for k, v in props.items()
            ]
            tool_specs.append(
                f"- {t.name}({', '.join(param_list)}): {t.description.split(chr(10))[0]}"
            )

        tools_text = "\n".join(tool_specs)
        generated = 0

        for category in categories:
            batch_size = max(1, num_examples // len(categories))
            
            prompt = f"""Generate {batch_size} realistic user messages for the category: "{category}"

Available tools:
{tools_text}

For each example, provide:
1. A realistic user message
2. The correct tool call(s) as JSON, or [] if no tool is needed

Format each example as a JSON object on its own line:
{{"user_message": "...", "tool_calls": [{{"name": "...", "arguments": {{...}}}}]}}

Generate diverse, realistic examples. Include edge cases."""

            try:
                response = await self.inference.chat_completion(
                    messages=[
                        {"role": "system", "content": "You generate training data for a function-calling AI. Output ONLY JSON lines, no other text."},
                        {"role": "user", "content": prompt}
                    ],
                    model=self.teacher_model,
                    stateless=True,
                    rag_enabled=False,
                    max_tokens=2048,
                    temperature=0.8,  # Higher temp for diversity
                )

                # Parse examples from response
                for line in response.content.strip().split("\n"):
                    line = line.strip()
                    if not line or not line.startswith("{"):
                        continue
                    
                    try:
                        example = json.loads(line)
                        if "user_message" in example and "tool_calls" in example:
                            # Validate tool names
                            valid_names = {t.name for t in tools}
                            valid_calls = [
                                c for c in example["tool_calls"]
                                if isinstance(c, dict) and c.get("name") in valid_names
                            ]
                            
                            training_entry = {
                                "timestamp": datetime.now().isoformat(),
                                "source": "synthetic",
                                "category": category,
                                "input": {
                                    "user_message": example["user_message"],
                                    "tools": [{"name": t.name, "description": t.description[:100]} for t in tools],
                                },
                                "output": {
                                    "tool_calls": valid_calls,
                                },
                                "metadata": {
                                    "teacher_model": self.teacher_model,
                                }
                            }
                            
                            with open(self.synthetic_path, "a") as f:
                                f.write(json.dumps(training_entry) + "\n")
                            
                            generated += 1
                    except json.JSONDecodeError:
                        continue

            except Exception as e:
                logger.warning(f"Failed to generate examples for '{category}': {e}")
                continue

        logger.info(f"Generated {generated} synthetic training examples")
        return generated

    def get_training_data_count(self) -> int:
        """Count total training examples available."""
        count = 0
        for path in [self.synthetic_path, self.data_dir / "training_data.jsonl"]:
            if path.exists():
                count += sum(1 for line in path.open() if line.strip())
        return count

    def export_for_finetuning(self, output_path: Optional[Path] = None) -> Path:
        """Export training data in a format suitable for LoRA fine-tuning.
        
        Outputs in the chat-ml / alpaca format that unsloth expects.
        """
        output_path = output_path or (self.data_dir / "finetune_dataset.jsonl")
        
        examples = []
        
        for path in [self.synthetic_path, self.data_dir / "training_data.jsonl"]:
            if not path.exists():
                continue
            for line in path.open():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    inp = entry.get("input", {})
                    out = entry.get("output", {})
                    
                    # Format as instruction/response pair
                    tools_desc = "\n".join(
                        f"- {t['name']}: {t.get('description', '')}"
                        for t in inp.get("tools", [])
                    )
                    
                    instruction = (
                        f"Available functions:\n{tools_desc}\n\n"
                        f"User message: {inp.get('user_message', '')}\n\n"
                        f"Which function(s) should be called? Respond with a JSON array."
                    )
                    
                    response = json.dumps(out.get("tool_calls", []))
                    
                    examples.append({
                        "instruction": instruction,
                        "input": "",
                        "output": response,
                    })
                except json.JSONDecodeError:
                    continue
        
        with open(output_path, "w") as f:
            for ex in examples:
                f.write(json.dumps(ex) + "\n")
        
        logger.info(f"Exported {len(examples)} examples to {output_path}")
        return output_path
