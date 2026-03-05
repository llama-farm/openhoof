"""
Synthetic training data generator for OpenHoof tool calling.

Optimized for FunctionGemma 270M based on empirical lessons (see TRAINING_LESSONS.md):
- Simple text output format wins for tiny models
- Synonym explosion beats balanced/minimal strategies  
- Conflict detection is mandatory
- Natural distribution, not artificial balancing
- Auto train/eval split with leak detection

Also supports larger models that handle structured JSON output.

## Output formats

### "text" (default, FunctionGemma-optimized)
    human: "spin left 90 degrees"
    gpt:   "drone_move(yaw_deg=-90)"

    Simple Python-style function call syntax. No JSON, no tags.
    A 270M model routes on keywords — simpler output = better accuracy.
    Empirically: this format scored 87.4% vs structured formats scoring 50–75%.

### "json" (for larger models)
    human: "spin left 90 degrees"
    gpt:   '<tool_call>{"name": "drone_move", "arguments": {"yaw_deg": -90}}</tool_call>'

    For models that can reliably produce structured JSON (e.g. Qwen3-1.7B+).

## Generation strategy (based on lessons learned)

### Synonym explosion (default) — empirically best
    For each tool, generate 8–15 rephrasings of the same intent.
    Let drone_move have 200+ examples if it has 200+ valid phrasings.
    Don't cap. Don't balance. Natural distribution wins.

### Cross-tool (selection training)
    Mixed tasks where tool selection matters.
    Good supplement to synonym explosion, not a replacement.

## Usage

### Python API

    from openhoof.synth import SyntheticDataGenerator

    gen = SyntheticDataGenerator(
        endpoint="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )

    result = gen.generate_router(
        tools=DRONE_TOOLS,
        count=500,
        output_dir=".microclaw/training",
        output_format="text",       # FunctionGemma-optimized
        synonyms_per_example=8,     # rephrasings per base intent
        min_per_tool=8,             # warn if any tool < 8 examples
        holdout_pct=0.1,            # auto split 10% for eval
    )
    print(result)  # GenerationStats(valid=487, invalid=13, ...)

### CLI

    python -m openhoof.synth \\
        --tools path/to/tools.json \\
        --model gpt-4o-mini \\
        --endpoint https://api.openai.com/v1 \\
        --type router \\
        --count 500 \\
        --format text \\
        --synonyms 8 \\
        --output .microclaw/training

    # Local LlamaFarm (Qwen3-8B as teacher)
    python -m openhoof.synth \\
        --tools openhoof.drone_tools:DRONE_TOOLS \\
        --model unsloth/Qwen3-8B-GGUF \\
        --endpoint http://localhost:11540/v1 \\
        --count 500 \\
        --format text

    # Validate existing JSONL
    python -m openhoof.synth \\
        --tools path/to/tools.json \\
        --validate-only .microclaw/training/router_synthetic_2026-03-05.jsonl
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


# ── Output format helpers ─────────────────────────────────────────────────────

def to_text_call(tool_name: str, arguments: Dict[str, Any]) -> str:
    """
    Format a tool call as simple Python-style text.

        tool_name(param1=value1, param2=value2)

    This is the FunctionGemma-optimized format. Empirically outperforms
    JSON formats for 270M models — simpler output pattern = better accuracy.
    """
    parts = []
    for k, v in arguments.items():
        if isinstance(v, str):
            parts.append(f'{k}="{v}"')
        else:
            parts.append(f"{k}={v}")
    return f"{tool_name}({', '.join(parts)})"


def parse_text_call(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a Python-style function call back to {"name": ..., "arguments": ...}.

        "drone_move(yaw_deg=-90)"  →  {"name": "drone_move", "arguments": {"yaw_deg": -90}}

    Used by OutputParser to handle text-format FunctionGemma outputs.
    """
    text = text.strip()
    m = re.match(r"^(\w+)\((.*)\)$", text, re.DOTALL)
    if not m:
        return None
    name = m.group(1)
    args_str = m.group(2).strip()
    args: Dict[str, Any] = {}

    if not args_str:
        return {"name": name, "arguments": {}}

    # Parse key=value pairs (handles strings, numbers, booleans)
    for pair in re.split(r",\s*(?=\w+=)", args_str):
        pair = pair.strip()
        km = re.match(r'^(\w+)=(.+)$', pair, re.DOTALL)
        if not km:
            continue
        key = km.group(1)
        raw = km.group(2).strip()
        # String
        if (raw.startswith('"') and raw.endswith('"')) or \
           (raw.startswith("'") and raw.endswith("'")):
            args[key] = raw[1:-1]
        # Boolean
        elif raw in ("True", "False"):
            args[key] = raw == "True"
        # Number
        else:
            try:
                args[key] = int(raw)
            except ValueError:
                try:
                    args[key] = float(raw)
                except ValueError:
                    args[key] = raw  # fallback: keep as string

    return {"name": name, "arguments": args}


def to_json_call(tool_name: str, arguments: Dict[str, Any]) -> str:
    """
    Format a tool call as <tool_call> JSON (UR-native format for larger models).
    """
    payload = json.dumps({"name": tool_name, "arguments": arguments}, ensure_ascii=False)
    return f"<tool_call>{payload}</tool_call>"


# ── Schema validator ──────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)


class SchemaValidator:
    """
    Validate a generated tool call against tool schemas.

    Checks:
    1. Tool name exists in schemas
    2. All required parameters are present
    3. Parameter types match (with safe numeric string coercion)
    4. No hallucinated parameters beyond the schema
    """

    TYPE_MAP: Dict[str, Tuple] = {
        "string":  (str,),
        "number":  (int, float),
        "integer": (int,),
        "boolean": (bool,),
        "array":   (list,),
        "object":  (dict,),
    }

    def __init__(self, tools: List[Dict[str, Any]]):
        self._schemas: Dict[str, Dict[str, Any]] = {}
        for tool in tools:
            func = tool.get("function", tool)
            name = func.get("name", "")
            if name:
                self._schemas[name] = func.get("parameters", {})

    @property
    def known_tools(self) -> List[str]:
        return list(self._schemas.keys())

    def validate(self, tool_name: str, arguments: Dict[str, Any]) -> ValidationResult:
        errors: List[str] = []

        if tool_name not in self._schemas:
            return ValidationResult(
                valid=False,
                errors=[f"Unknown tool '{tool_name}'. Known: {self.known_tools}"],
            )

        schema = self._schemas[tool_name]
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        for param in required:
            if param not in arguments:
                errors.append(f"Missing required param '{param}'")

        for param, value in arguments.items():
            if param not in properties:
                errors.append(f"Hallucinated param '{param}'")
                continue
            expected = properties[param].get("type")
            if expected and expected in self.TYPE_MAP:
                allowed = self.TYPE_MAP[expected]
                if not isinstance(value, allowed):
                    if expected in ("number", "integer") and isinstance(value, str):
                        try:
                            arguments[param] = int(value) if expected == "integer" else float(value)
                        except ValueError:
                            errors.append(f"'{param}': expected {expected}, got str")
                    elif expected == "string" and isinstance(value, (int, float)):
                        arguments[param] = str(value)
                    else:
                        errors.append(f"'{param}': expected {expected}, got {type(value).__name__}")

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def validate_tool_call(self, tool_call: Dict[str, Any]) -> ValidationResult:
        func = tool_call.get("function", {})
        name = func.get("name", "")
        raw = func.get("arguments", "{}")
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as e:
            return ValidationResult(valid=False, errors=[f"JSON parse error: {e}"])
        return self.validate(name, args)


# ── Conflict detector ─────────────────────────────────────────────────────────

class ConflictDetector:
    """
    Detect contradictory training examples: same input → different outputs.

    Lesson learned: contradictions destroy FunctionGemma accuracy. A 270M
    model can't resolve ambiguity — it picks randomly. Every input must
    map to exactly one output.

    Usage:
        cd = ConflictDetector()
        for example in examples:
            conflict = cd.check(example)
            if conflict:
                print(f"CONFLICT: {conflict}")
            else:
                cd.add(example)
        clean = cd.examples
    """

    def __init__(self):
        self._seen: Dict[str, str] = {}   # normalized_input → output
        self._examples: List[Dict] = []
        self.conflicts: List[Dict] = []

    @property
    def examples(self) -> List[Dict]:
        return self._examples

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize input for conflict detection (lowercase, strip punctuation)."""
        return re.sub(r"[^a-z0-9 ]", "", text.lower().strip())

    def check(self, example: Dict[str, Any]) -> Optional[str]:
        """
        Check an example for conflicts.
        Returns a description string if conflicting, None if clean.
        """
        convs = example.get("conversations", [])
        human = next((c["value"] for c in convs if c.get("from") == "human"), "")
        gpt = next((c["value"] for c in convs if c.get("from") == "gpt"), "")
        key = self._normalize(human)
        if key in self._seen and self._seen[key] != gpt:
            return f"'{human}' → '{self._seen[key]}' vs '{gpt}'"
        return None

    def add(self, example: Dict[str, Any]) -> None:
        convs = example.get("conversations", [])
        human = next((c["value"] for c in convs if c.get("from") == "human"), "")
        gpt = next((c["value"] for c in convs if c.get("from") == "gpt"), "")
        key = self._normalize(human)
        if key not in self._seen:
            self._seen[key] = gpt
            self._examples.append(example)

    def add_all(self, examples: List[Dict[str, Any]]) -> int:
        """Add examples, skipping conflicts. Returns number of conflicts found."""
        for ex in examples:
            conflict = self.check(ex)
            if conflict:
                self.conflicts.append({"conflict": conflict, "example": ex})
            else:
                self.add(ex)
        return len(self.conflicts)


# ── Teacher model ─────────────────────────────────────────────────────────────

class TeacherModel:
    """
    Wrapper around any OpenAI-compatible /v1/chat/completions endpoint.

    Works with OpenAI, LlamaFarm UR, Ollama, Anthropic proxy, or any
    endpoint that speaks OpenAI chat completions.
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

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def chat(self, messages: List[Dict], temperature: Optional[float] = None) -> str:
        """Send a chat request, return assistant text content."""
        import requests
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
        }
        r = requests.post(
            f"{self.endpoint}/chat/completions",
            json=payload, headers=self._headers(), timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        msg = data.get("choices", [{}])[0].get("message", {})
        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            return json.dumps(tool_calls[0].get("function", {}))
        return msg.get("content", "")

    def chat_with_tool_calls(
        self,
        messages: List[Dict],
        tools: List[Dict],
        temperature: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Send a request expecting a tool call. Returns {"name":..,"arguments":..} or None."""
        import requests
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "required",
            "max_tokens": 512,
            "temperature": temperature if temperature is not None else 0.3,
        }
        try:
            r = requests.post(
                f"{self.endpoint}/chat/completions",
                json=payload, headers=self._headers(), timeout=self.timeout,
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

        # Fallback: parse from content
        content = msg.get("content", "")
        if content:
            from .router import ToolCallTagParser, FunctionGemmaOutputParser
            return ToolCallTagParser.parse(content) or FunctionGemmaOutputParser.parse(content)
        return None


# ── Generation result ─────────────────────────────────────────────────────────

@dataclass
class GenerationStats:
    valid: int = 0
    invalid: int = 0
    conflicts: int = 0
    coverage_warnings: List[str] = field(default_factory=list)
    train_path: Optional[Path] = None
    eval_path: Optional[Path] = None

    @property
    def total(self) -> int:
        return self.valid + self.invalid

    @property
    def acceptance_rate(self) -> float:
        return self.valid / self.total if self.total else 0.0

    def __repr__(self) -> str:
        parts = [f"valid={self.valid}", f"invalid={self.invalid}",
                 f"conflicts={self.conflicts}", f"acceptance={self.acceptance_rate:.0%}"]
        if self.train_path:
            parts.append(f"train={self.train_path.name}")
        if self.eval_path:
            parts.append(f"eval={self.eval_path.name}")
        if self.coverage_warnings:
            parts.append(f"warnings={len(self.coverage_warnings)}")
        return f"GenerationStats({', '.join(parts)})"


# ── Router example generator ──────────────────────────────────────────────────

class RouterExampleGenerator:
    """
    Generate single-turn (intent → tool call) examples for router fine-tuning.

    Default strategy: synonym explosion.
    For each base intent, generate N rephrasings at varying formality/length.
    Let high-frequency tools accumulate naturally — do NOT balance.

    Lesson: "Kitchen Sink" (all synonyms, natural distribution) scored 75.4%.
    Balanced (capped per tool) scored 63.1%. Minimal (clean, small) scored 50.8%.
    """

    # ── Prompts ──────────────────────────────────────────────────────────────

    BASE_INTENT_PROMPT = """\
You are generating training data for an AI tool router.

Available tools and their parameters:
{tool_descriptions}

Generate {count} base user intents for the tool "{tool_name}".

Rules:
- Each intent must clearly require "{tool_name}" — not ambiguously another tool
- Use realistic parameter values drawn from the schema
- DO NOT include the tool name in the intent — write as a natural user request
- DO NOT add situational context ("battery is low...", "we need to...") — just the command
- Vary parameter values across the full range
- Return a JSON array of objects:
  [{{"intent": "...", "params": {{"key": "value"}}}}]

Return ONLY the JSON array."""

    SYNONYM_EXPANSION_PROMPT = """\
Rephrase the following command in {count} different ways.

Command: "{base_intent}"
Correct tool call: {tool_call}

Generate {count} alternative phrasings that all mean the same thing.
Vary: formal/casual tone, word order, abbreviations, implied vs explicit.
Do NOT change the meaning or required parameters.

Rules:
- Each rephrasing must still clearly map to the SAME tool call
- Keep phrasings natural — how a real user would actually say it
- No situational context prefixes
- Return a JSON array of strings: ["phrasing 1", "phrasing 2", ...]

Return ONLY the JSON array."""

    CROSS_TOOL_PROMPT = """\
You are generating training data for an AI tool router.

Available tools:
{tool_descriptions}

Generate {count} realistic user requests. Mix tools — don't always use the same one.
For each request, output which tool to call and with what parameters.

The requests should test tool SELECTION — some tools may look similar.

Return a JSON array:
[{{"intent": "...", "tool": "tool_name", "params": {{"key": "value"}}}}]

Rules:
- Intents must be natural — how a real person would say it
- Params must be valid per the schema
- No situational context prefixes
- Return ONLY the JSON array."""

    def __init__(self, teacher: TeacherModel, validator: SchemaValidator):
        self.teacher = teacher
        self.validator = validator

    def generate(
        self,
        tools: List[Dict[str, Any]],
        count: int = 200,
        output_format: str = "text",
        synonyms_per_example: int = 8,
        min_per_tool: int = 8,
        cross_tool_ratio: float = 0.2,
    ) -> Tuple[List[Dict], List[str]]:
        """
        Generate router training examples using synonym explosion strategy.

        Args:
            tools:               Tool schemas
            count:               Target total valid examples
            output_format:       "text" (FunctionGemma) or "json" (<tool_call>)
            synonyms_per_example: Rephrasings per base intent (default 8)
            min_per_tool:        Minimum examples per tool (warns if under)
            cross_tool_ratio:    Fraction from cross-tool generation (default 20%)

        Returns:
            (examples, coverage_warnings)
        """
        examples: List[Dict] = []
        detector = ConflictDetector()

        # Allocate budget: cross-tool first (tests selection), then synonym explosion
        cross_budget = int(count * cross_tool_ratio)
        synonym_budget = count - cross_budget

        # Cross-tool examples
        if cross_budget > 0:
            cross = self._generate_cross_tool(tools, cross_budget, output_format)
            detector.add_all(cross)

        # Synonym explosion per tool
        # Don't balance — allocate proportionally by tool complexity
        per_tool = max(1, synonym_budget // max(len(tools), 1))
        for tool in tools:
            tool_examples = self._generate_synonyms(
                tool, tools, per_tool, output_format, synonyms_per_example
            )
            detector.add_all(tool_examples)

        # Coverage check
        warnings = self._check_coverage(detector.examples, tools, min_per_tool)

        return detector.examples[:count], warnings

    # ── Per-tool synonym generation ─────────────────────────────────────────

    def _generate_synonyms(
        self,
        tool: Dict,
        all_tools: List[Dict],
        base_count: int,
        output_format: str,
        synonyms_per: int,
    ) -> List[Dict]:
        func = tool.get("function", tool)
        tool_name = func.get("name", "")
        tool_descriptions = self._tool_descriptions(all_tools)

        # Step 1: Generate base intents with parameters
        prompt = self.BASE_INTENT_PROMPT.format(
            tool_descriptions=tool_descriptions,
            tool_name=tool_name,
            count=max(base_count // synonyms_per, 3),
        )
        raw = self.teacher.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.85,
        )
        base_items = self._parse_json_list(raw, dict)

        examples = []
        for item in base_items:
            if not isinstance(item, dict):
                continue
            intent = item.get("intent", "")
            params = item.get("params", {})
            if not intent:
                continue

            # Validate the base params
            vr = self.validator.validate(tool_name, params)
            if not vr.valid:
                continue

            tool_call_str = (
                to_text_call(tool_name, params)
                if output_format == "text"
                else to_json_call(tool_name, params)
            )

            # Add base example
            examples.append(self._make_example(intent, tool_call_str))

            # Step 2: Explode synonyms for this base intent
            synonyms = self._expand_synonyms(intent, tool_call_str, synonyms_per)
            for syn in synonyms:
                examples.append(self._make_example(syn, tool_call_str))

        return examples

    def _expand_synonyms(
        self,
        base_intent: str,
        tool_call_str: str,
        count: int,
    ) -> List[str]:
        """Generate `count` rephrasings of base_intent that map to the same tool call."""
        prompt = self.SYNONYM_EXPANSION_PROMPT.format(
            base_intent=base_intent,
            tool_call=tool_call_str,
            count=count,
        )
        raw = self.teacher.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
        )
        return self._parse_json_list(raw, str)

    # ── Cross-tool generation ───────────────────────────────────────────────

    def _generate_cross_tool(
        self,
        tools: List[Dict],
        count: int,
        output_format: str,
    ) -> List[Dict]:
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
            tool_call_str = (
                to_text_call(tool_name, params)
                if output_format == "text"
                else to_json_call(tool_name, params)
            )
            examples.append(self._make_example(intent, tool_call_str))

        return examples[:count]

    # ── Utilities ───────────────────────────────────────────────────────────

    @staticmethod
    def _make_example(intent: str, tool_call_str: str) -> Dict[str, Any]:
        return {
            "conversations": [
                {"from": "human", "value": intent.strip()},
                {"from": "gpt",   "value": tool_call_str},
            ]
        }

    @staticmethod
    def _tool_descriptions(tools: List[Dict]) -> str:
        lines = []
        for t in tools:
            func = t.get("function", t)
            name = func.get("name", "")
            desc = func.get("description", "").split(".")[0]  # first sentence only
            params = func.get("parameters", {}).get("properties", {})
            param_str = ", ".join(
                f"{k}: {v.get('type','?')}" for k, v in params.items()
            )
            lines.append(f"  {name}({param_str}) — {desc}")
        return "\n".join(lines)

    @staticmethod
    def _check_coverage(
        examples: List[Dict],
        tools: List[Dict],
        min_per_tool: int,
    ) -> List[str]:
        """Check that each tool has enough examples. Return warnings."""
        counts: Dict[str, int] = {}
        for ex in examples:
            convs = ex.get("conversations", [])
            gpt = next((c["value"] for c in convs if c.get("from") == "gpt"), "")
            # Extract tool name from either format
            m = re.match(r"^(\w+)\(", gpt)
            if m:
                counts[m.group(1)] = counts.get(m.group(1), 0) + 1
            else:
                m2 = re.search(r'"name":\s*"(\w+)"', gpt)
                if m2:
                    counts[m2.group(1)] = counts.get(m2.group(1), 0) + 1

        warnings = []
        for t in tools:
            name = t.get("function", t).get("name", "")
            n = counts.get(name, 0)
            if n < min_per_tool:
                warnings.append(
                    f"Tool '{name}' has {n} examples (minimum: {min_per_tool})"
                )
        return warnings

    @staticmethod
    def _parse_json_list(raw: str, item_type: type) -> List[Any]:
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
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
    Generate multi-turn (task → tool chain → answer) examples for reasoner SFT.

    The teacher model acts as the agent, chaining tool calls to solve a task.
    An optional executor runs tools for real results; otherwise teacher simulates.
    """

    TASK_GENERATION_PROMPT = """\
You are generating training tasks for an AI reasoning agent.

Available tools:
{tool_descriptions}

Generate {count} realistic tasks that require calling 2–4 tools in sequence.
Each task should require chaining: output of one tool feeds the next.

Requirements:
- Realistic, domain-appropriate requests
- Each task genuinely requires multiple tool calls
- Vary which tools are combined
- Concise (1–2 sentences)

Return a JSON array of strings. Return ONLY the JSON array."""

    REASONING_SYSTEM_PROMPT = """\
You are an autonomous AI agent. Solve the user's task by calling the available \
tools in sequence. Use tool results to decide next steps. \
When done, give a concise final answer."""

    def __init__(
        self,
        teacher: TeacherModel,
        validator: SchemaValidator,
        executor: Optional[Callable[[str, Dict], Any]] = None,
    ):
        self.teacher = teacher
        self.validator = validator
        self.executor = executor

    def generate(
        self,
        tools: List[Dict],
        count: int = 50,
        task_seeds: Optional[List[str]] = None,
        max_turns: int = 8,
        system_prompt: Optional[str] = None,
    ) -> List[Dict]:
        tool_descriptions = "\n".join(
            f"  {t.get('function',t).get('name','')} — {t.get('function',t).get('description','')}"
            for t in tools
        )

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
            tasks.extend(RouterExampleGenerator._parse_json_list(raw, str))

        sys_prompt = system_prompt or self.REASONING_SYSTEM_PROMPT
        examples = []
        for task in tasks[:count * 2]:
            chain = self._run_chain(task, tools, sys_prompt, max_turns)
            if chain:
                examples.append({"messages": chain})
            if len(examples) >= count:
                break
        return examples

    def _run_chain(
        self,
        task: str,
        tools: List[Dict],
        system_prompt: str,
        max_turns: int,
    ) -> Optional[List[Dict]]:
        import requests
        messages: List[Dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": task},
        ]
        headers = {"Content-Type": "application/json"}
        if self.teacher.api_key:
            headers["Authorization"] = f"Bearer {self.teacher.api_key}"

        for _ in range(max_turns):
            payload = {
                "model": self.teacher.model,
                "messages": messages,
                "tools": tools,
                "max_tokens": 1024,
                "temperature": 0.4,
            }
            try:
                r = requests.post(
                    f"{self.teacher.endpoint}/chat/completions",
                    json=payload, headers=headers, timeout=self.teacher.timeout,
                )
                r.raise_for_status()
            except Exception:
                return None

            choice = r.json().get("choices", [{}])[0]
            msg = choice.get("message", {})
            tool_calls = msg.get("tool_calls") or []
            content = msg.get("content") or None

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls or None,
            })

            if not tool_calls:
                return self._clean(messages) if (content and content.strip()) else None

            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                raw = func.get("arguments", "{}")
                try:
                    args = json.loads(raw) if isinstance(raw, str) else raw
                except json.JSONDecodeError:
                    args = {}

                vr = self.validator.validate(name, args)
                if self.executor and vr.valid:
                    try:
                        result = self.executor(name, args)
                    except Exception as e:
                        result = {"error": str(e)}
                else:
                    result = self._simulate(name, args, tools)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", "call_0"),
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        return None

    def _simulate(self, tool_name: str, args: Dict, tools: List[Dict]) -> Dict:
        desc = next(
            (t.get("function", t).get("description", "") for t in tools
             if t.get("function", t).get("name") == tool_name), ""
        )
        prompt = (
            f"Simulate a realistic JSON result for {tool_name}({args}).\n"
            f"Description: {desc}\nReturn only JSON."
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
    def _clean(messages: List[Dict]) -> List[Dict]:
        return [{k: v for k, v in m.items() if v is not None} for m in messages]


# ── Orchestrator ──────────────────────────────────────────────────────────────

class SyntheticDataGenerator:
    """
    Orchestrates synthetic training data generation.

    Combines TeacherModel + SchemaValidator + generators.
    Handles conflict detection, holdout splitting, and JSONL output.
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
            endpoint=endpoint, model=model,
            api_key=api_key, temperature=temperature, timeout=timeout,
        )

    def generate_router(
        self,
        tools: List[Dict[str, Any]],
        count: int = 200,
        output_dir: Optional[str] = None,
        output_format: str = "text",
        synonyms_per_example: int = 8,
        min_per_tool: int = 8,
        holdout_pct: float = 0.1,
        cross_tool_ratio: float = 0.2,
        verbose: bool = True,
    ) -> GenerationStats:
        """
        Generate router (single-turn) training examples.

        Args:
            tools:               OpenHoof / OpenAI tool schema list
            count:               Target valid example count
            output_dir:          Write JSONL here (None = dry-run)
            output_format:       "text" — FunctionGemma-optimized function syntax
                                 "json" — <tool_call> JSON for larger models
            synonyms_per_example: Rephrasings per base intent (default 8)
                                  Lesson: synonym explosion is the winning strategy
            min_per_tool:        Warn if any tool has fewer than this many examples
            holdout_pct:         Fraction to hold out for eval (0 = no split)
            cross_tool_ratio:    Fraction from cross-tool generation (default 20%)
            verbose:             Print progress

        Returns:
            GenerationStats
        """
        validator = SchemaValidator(tools)
        gen = RouterExampleGenerator(self.teacher, validator)

        if verbose:
            mode = "FunctionGemma text" if output_format == "text" else "JSON <tool_call>"
            print(f"🔧 Generating {count} router examples [{mode} format]")
            print(f"   Teacher: {self.teacher.model} @ {self.teacher.endpoint}")
            print(f"   Tools: {validator.known_tools}")
            print(f"   Strategy: synonym explosion × {synonyms_per_example} + {cross_tool_ratio:.0%} cross-tool")

        examples, warnings = gen.generate(
            tools=tools,
            count=count,
            output_format=output_format,
            synonyms_per_example=synonyms_per_example,
            min_per_tool=min_per_tool,
            cross_tool_ratio=cross_tool_ratio,
        )

        if verbose and warnings:
            for w in warnings:
                print(f"   ⚠️  {w}")

        stats = GenerationStats(
            valid=len(examples),
            coverage_warnings=warnings,
        )

        if output_dir:
            train_path, eval_path = self._write_split(
                examples, output_dir, "router_synthetic", holdout_pct
            )
            stats.train_path = train_path
            stats.eval_path = eval_path
            if verbose:
                print(f"✅ {len(examples)} examples → {train_path.name}", end="")
                if eval_path:
                    eval_n = sum(1 for _ in open(eval_path))
                    print(f" + {eval_path.name} ({eval_n} eval)")
                else:
                    print()

        return stats

    def generate_reasoner(
        self,
        tools: List[Dict[str, Any]],
        count: int = 50,
        output_dir: Optional[str] = None,
        task_seeds: Optional[List[str]] = None,
        executor: Optional[Callable] = None,
        holdout_pct: float = 0.1,
        verbose: bool = True,
    ) -> GenerationStats:
        """
        Generate reasoner (multi-turn chain) examples.

        Args:
            tools:       OpenHoof / OpenAI tool schema list
            count:       Target example count
            output_dir:  Write JSONL here
            task_seeds:  Optional seed task descriptions
            executor:    Optional tool executor for real results
            holdout_pct: Fraction for eval holdout
            verbose:     Print progress
        """
        validator = SchemaValidator(tools)
        gen = ReasonerExampleGenerator(self.teacher, validator, executor=executor)

        if verbose:
            print(f"🧠 Generating {count} reasoner examples")
            print(f"   Teacher: {self.teacher.model} @ {self.teacher.endpoint}")

        examples = gen.generate(tools, count=count, task_seeds=task_seeds)

        stats = GenerationStats(valid=len(examples))

        if output_dir:
            train_path, eval_path = self._write_split(
                examples, output_dir, "reasoner_synthetic", holdout_pct
            )
            stats.train_path = train_path
            stats.eval_path = eval_path
            if verbose:
                print(f"✅ {len(examples)} examples → {train_path.name}")

        return stats

    @staticmethod
    def _write_split(
        examples: List[Dict],
        output_dir: str,
        prefix: str,
        holdout_pct: float,
    ) -> Tuple[Path, Optional[Path]]:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        today = date.today()

        if holdout_pct > 0 and len(examples) >= 10:
            split = max(1, int(len(examples) * holdout_pct))
            train_examples = examples[split:]
            eval_examples = examples[:split]
        else:
            train_examples = examples
            eval_examples = []

        train_path = out / f"{prefix}_{today}.jsonl"
        with open(train_path, "a") as f:
            for ex in train_examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

        eval_path = None
        if eval_examples:
            eval_path = out / f"{prefix}_eval_{today}.jsonl"
            with open(eval_path, "a") as f:
                for ex in eval_examples:
                    f.write(json.dumps(ex, ensure_ascii=False) + "\n")

        return train_path, eval_path

    @staticmethod
    def load_tools(source: str) -> List[Dict[str, Any]]:
        """
        Load tool schemas from:
        - JSON file path:          "path/to/tools.json"
        - Python module attribute: "mymodule.tools:MY_TOOLS"
        - Inline JSON:             '[{"type": "function", ...}]'
        """
        if ":" in source and not source.startswith("[") and not source.endswith(".json"):
            module_path, attr = source.rsplit(":", 1)
            import importlib
            mod = importlib.import_module(module_path)
            return getattr(mod, attr)
        p = Path(source)
        if p.exists():
            with open(p) as f:
                data = json.load(f)
            return data if isinstance(data, list) else [data]
        try:
            data = json.loads(source)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            raise ValueError(f"Cannot load tools from: {source!r}")

    @staticmethod
    def validate_file(jsonl_path: str, tools: List[Dict[str, Any]]) -> GenerationStats:
        """
        Validate an existing JSONL file against tool schemas.
        Checks both text-format and JSON-format examples.
        """
        validator = SchemaValidator(tools)
        valid = invalid = conflicts = 0
        detector = ConflictDetector()

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

                # Extract tool call from ShareGPT format
                convs = entry.get("conversations", [])
                gpt = next((c["value"] for c in convs if c.get("from") == "gpt"), "")
                if not gpt:
                    invalid += 1
                    continue

                # Try text format first
                parsed = parse_text_call(gpt)
                # Then JSON format
                if not parsed:
                    m = re.search(r"<tool_call>(.*?)</tool_call>", gpt, re.DOTALL)
                    if m:
                        try:
                            data = json.loads(m.group(1))
                            parsed = {"name": data.get("name"), "arguments": data.get("arguments", {})}
                        except json.JSONDecodeError:
                            pass

                if not parsed or not parsed.get("name"):
                    invalid += 1
                    continue

                vr = validator.validate(parsed["name"], parsed.get("arguments", {}))
                if vr.valid:
                    conflict = detector.check(entry)
                    if conflict:
                        print(f"  Line {i} CONFLICT: {conflict}")
                        conflicts += 1
                    else:
                        detector.add(entry)
                        valid += 1
                else:
                    print(f"  Line {i} [{parsed['name']}]: {'; '.join(vr.errors)}")
                    invalid += 1

        return GenerationStats(valid=valid, invalid=invalid, conflicts=conflicts)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m openhoof.synth",
        description="Generate synthetic training data for OpenHoof tool routing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # FunctionGemma 270M (text format, synonym explosion)
  python -m openhoof.synth --tools tools.json --model gpt-4o-mini --format text --count 500

  # Larger model (JSON format)
  python -m openhoof.synth --tools tools.json --model gpt-4o-mini --format json --count 200

  # Local LlamaFarm teacher
  python -m openhoof.synth --tools tools.json --model unsloth/Qwen3-8B-GGUF \\
      --endpoint http://localhost:11540/v1 --count 300

  # From Python module
  python -m openhoof.synth --tools openhoof.drone_tools:DRONE_TOOLS --model gpt-4o-mini

  # Validate existing JSONL
  python -m openhoof.synth --tools tools.json --validate-only training/router_synthetic.jsonl
""",
    )
    p.add_argument("--tools", required=True,
                   help="Tool schemas: JSON file, 'module:ATTR', or inline JSON")
    p.add_argument("--model", required=True,
                   help="Teacher model ID")
    p.add_argument("--endpoint", default="https://api.openai.com/v1",
                   help="Chat completions base URL (default: OpenAI)")
    p.add_argument("--api-key", default=None, dest="api_key",
                   help="API key (default: $OPENAI_API_KEY)")
    p.add_argument("--type", choices=["router", "reasoner", "both"], default="router",
                   help="Data type to generate (default: router)")
    p.add_argument("--format", choices=["text", "json"], default="text", dest="fmt",
                   help="Output format: text=FunctionGemma function syntax, json=<tool_call> JSON (default: text)")
    p.add_argument("--count", type=int, default=200,
                   help="Target valid examples (default: 200)")
    p.add_argument("--synonyms", type=int, default=8, dest="synonyms",
                   help="Rephrasings per base intent — synonym explosion (default: 8)")
    p.add_argument("--min-per-tool", type=int, default=8, dest="min_per_tool",
                   help="Warn if any tool has fewer than N examples (default: 8)")
    p.add_argument("--holdout", type=float, default=0.1, dest="holdout_pct",
                   help="Fraction held out for eval JSONL (default: 0.1)")
    p.add_argument("--cross-tool-ratio", type=float, default=0.2, dest="cross_tool_ratio",
                   help="Fraction from cross-tool generation (default: 0.2)")
    p.add_argument("--tasks", nargs="*",
                   help="Reasoner: seed task descriptions")
    p.add_argument("--temperature", type=float, default=0.8,
                   help="Teacher temperature (default: 0.8)")
    p.add_argument("--timeout", type=int, default=60,
                   help="HTTP timeout seconds (default: 60)")
    p.add_argument("--output", default=".microclaw/training",
                   help="Output directory (default: .microclaw/training)")
    p.add_argument("--validate-only", default=None, dest="validate_only",
                   help="Validate an existing JSONL file, then exit")
    return p


def main(argv: Optional[List[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    tools = SyntheticDataGenerator.load_tools(args.tools)
    print(f"Loaded {len(tools)} tools: {[t.get('function', t).get('name') for t in tools]}")

    if args.validate_only:
        stats = SyntheticDataGenerator.validate_file(args.validate_only, tools)
        print(f"\n{stats}")
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
            output_format=args.fmt,
            synonyms_per_example=args.synonyms,
            min_per_tool=args.min_per_tool,
            holdout_pct=args.holdout_pct,
            cross_tool_ratio=args.cross_tool_ratio,
        )
        print(stats)

    if args.type in ("reasoner", "both"):
        stats = gen.generate_reasoner(
            tools=tools,
            count=args.count // 4 if args.type == "both" else args.count,
            output_dir=args.output,
            task_seeds=args.tasks,
            holdout_pct=args.holdout_pct,
        )
        print(stats)


if __name__ == "__main__":
    main()
