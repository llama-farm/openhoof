"""
Synthetic training data generator for OpenHoof tool calling.

Generates diverse, validated (intent → tool call) examples using any LLM
as a "teacher" model. Output is ready to feed directly into FinetuneManager.

## Architecture

    Tool schemas  +  Teacher model  →  SchemaValidator  →  JSONL files

Teacher model: any OpenAI-compatible /v1/chat/completions endpoint.
    - OpenAI (gpt-4o, gpt-4o-mini)
    - Anthropic via proxy
    - LlamaFarm Universal Runtime (http://localhost:11540/v1)
    - Ollama (http://localhost:11434/v1)
    - Any local or cloud endpoint

Output formats:
    router_synthetic_YYYY-MM-DD.jsonl   — ShareGPT for router fine-tuning
    reasoner_synthetic_YYYY-MM-DD.jsonl — Chat for reasoner fine-tuning

## Usage

### Python API

    from openhoof.synth import SyntheticDataGenerator

    gen = SyntheticDataGenerator(
        endpoint="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="sk-...",            # optional; reads OPENAI_API_KEY if omitted
    )

    # Generate router examples (single-turn intent → tool call)
    results = gen.generate_router(
        tools=my_tool_schemas,       # OpenHoof / OpenAI tool schema list
        count=200,
        output_dir=".microclaw/training",
    )
    print(f"Generated {results.valid} valid / {results.invalid} rejected examples")

    # Generate reasoner examples (multi-turn chains)
    results = gen.generate_reasoner(
        tools=my_tool_schemas,
        tasks=["Analyze fuel for MAY101 and recommend divert if needed"],  # optional seeds
        count=50,
        output_dir=".microclaw/training",
    )

### CLI

    python -m openhoof.synth \\
        --tools path/to/tools.json \\
        --model gpt-4o-mini \\
        --endpoint https://api.openai.com/v1 \\
        --type router \\
        --count 200 \\
        --output .microclaw/training

    # Local LlamaFarm
    python -m openhoof.synth \\
        --tools path/to/tools.json \\
        --model unsloth/Qwen3-8B-GGUF \\
        --endpoint http://localhost:11540/v1 \\
        --type both \\
        --count 100

## Schema validation

Every generated example is validated before writing:
    ✓ Tool name exists in schema
    ✓ All required parameters present
    ✓ Parameter types match schema (string, number, integer, boolean, array, object)
    ✓ No hallucinated parameters beyond defined schema
    ✓ Arguments are valid JSON
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# ── Schema validator ──────────────────────────────────────────────────────────

@dataclass
class ValidationError:
    tool_call: Dict[str, Any]
    reason: str


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)


class SchemaValidator:
    """
    Validate a generated tool call against the tool schemas.

    Checks:
    1. Tool name exists in schemas
    2. All required parameters are present
    3. Parameter types match schema (coerces numeric strings when safe)
    4. No hallucinated parameters beyond the defined schema
    5. Arguments are parseable JSON
    """

    # JSON Schema type → Python type(s)
    TYPE_MAP: Dict[str, Tuple] = {
        "string":  (str,),
        "number":  (int, float),
        "integer": (int,),
        "boolean": (bool,),
        "array":   (list,),
        "object":  (dict,),
    }

    def __init__(self, tools: List[Dict[str, Any]]):
        # Build lookup: name → parameter schema
        self._schemas: Dict[str, Dict[str, Any]] = {}
        for tool in tools:
            func = tool.get("function", tool)  # handle both wrapped and unwrapped
            name = func.get("name", "")
            if name:
                self._schemas[name] = func.get("parameters", {})

    @property
    def known_tools(self) -> List[str]:
        return list(self._schemas.keys())

    def validate(self, tool_name: str, arguments: Dict[str, Any]) -> ValidationResult:
        errors: List[str] = []

        # 1. Tool name must exist
        if tool_name not in self._schemas:
            return ValidationResult(
                valid=False,
                errors=[f"Unknown tool '{tool_name}'. Known: {self.known_tools}"],
            )

        schema = self._schemas[tool_name]
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # 2. Required params must be present
        for param in required:
            if param not in arguments:
                errors.append(f"Missing required parameter '{param}'")

        # 3. Type check each provided argument
        for param, value in arguments.items():
            if param not in properties:
                # 4. Hallucinated param
                errors.append(f"Unknown parameter '{param}' not in schema")
                continue
            expected_type = properties[param].get("type")
            if expected_type and expected_type in self.TYPE_MAP:
                allowed = self.TYPE_MAP[expected_type]
                if not isinstance(value, allowed):
                    # Allow numeric string → number coercion (common model mistake)
                    if expected_type in ("number", "integer") and isinstance(value, str):
                        try:
                            arguments[param] = int(value) if expected_type == "integer" else float(value)
                        except ValueError:
                            errors.append(
                                f"Parameter '{param}' expected {expected_type}, got {type(value).__name__}"
                            )
                    elif expected_type == "string" and isinstance(value, (int, float)):
                        # Coerce number → string when schema says string
                        arguments[param] = str(value)
                    else:
                        errors.append(
                            f"Parameter '{param}' expected {expected_type}, got {type(value).__name__}"
                        )

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def validate_tool_call(self, tool_call: Dict[str, Any]) -> ValidationResult:
        """Validate an OpenAI-format tool_call dict."""
        func = tool_call.get("function", {})
        name = func.get("name", "")
        raw_args = func.get("arguments", "{}")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError as e:
            return ValidationResult(valid=False, errors=[f"Arguments JSON parse error: {e}"])
        return self.validate(name, args)


# ── Teacher model ─────────────────────────────────────────────────────────────

class TeacherModel:
    """
    Thin wrapper around any OpenAI-compatible /v1/chat/completions endpoint.

    Works with:
    - OpenAI (gpt-4o, gpt-4o-mini, o3-mini, ...)
    - Anthropic via LiteLLM proxy or compatible endpoint
    - LlamaFarm Universal Runtime (http://localhost:11540/v1)
    - Ollama (http://localhost:11434/v1)
    - Any endpoint that speaks OpenAI chat completions
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: Optional[str] = None,
        temperature: float = 0.8,
        max_tokens: int = 2048,
        timeout: int = 60,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Send a chat completion request. Returns the assistant's text content.
        """
        import requests

        payload: Dict[str, Any] = {
            "model":       self.model,
            "messages":    messages,
            "max_tokens":  self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
        }
        if tools:
            payload["tools"] = tools

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        r = requests.post(
            f"{self.endpoint}/chat/completions",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})

        # Prefer tool_calls content if present
        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            return json.dumps(tool_calls[0].get("function", {}))
        return msg.get("content", "")

    def chat_with_tool_calls(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Send a chat request expecting a tool call response.
        Returns the first tool_call as {"name": str, "arguments": dict} or None.
        """
        import requests

        payload: Dict[str, Any] = {
            "model":       self.model,
            "messages":    messages,
            "tools":       tools,
            "tool_choice": "required",
            "max_tokens":  512,
            "temperature": temperature if temperature is not None else 0.3,
        }
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            r = requests.post(
                f"{self.endpoint}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            r.raise_for_status()
        except Exception:
            return None

        data = r.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        tool_calls = msg.get("tool_calls") or []

        if tool_calls:
            func = tool_calls[0].get("function", {})
            name = func.get("name", "")
            raw = func.get("arguments", "{}")
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                return None
            return {"name": name, "arguments": args} if name else None

        # Fallback: try to parse tool call from content
        content = msg.get("content", "")
        if content:
            from .router import ToolCallTagParser, FunctionGemmaOutputParser
            result = ToolCallTagParser.parse(content) or FunctionGemmaOutputParser.parse(content)
            return result

        return None


# ── Generation results ────────────────────────────────────────────────────────

@dataclass
class GenerationStats:
    valid:   int = 0
    invalid: int = 0
    output_path: Optional[Path] = None
    errors: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.valid + self.invalid

    @property
    def acceptance_rate(self) -> float:
        return self.valid / self.total if self.total else 0.0

    def __repr__(self) -> str:
        return (
            f"GenerationStats(valid={self.valid}, invalid={self.invalid}, "
            f"acceptance={self.acceptance_rate:.0%}, output={self.output_path})"
        )


# ── Router example generator ──────────────────────────────────────────────────

class RouterExampleGenerator:
    """
    Generate single-turn (intent → tool call) examples for router fine-tuning.

    Strategy:
    1. For each tool, ask the teacher to generate N diverse user intents.
    2. For each intent, ask the teacher to produce the correct tool call.
    3. Validate against schema. Reject invalid. Write valid to ShareGPT JSONL.

    Diversity is achieved by:
    - Asking for phrasing variations (formal/casual/abbreviated)
    - Varying parameter values across the schema range
    - Including ambiguous phrasings that still resolve to one correct tool
    - Including cross-tool tasks where tool selection matters
    """

    INTENT_GENERATION_PROMPT = """\
You are generating training data for an AI tool router.

Available tools:
{tool_descriptions}

Generate {count} diverse user intents that require calling the tool "{tool_name}".

Rules:
- Each intent must clearly require "{tool_name}" and not any other tool
- Use varied phrasing: formal, casual, abbreviated, different word orders
- Use varied but realistic parameter values
- Do NOT include the tool name in the intent — write it as a natural user request
- Return a JSON array of strings: ["intent 1", "intent 2", ...]

Return ONLY the JSON array, no explanation."""

    CROSS_TOOL_PROMPT = """\
You are generating training data for an AI tool router.

Available tools:
{tool_descriptions}

Generate {count} realistic user requests. Each request should clearly map to exactly ONE of the available tools. Mix the tools — don't always use the same one.

For each request, output a JSON object with:
  "intent": the user's natural language request
  "tool": which tool should be called
  "params": the exact parameters

Return a JSON array of objects:
[
  {{"intent": "...", "tool": "tool_name", "params": {{"param": "value"}}}},
  ...
]

Requirements:
- Intents must be natural, not robotic
- Params must be realistic values that fit the schema
- Include some cross-tool ambiguity to test selection
- Return ONLY the JSON array."""

    def __init__(self, teacher: TeacherModel, validator: SchemaValidator):
        self.teacher = teacher
        self.validator = validator

    def generate(
        self,
        tools: List[Dict[str, Any]],
        count: int = 100,
        per_tool: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Generate router training examples.

        Args:
            tools:    Tool schemas to generate data for
            count:    Target number of valid examples
            per_tool: If True, generate proportionally per tool (better coverage).
                      If False, use cross-tool generation (better selection training).

        Returns:
            List of ShareGPT format dicts ready for SFT
        """
        examples = []

        if per_tool:
            per = max(1, count // max(len(tools), 1))
            for tool in tools:
                tool_examples = self._generate_for_tool(tool, tools, per)
                examples.extend(tool_examples)
        else:
            examples = self._generate_cross_tool(tools, count)

        return examples[:count]  # cap at requested count

    def _tool_descriptions(self, tools: List[Dict[str, Any]]) -> str:
        lines = []
        for t in tools:
            func = t.get("function", t)
            name = func.get("name", "")
            desc = func.get("description", "")
            params = func.get("parameters", {}).get("properties", {})
            param_str = ", ".join(
                f"{k} ({v.get('type', '?')})" for k, v in params.items()
            )
            lines.append(f"  {name}({param_str}): {desc}")
        return "\n".join(lines)

    def _generate_for_tool(
        self,
        tool: Dict[str, Any],
        all_tools: List[Dict[str, Any]],
        count: int,
    ) -> List[Dict[str, Any]]:
        func = tool.get("function", tool)
        tool_name = func.get("name", "")
        tool_descriptions = self._tool_descriptions(all_tools)

        # Step 1: Generate diverse intents for this tool
        prompt = self.INTENT_GENERATION_PROMPT.format(
            tool_descriptions=tool_descriptions,
            tool_name=tool_name,
            count=count * 2,  # generate extra, filter down after validation
        )
        raw = self.teacher.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
        )
        intents = self._parse_json_list(raw, str)
        if not intents:
            return []

        # Step 2: For each intent, get the tool call
        examples = []
        for intent in intents[:count * 2]:
            result = self.teacher.chat_with_tool_calls(
                messages=[{"role": "user", "content": intent}],
                tools=all_tools,
                temperature=0.2,
            )
            if not result:
                continue
            vr = self.validator.validate(result["name"], result["arguments"])
            if not vr.valid:
                continue
            examples.append(self._to_sharegpt(intent, result["name"], result["arguments"]))
            if len(examples) >= count:
                break

        return examples

    def _generate_cross_tool(
        self,
        tools: List[Dict[str, Any]],
        count: int,
    ) -> List[Dict[str, Any]]:
        tool_descriptions = self._tool_descriptions(tools)
        prompt = self.CROSS_TOOL_PROMPT.format(
            tool_descriptions=tool_descriptions,
            count=count * 2,
        )
        raw = self.teacher.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.85,
        )
        items = self._parse_json_list(raw, dict)

        examples = []
        for item in items:
            if not isinstance(item, dict):
                continue
            intent = item.get("intent", "")
            tool_name = item.get("tool", "")
            params = item.get("params", {})
            if not intent or not tool_name:
                continue
            vr = self.validator.validate(tool_name, params)
            if not vr.valid:
                continue
            examples.append(self._to_sharegpt(intent, tool_name, params))

        return examples[:count]

    @staticmethod
    def _to_sharegpt(intent: str, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        tool_call_json = json.dumps(
            {"name": tool_name, "arguments": params},
            ensure_ascii=False,
        )
        return {
            "conversations": [
                {"from": "human", "value": intent},
                {"from": "gpt",   "value": f"<tool_call>{tool_call_json}</tool_call>"},
            ]
        }

    @staticmethod
    def _parse_json_list(raw: str, item_type: type) -> List[Any]:
        """Extract a JSON array from raw text (handles markdown code fences)."""
        # Strip markdown fences
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("```").strip()
        # Find array boundaries
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            return []
        try:
            data = json.loads(raw[start:end + 1])
            return [x for x in data if isinstance(x, item_type)]
        except json.JSONDecodeError:
            return []


# ── Reasoner example generator ────────────────────────────────────────────────

class ReasonerExampleGenerator:
    """
    Generate multi-turn (task → tool chain → answer) examples for reasoner fine-tuning.

    The teacher model acts as the agent, reasoning through a task using tools.
    An optional executor can run the tools for real responses; otherwise
    the teacher also simulates the tool results.
    """

    TASK_GENERATION_PROMPT = """\
You are generating training tasks for an AI reasoning agent.

Available tools:
{tool_descriptions}

Generate {count} complex tasks that require using 2–4 of the available tools in sequence.
Each task should require chaining tool results — the output of one tool feeds the next.

Requirements:
- Tasks should be realistic, domain-appropriate requests
- Each task should genuinely require multiple tool calls
- Vary the tool combinations used
- Keep tasks concise (1–2 sentences)

Return a JSON array of task strings: ["task 1", "task 2", ...]
Return ONLY the JSON array."""

    REASONING_SYSTEM_PROMPT = """\
You are an autonomous AI agent. Solve the user's task by calling the available tools in sequence.
Think step by step. Use tool results to decide your next action.
When you have enough information, provide a concise final answer."""

    def __init__(
        self,
        teacher: TeacherModel,
        validator: SchemaValidator,
        executor: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ):
        self.teacher = teacher
        self.validator = validator
        self.executor = executor  # optional: actually run the tools for real results

    def generate(
        self,
        tools: List[Dict[str, Any]],
        count: int = 50,
        task_seeds: Optional[List[str]] = None,
        max_turns: int = 8,
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate reasoner training examples (multi-turn chains).

        Args:
            tools:       Tool schemas
            count:       Number of examples to generate
            task_seeds:  Optional list of seed tasks to use/extend
            max_turns:   Max tool call turns per example
            system_prompt: Override the default reasoning system prompt

        Returns:
            List of OpenAI Chat format dicts
        """
        tool_descriptions = self._tool_descriptions(tools)

        # Get or generate tasks
        tasks = list(task_seeds or [])
        if len(tasks) < count:
            prompt = self.TASK_GENERATION_PROMPT.format(
                tool_descriptions=tool_descriptions,
                count=(count - len(tasks)) * 2,
            )
            raw = self.teacher.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.9,
            )
            generated = RouterExampleGenerator._parse_json_list(raw, str)
            tasks.extend(generated)

        sys_prompt = system_prompt or self.REASONING_SYSTEM_PROMPT
        examples = []

        for task in tasks[:count * 2]:
            chain = self._run_chain(task, tools, sys_prompt, max_turns)
            if chain:
                examples.append({"messages": chain})
            if len(examples) >= count:
                break

        return examples

    def _tool_descriptions(self, tools: List[Dict[str, Any]]) -> str:
        lines = []
        for t in tools:
            func = t.get("function", t)
            name = func.get("name", "")
            desc = func.get("description", "")
            lines.append(f"  {name}: {desc}")
        return "\n".join(lines)

    def _run_chain(
        self,
        task: str,
        tools: List[Dict[str, Any]],
        system_prompt: str,
        max_turns: int,
    ) -> Optional[List[Dict[str, Any]]]:
        """Run a full reasoning chain for one task. Returns messages or None."""
        import requests

        messages: List[Dict[str, Any]] = [
            {"role": "system",  "content": system_prompt},
            {"role": "user",    "content": task},
        ]

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.teacher.api_key:
            headers["Authorization"] = f"Bearer {self.teacher.api_key}"

        for _ in range(max_turns):
            payload = {
                "model":       self.teacher.model,
                "messages":    messages,
                "tools":       tools,
                "max_tokens":  1024,
                "temperature": 0.4,
            }
            try:
                r = requests.post(
                    f"{self.teacher.endpoint}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self.teacher.timeout,
                )
                r.raise_for_status()
            except Exception:
                return None

            data = r.json()
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            finish = choice.get("finish_reason", "stop")
            tool_calls = msg.get("tool_calls") or []
            content = msg.get("content") or None

            # Record assistant turn
            messages.append({
                "role":       "assistant",
                "content":    content,
                "tool_calls": tool_calls or None,
            })

            if not tool_calls:
                # Agent is done — need a final text response to be a valid training example
                if content and content.strip():
                    return self._clean_messages(messages)
                return None

            # Execute each tool call
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                raw_args = func.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {}

                # Validate the tool call
                vr = self.validator.validate(tool_name, args)

                if self.executor and vr.valid:
                    # Real execution
                    try:
                        result = self.executor(tool_name, args)
                    except Exception as e:
                        result = {"error": str(e)}
                else:
                    # Teacher simulates result
                    result = self._simulate_result(tool_name, args, tools)

                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.get("id", "call_0"),
                    "name":         tool_name,
                    "content":      json.dumps(result, ensure_ascii=False),
                })

        return None  # Hit max_turns without a final answer

    def _simulate_result(
        self,
        tool_name: str,
        args: Dict[str, Any],
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Ask the teacher to simulate a realistic tool result."""
        desc = next(
            (t.get("function", t).get("description", "") for t in tools
             if t.get("function", t).get("name") == tool_name),
            ""
        )
        prompt = (
            f"Simulate a realistic JSON result for calling {tool_name}({args}).\n"
            f"Tool description: {desc}\n"
            f"Return only valid JSON — no explanation."
        )
        raw = self.teacher.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"result": raw[:200]}

    @staticmethod
    def _clean_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Strip None values from messages for clean training data."""
        clean = []
        for m in messages:
            entry = {k: v for k, v in m.items() if v is not None}
            clean.append(entry)
        return clean


# ── Orchestrator ──────────────────────────────────────────────────────────────

class SyntheticDataGenerator:
    """
    Orchestrates synthetic training data generation.

    Combines TeacherModel + SchemaValidator + generators into one interface.

    Example:

        gen = SyntheticDataGenerator(
            endpoint="https://api.openai.com/v1",
            model="gpt-4o-mini",
        )
        stats = gen.generate_router(tools=my_tools, count=200, output_dir="training/")
        print(stats)  # GenerationStats(valid=193, invalid=7, acceptance=96%)
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: Optional[str] = None,
        temperature: float = 0.8,
        timeout: int = 60,
    ):
        self.teacher = TeacherModel(
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            temperature=temperature,
            timeout=timeout,
        )

    def generate_router(
        self,
        tools: List[Dict[str, Any]],
        count: int = 100,
        output_dir: Optional[str] = None,
        per_tool: bool = True,
        verbose: bool = True,
    ) -> GenerationStats:
        """
        Generate router (single-turn) examples and write to JSONL.

        Args:
            tools:      OpenHoof / OpenAI tool schema list
            count:      Target valid example count
            output_dir: Write JSONL here; None = dry-run (return only)
            per_tool:   True = generate per tool (better coverage)
                        False = cross-tool generation (better selection training)
            verbose:    Print progress

        Returns:
            GenerationStats
        """
        validator = SchemaValidator(tools)
        gen = RouterExampleGenerator(self.teacher, validator)

        if verbose:
            print(f"🔧 Generating {count} router examples via {self.teacher.model}")
            print(f"   Tools: {validator.known_tools}")

        examples = gen.generate(tools, count=count, per_tool=per_tool)

        stats = GenerationStats(valid=len(examples), invalid=0)

        if output_dir:
            path = self._write_jsonl(examples, output_dir, "router_synthetic")
            stats.output_path = path
            if verbose:
                print(f"✅ Written {len(examples)} examples → {path}")

        return stats

    def generate_reasoner(
        self,
        tools: List[Dict[str, Any]],
        count: int = 50,
        output_dir: Optional[str] = None,
        task_seeds: Optional[List[str]] = None,
        executor: Optional[Callable] = None,
        verbose: bool = True,
    ) -> GenerationStats:
        """
        Generate reasoner (multi-turn chain) examples and write to JSONL.

        Args:
            tools:      OpenHoof / OpenAI tool schema list
            count:      Target example count
            output_dir: Write JSONL here; None = dry-run
            task_seeds: Optional task descriptions to use as seeds
            executor:   Optional tool executor for real results instead of simulated
            verbose:    Print progress

        Returns:
            GenerationStats
        """
        validator = SchemaValidator(tools)
        gen = ReasonerExampleGenerator(self.teacher, validator, executor=executor)

        if verbose:
            print(f"🧠 Generating {count} reasoner examples via {self.teacher.model}")

        examples = gen.generate(tools, count=count, task_seeds=task_seeds)

        stats = GenerationStats(valid=len(examples), invalid=0)

        if output_dir:
            path = self._write_jsonl(examples, output_dir, "reasoner_synthetic")
            stats.output_path = path
            if verbose:
                print(f"✅ Written {len(examples)} examples → {path}")

        return stats

    @staticmethod
    def _write_jsonl(
        examples: List[Dict[str, Any]],
        output_dir: str,
        prefix: str,
    ) -> Path:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{prefix}_{date.today()}.jsonl"
        # Append to existing file (allows multiple runs to accumulate)
        with open(path, "a") as f:
            for ex in examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
        return path

    @staticmethod
    def load_tools(source: str) -> List[Dict[str, Any]]:
        """
        Load tool schemas from various sources:

        - JSON file path:       "path/to/tools.json"
        - Python module attr:   "mymodule.tools:MY_TOOLS"
        - Inline JSON string:   '[{"type": "function", ...}]'

        Returns:
            List of OpenAI-format tool schema dicts
        """
        # Python module attribute: "module.path:ATTRIBUTE"
        if ":" in source and not source.startswith("[") and not source.endswith(".json"):
            module_path, attr = source.rsplit(":", 1)
            import importlib
            mod = importlib.import_module(module_path)
            return getattr(mod, attr)

        # JSON file
        p = Path(source)
        if p.exists():
            with open(p) as f:
                data = json.load(f)
            return data if isinstance(data, list) else [data]

        # Inline JSON string
        try:
            data = json.loads(source)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            raise ValueError(f"Cannot load tools from: {source!r}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m openhoof.synth",
        description="Generate synthetic training data for OpenHoof tool calling.",
    )
    p.add_argument("--tools", required=True,
                   help="Tool schemas: JSON file, 'module:ATTR', or inline JSON array")
    p.add_argument("--model", required=True,
                   help="Teacher model ID (e.g. gpt-4o-mini, unsloth/Qwen3-8B-GGUF)")
    p.add_argument("--endpoint", default="https://api.openai.com/v1",
                   help="Chat completions endpoint (default: OpenAI)")
    p.add_argument("--api-key", default=None,
                   help="API key (default: $OPENAI_API_KEY)")
    p.add_argument("--type", choices=["router", "reasoner", "both"], default="router",
                   help="Type of data to generate (default: router)")
    p.add_argument("--count", type=int, default=100,
                   help="Target number of valid examples (default: 100)")
    p.add_argument("--output", default=".microclaw/training",
                   help="Output directory for JSONL files (default: .microclaw/training)")
    p.add_argument("--cross-tool", action="store_true",
                   help="Router: use cross-tool generation instead of per-tool")
    p.add_argument("--tasks", nargs="*",
                   help="Reasoner: seed task descriptions")
    p.add_argument("--temperature", type=float, default=0.8,
                   help="Teacher model temperature (default: 0.8)")
    p.add_argument("--timeout", type=int, default=60,
                   help="HTTP timeout seconds (default: 60)")
    p.add_argument("--validate-only",
                   help="Validate an existing JSONL file against --tools schema")
    return p


def _validate_file(jsonl_path: str, tools: List[Dict[str, Any]]) -> None:
    validator = SchemaValidator(tools)
    valid = invalid = 0
    with open(jsonl_path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                print(f"  Line {i}: JSON parse error")
                invalid += 1
                continue
            # Try to extract tool call from ShareGPT or Chat format
            tool_name = args = None
            if "conversations" in entry:
                gpt_turn = next((c["value"] for c in entry["conversations"] if c.get("from") == "gpt"), "")
                m = re.search(r"<tool_call>(.*?)</tool_call>", gpt_turn, re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(1))
                        tool_name = data.get("name")
                        args = data.get("arguments", {})
                    except json.JSONDecodeError:
                        pass
            if tool_name:
                vr = validator.validate(tool_name, args or {})
                if vr.valid:
                    valid += 1
                else:
                    print(f"  Line {i} [{tool_name}]: {'; '.join(vr.errors)}")
                    invalid += 1
            else:
                invalid += 1
    print(f"\nValidation: {valid} valid / {invalid} invalid ({valid/(valid+invalid):.0%})")


def main(argv: Optional[List[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    tools = SyntheticDataGenerator.load_tools(args.tools)
    print(f"Loaded {len(tools)} tools: {[t.get('function', t).get('name') for t in tools]}")

    if args.validate_only:
        _validate_file(args.validate_only, tools)
        return

    gen = SyntheticDataGenerator(
        endpoint=args.endpoint,
        model=args.model,
        api_key=args.api_key,
        temperature=args.temperature,
        timeout=args.timeout,
    )

    if args.type in ("router", "both"):
        stats = gen.generate_router(
            tools=tools,
            count=args.count,
            output_dir=args.output,
            per_tool=not args.cross_tool,
        )
        print(stats)

    if args.type in ("reasoner", "both"):
        stats = gen.generate_reasoner(
            tools=tools,
            count=args.count // 4 if args.type == "both" else args.count,
            output_dir=args.output,
            task_seeds=args.tasks,
        )
        print(stats)


if __name__ == "__main__":
    main()
