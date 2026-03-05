"""
openhoof.refine — Training Refinement Loop

Implements the iterative fine-tuning workflow documented by Ace (drone agent):
  Train → Eval → Categorize misses → Targeted fixes → Repeat

The key insight: data changes, NOT hyperparameters.
Every round adds 20–60 targeted examples. Never removes. Never tunes lr/epochs.

Usage:
    from openhoof import RefinementLoop

    loop = RefinementLoop(
        tools=MY_TOOLS,
        training_dir=".microclaw/training",
        endpoint="http://localhost:11540/v1",
        model="unsloth/functiongemma-270m-it-GGUF",
    )

    # Evaluate a trained model
    report = loop.eval(job_id="ft:abc123", eval_file="router_eval.jsonl")
    print(report.summary())

    # Categorize every miss and get suggested fixes
    fixes = loop.categorize(report)
    fixes.print_report()

    # Generate targeted examples for the identified gaps
    new_examples = loop.suggest_targeted_examples(fixes)

    # Merge datasets (v1-priority conflict resolution + dedup)
    merged = loop.merge(
        base="router_train_v1.jsonl",
        addition="router_train_v2.jsonl",
        output="router_train_merged.jsonl",
        base_priority=True,
    )
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Miss categories (from Ace's analysis) ────────────────────────────────────

CATEGORY_CONTRADICTION   = "contradiction"       # same input → different output in training data
CATEGORY_ZERO_COVERAGE   = "zero_coverage"       # no training examples for this input pattern
CATEGORY_HALLUCINATED    = "hallucinated_tool"   # model output is not a real tool
CATEGORY_WRONG_FALLBACK  = "wrong_fallback"      # model defaulted to most-common tool
CATEGORY_AMBIGUOUS       = "ambiguous"           # multiple valid tools could match
CATEGORY_UNKNOWN         = "unknown"             # couldn't classify


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class EvalExample:
    """Single eval example with model result."""
    input: str
    expected_tool: str
    expected_raw: str          # full expected output e.g. switch_create_vlan(vid=100)
    got_tool: str
    got_raw: str
    correct: bool
    latency_ms: float = 0.0


@dataclass
class MissCategorization:
    """Classification of a single miss."""
    example: EvalExample
    category: str
    explanation: str
    suggested_fix: Optional[str] = None   # concrete example to add


@dataclass
class EvalReport:
    """Full eval run results."""
    model: str
    eval_file: str
    examples: List[EvalExample] = field(default_factory=list)
    timestamp: str = ""

    @property
    def total(self) -> int:
        return len(self.examples)

    @property
    def correct(self) -> int:
        return sum(1 for e in self.examples if e.correct)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def misses(self) -> List[EvalExample]:
        return [e for e in self.examples if not e.correct]

    def per_tool_accuracy(self) -> Dict[str, Dict[str, int]]:
        by_tool: Dict[str, Dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
        for ex in self.examples:
            by_tool[ex.expected_tool]["total"] += 1
            if ex.correct:
                by_tool[ex.expected_tool]["correct"] += 1
        return dict(by_tool)

    def summary(self) -> str:
        lines = [
            f"Model:    {self.model}",
            f"Accuracy: {self.accuracy:.1%}  ({self.correct}/{self.total})",
        ]
        if self.accuracy >= 0.90:
            lines.append("Status:   ✅ Ready to ship")
        elif self.accuracy >= 0.80:
            lines.append("Status:   ⚠️  Acceptable — retrain with targeted fixes")
        else:
            lines.append("Status:   ❌ Below threshold — data quality issue")

        lines.append("\nPer-tool accuracy:")
        for tool, stats in sorted(
            self.per_tool_accuracy().items(),
            key=lambda x: x[1]["correct"] / max(x[1]["total"], 1),
        ):
            n = stats["total"]
            c = stats["correct"]
            pct = c / n if n else 0
            bar = "█" * int(pct * 20)
            flag = " ✅" if pct >= 0.9 else (" ⚠️" if pct >= 0.7 else " ❌")
            lines.append(f"  {pct:5.0%}  {bar:<20s}  {c}/{n}  {tool}{flag}")
        return "\n".join(lines)

    def miss_report(self) -> str:
        if not self.misses:
            return "No misses."
        lines = [f"Misses ({len(self.misses)}):"]
        for ex in self.misses:
            lines.append(f"  input:    {ex.input!r}")
            lines.append(f"  expected: {ex.expected_raw}")
            lines.append(f"  got:      {ex.got_raw}")
            lines.append("")
        return "\n".join(lines)


@dataclass
class CategorizationReport:
    """All miss categorizations for one eval run."""
    categorizations: List[MissCategorization] = field(default_factory=list)
    eval_report: Optional[EvalReport] = None

    def by_category(self) -> Dict[str, List[MissCategorization]]:
        result: Dict[str, List[MissCategorization]] = defaultdict(list)
        for c in self.categorizations:
            result[c.category].append(c)
        return dict(result)

    def print_report(self) -> None:
        by_cat = self.by_category()
        total = len(self.categorizations)
        print(f"\nMiss Categorization ({total} misses):")
        print("=" * 60)

        order = [
            CATEGORY_CONTRADICTION,
            CATEGORY_ZERO_COVERAGE,
            CATEGORY_HALLUCINATED,
            CATEGORY_WRONG_FALLBACK,
            CATEGORY_AMBIGUOUS,
            CATEGORY_UNKNOWN,
        ]
        for cat in order:
            items = by_cat.get(cat, [])
            if not items:
                continue
            print(f"\n{cat.upper().replace('_', ' ')} ({len(items)}):")
            for item in items:
                print(f"  input:    {item.example.input!r}")
                print(f"  expected: {item.example.expected_raw}")
                print(f"  got:      {item.example.got_raw}")
                print(f"  why:      {item.explanation}")
                if item.suggested_fix:
                    print(f"  fix:      {item.suggested_fix}")
                print()

        print("Priority actions:")
        if by_cat.get(CATEGORY_CONTRADICTION):
            print(f"  1. Fix {len(by_cat[CATEGORY_CONTRADICTION])} contradictions in training data first")
        if by_cat.get(CATEGORY_ZERO_COVERAGE):
            print(f"  2. Add 3-5 examples for {len(by_cat[CATEGORY_ZERO_COVERAGE])} zero-coverage patterns")
        if by_cat.get(CATEGORY_HALLUCINATED):
            print(f"  3. Add examples of correct tool for {len(by_cat[CATEGORY_HALLUCINATED])} hallucinated patterns")
        if by_cat.get(CATEGORY_WRONG_FALLBACK):
            print(f"  4. Add slang → correct-tool examples for {len(by_cat[CATEGORY_WRONG_FALLBACK])} fallback failures")


@dataclass
class MergeStats:
    """Stats from a merge operation."""
    base_count: int
    addition_count: int
    merged_count: int
    conflicts_resolved: int
    duplicates_removed: int
    output_path: str

    def summary(self) -> str:
        return (
            f"Merged: {self.base_count} base + {self.addition_count} addition\n"
            f"  Conflicts resolved: {self.conflicts_resolved} (base priority)\n"
            f"  Duplicates removed: {self.duplicates_removed}\n"
            f"  Final count:        {self.merged_count}\n"
            f"  Output:             {self.output_path}"
        )


# ── RefinementLoop ────────────────────────────────────────────────────────────

class RefinementLoop:
    """
    Implements Ace's training refinement loop:
      Train → Eval → Categorize misses → Targeted fixes → Merge → Repeat

    Strategy:
    - Change data, NOT hyperparameters (epochs/lr/rank stay fixed)
    - Each round: 20-60 targeted examples maximum
    - Never remove existing examples — only append or edit
    - Base dataset always takes priority on conflicts
    - v1 (hand-tuned) + v2 (generated) + targeted fixes = highest accuracy
    """

    # Tools that models default to when uncertain (learned from Ace's experiments)
    # Update these with your domain's most-common tool if it shows up in wrong_fallback misses.
    COMMON_FALLBACK_TOOLS: List[str] = []

    def __init__(
        self,
        tools: List[Dict[str, Any]],
        training_dir: str,
        endpoint: str = "http://localhost:11540/v1",
        model: str = "unsloth/functiongemma-270m-it-GGUF",
        api_key: str = "local",
        temperature: float = 0.0,
    ):
        self.tools = tools
        self.training_dir = Path(training_dir)
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.temperature = temperature

        self._tool_names: set = set()
        for t in tools:
            fn = t.get("function", t)
            name = fn.get("name", "")
            if name:
                self._tool_names.add(name)

    # ── Eval ─────────────────────────────────────────────────────────────────

    def eval(
        self,
        eval_file: str,
        job_id: Optional[str] = None,
        model_override: Optional[str] = None,
        verbose: bool = True,
    ) -> EvalReport:
        """
        Run every example in eval_file through the model.
        Returns EvalReport with accuracy + per-example results.

        Args:
            eval_file:       Path to eval JSONL (ShareGPT format)
            job_id:          Fine-tuned model job id e.g. "abc123" (adds ft: prefix)
            model_override:  Override the default model entirely
            verbose:         Print progress
        """
        eval_path = Path(eval_file)
        if not eval_path.is_absolute():
            candidates = [
                eval_path,
                self.training_dir / eval_path,
            ]
            for c in candidates:
                if c.exists():
                    eval_path = c
                    break

        if not eval_path.exists():
            raise FileNotFoundError(f"Eval file not found: {eval_file}")

        model = model_override or (f"ft:{job_id}" if job_id else self.model)

        examples = []
        with open(eval_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ex = json.loads(line)
                convs = ex.get("conversations", [])
                if len(convs) >= 2:
                    h = next((c["value"] for c in convs if c.get("from") == "human"), "")
                    g = next((c["value"] for c in convs if c.get("from") == "gpt"), "")
                    if h and g:
                        examples.append({"input": h, "expected": g})

        if verbose:
            print(f"\nEval: {len(examples)} examples")
            print(f"Model: {model}")
            print(f"Endpoint: {self.endpoint}\n")

        import requests as _requests

        report = EvalReport(
            model=model,
            eval_file=str(eval_path),
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        # Build slim tools for inference (no descriptions — Ace's lesson)
        from .router import ToolRouter
        slim_tools = ToolRouter._slim_tools(self.tools)

        for i, ex in enumerate(examples):
            t0 = time.time()
            try:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Route the command to the correct tool call. Return a single function call only."},
                        {"role": "user", "content": ex["input"]},
                    ],
                    "tools": slim_tools,
                    "temperature": self.temperature,
                    # Low max_tokens prevents base FunctionGemma from chaining calls.
                    # Single tool calls are < 30 tokens; 64 is generous headroom.
                    "max_tokens": 64,
                }
                r = _requests.post(
                    f"{self.endpoint}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=30,
                )
                r.raise_for_status()
                resp_data = r.json()
                got_raw = self._extract_tool_call_str_from_dict(resp_data)
                got_tool = got_raw.split("(")[0] if got_raw else ""
            except Exception as e:
                got_raw = f"ERROR: {e}"
                got_tool = ""

            latency = (time.time() - t0) * 1000
            expected_tool = ex["expected"].split("(")[0]
            correct = got_tool == expected_tool

            result = EvalExample(
                input=ex["input"],
                expected_tool=expected_tool,
                expected_raw=ex["expected"],
                got_tool=got_tool,
                got_raw=got_raw,
                correct=correct,
                latency_ms=latency,
            )
            report.examples.append(result)

            if verbose and (i + 1) % 10 == 0:
                running = report.correct / (i + 1) * 100
                print(f"  [{i+1:3d}/{len(examples)}]  accuracy: {running:.1f}%  ({latency:.0f}ms)")

        if verbose:
            print(f"\n{report.summary()}")

        return report

    # ── Miss categorization ───────────────────────────────────────────────────

    def categorize(
        self,
        report: EvalReport,
        training_file: Optional[str] = None,
        verbose: bool = True,
    ) -> CategorizationReport:
        """
        Classify every miss in the eval report into one of 5 categories.

        Categories (from Ace's analysis):
          contradiction   — same input → different output in training data
          zero_coverage   — no similar examples in training data
          hallucinated    — model output tool doesn't exist in schema
          wrong_fallback  — model picked the most-common tool when uncertain
          ambiguous       — multiple valid tools could match
          unknown         — couldn't classify

        Args:
            report:          EvalReport from eval()
            training_file:   Training JSONL to check for contradictions + coverage
            verbose:         Print progress
        """
        # Load training data for context
        training_examples = []
        if training_file:
            tf = Path(training_file)
            if not tf.exists():
                candidates = sorted(self.training_dir.glob("router_synthetic_[0-9]*.jsonl"))
                if candidates:
                    tf = candidates[-1]
            if tf.exists():
                with open(tf) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        ex = json.loads(line)
                        convs = ex.get("conversations", [])
                        if len(convs) >= 2:
                            h = next((c["value"] for c in convs if c.get("from") == "human"), "")
                            g = next((c["value"] for c in convs if c.get("from") == "gpt"), "")
                            training_examples.append({"input": h.lower(), "expected": g, "tool": g.split("(")[0]})

        # Build lookup structures
        input_to_tools: Dict[str, set] = defaultdict(set)
        tool_frequency: Counter = Counter()
        for ex in training_examples:
            input_to_tools[ex["input"]].add(ex["tool"])
            tool_frequency[ex["tool"]] += 1

        # Most common tool = likely fallback
        fallback_tools = set(self.COMMON_FALLBACK_TOOLS)
        if tool_frequency:
            most_common = tool_frequency.most_common(3)
            for tool, _ in most_common:
                fallback_tools.add(tool)

        result = CategorizationReport(eval_report=report)

        for miss in report.misses:
            cat, explanation, suggested_fix = self._classify_miss(
                miss=miss,
                input_to_tools=input_to_tools,
                training_examples=training_examples,
                fallback_tools=fallback_tools,
            )
            result.categorizations.append(MissCategorization(
                example=miss,
                category=cat,
                explanation=explanation,
                suggested_fix=suggested_fix,
            ))

        if verbose:
            result.print_report()

        return result

    def _classify_miss(
        self,
        miss: EvalExample,
        input_to_tools: Dict[str, set],
        training_examples: List[Dict],
        fallback_tools: set,
    ) -> Tuple[str, str, Optional[str]]:
        """Returns (category, explanation, suggested_fix)."""

        # 1. Hallucinated tool — model output not in schema
        if miss.got_tool and miss.got_tool not in self._tool_names and miss.got_tool != "":
            return (
                CATEGORY_HALLUCINATED,
                f"'{miss.got_tool}' is not a real tool. Model invented it.",
                f'{{"conversations": [{{"from": "human", "value": "{miss.input}"}}, {{"from": "gpt", "value": "{miss.expected_raw}"}}]}}',
            )

        # 2. Contradiction — training data has same input → different tools
        input_lower = miss.input.lower()
        tools_for_input = input_to_tools.get(input_lower, set())
        if len(tools_for_input) > 1:
            return (
                CATEGORY_CONTRADICTION,
                f"Training data maps this input to {tools_for_input}. Pick one and remove the other.",
                f"Edit training data: standardize '{miss.input}' → '{miss.expected_raw}'",
            )

        # 3. Zero coverage — check for similar phrasing in training
        similar = self._find_similar(miss.input, training_examples, threshold=0.3)
        if len(similar) < 3:
            return (
                CATEGORY_ZERO_COVERAGE,
                f"Only {len(similar)} similar training examples found for '{miss.expected_tool}'.",
                f'{{"conversations": [{{"from": "human", "value": "{miss.input}"}}, {{"from": "gpt", "value": "{miss.expected_raw}"}}]}}',
            )

        # 4. Wrong fallback — model picked a common/default tool
        if miss.got_tool in fallback_tools:
            return (
                CATEGORY_WRONG_FALLBACK,
                f"Model defaulted to '{miss.got_tool}' (common fallback). "
                f"Need more examples of this phrasing → '{miss.expected_tool}'.",
                f'{{"conversations": [{{"from": "human", "value": "{miss.input}"}}, {{"from": "gpt", "value": "{miss.expected_raw}"}}]}}',
            )

        # 5. Ambiguous — both expected and got are valid for this input
        if miss.got_tool in self._tool_names:
            return (
                CATEGORY_AMBIGUOUS,
                f"Both '{miss.expected_tool}' and '{miss.got_tool}' could reasonably match this input. "
                f"Consider whether the test expectation is correct.",
                f"Review: is '{miss.input}' always '{miss.expected_raw}'? Or accept both?",
            )

        return (
            CATEGORY_UNKNOWN,
            f"Model returned '{miss.got_raw}' for unknown reason.",
            None,
        )

    @staticmethod
    def _find_similar(
        query: str,
        training_examples: List[Dict],
        threshold: float = 0.3,
    ) -> List[Dict]:
        """Token overlap similarity — fast, no embeddings needed."""
        q_tokens = set(query.lower().split())
        similar = []
        for ex in training_examples:
            t_tokens = set(ex["input"].split())
            overlap = len(q_tokens & t_tokens)
            union = len(q_tokens | t_tokens)
            if union > 0 and overlap / union >= threshold:
                similar.append(ex)
        return similar

    # ── Dataset merge ─────────────────────────────────────────────────────────

    def merge(
        self,
        base: str,
        addition: str,
        output: str,
        base_priority: bool = True,
        dedup: bool = True,
        verbose: bool = True,
    ) -> MergeStats:
        """
        Merge two training JSONL files.

        Strategy (from Ace's v3 breakthrough):
        - base takes priority on any conflict (v1 hand-tuned data wins)
        - Dedup by exact input string (remove exact duplicates)
        - Result: base_count + addition_count - conflicts - duplicates

        Args:
            base:           Path to base JSONL (higher priority)
            addition:       Path to addition JSONL (generated / round N)
            output:         Output path
            base_priority:  If True, base wins on conflict (default True)
            dedup:          Remove exact-input duplicates (default True)
            verbose:        Print stats
        """
        def load(path: str) -> List[Tuple[str, str, dict]]:
            """Returns [(human, tool, raw_entry)]"""
            items = []
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    convs = entry.get("conversations", [])
                    h = next((c["value"] for c in convs if c.get("from") == "human"), "")
                    g = next((c["value"] for c in convs if c.get("from") == "gpt"), "")
                    items.append((h.lower().strip(), g, entry))
            return items

        base_items = load(base)
        add_items  = load(addition)

        # Build base index: input → (expected_output, entry)
        base_index: Dict[str, Tuple[str, dict]] = {}
        for h, g, entry in base_items:
            base_index[h] = (g, entry)

        conflicts_resolved = 0
        duplicates_removed = 0
        merged: List[dict] = [entry for _, _, entry in base_items]

        for h, g, entry in add_items:
            if h in base_index:
                base_g, _ = base_index[h]
                if base_g == g:
                    duplicates_removed += 1  # exact duplicate
                else:
                    conflicts_resolved += 1  # conflict — base wins
                continue
            merged.append(entry)

        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            for entry in merged:
                f.write(json.dumps(entry) + "\n")

        stats = MergeStats(
            base_count=len(base_items),
            addition_count=len(add_items),
            merged_count=len(merged),
            conflicts_resolved=conflicts_resolved,
            duplicates_removed=duplicates_removed,
            output_path=str(output_path),
        )

        if verbose:
            print(f"\nMerge complete:")
            print(stats.summary())

        return stats

    # ── Targeted example generation ───────────────────────────────────────────

    def suggest_targeted_examples(
        self,
        report: CategorizationReport,
        n_per_miss: int = 3,
    ) -> List[dict]:
        """
        Return a list of suggested JSONL entries targeting identified miss patterns.

        For zero-coverage and wrong-fallback misses, generates synonym rephrasings.
        For contradictions, returns the canonical (base) answer.

        n_per_miss: How many synonym variants per miss (default 3; max 5 per Ace's rule)
        """
        suggestions = []
        by_cat = report.by_category()

        # Zero coverage + wrong fallback → generate variations
        for cat in [CATEGORY_ZERO_COVERAGE, CATEGORY_WRONG_FALLBACK, CATEGORY_HALLUCINATED]:
            for item in by_cat.get(cat, []):
                # Base example
                suggestions.append({"conversations": [
                    {"from": "human", "value": item.example.input},
                    {"from": "gpt",   "value": item.example.expected_raw},
                ]})
                # Simple character-level variations (real synonyms need teacher model)
                variations = self._simple_variations(item.example.input, n_per_miss - 1)
                for v in variations:
                    suggestions.append({"conversations": [
                        {"from": "human", "value": v},
                        {"from": "gpt",   "value": item.example.expected_raw},
                    ]})

        # Contradictions → just add the canonical answer
        for item in by_cat.get(CATEGORY_CONTRADICTION, []):
            suggestions.append({"conversations": [
                {"from": "human", "value": item.example.input},
                {"from": "gpt",   "value": item.example.expected_raw},
            ]})

        return suggestions

    @staticmethod
    def _simple_variations(text: str, n: int) -> List[str]:
        """Generate simple rephrasing variations without an LLM."""
        # Very basic prefix/suffix substitutions — enough to hint at patterns
        prefixes = [
            "please ", "can you ", "show me ", "get me ", "i need to ",
            "what's the ", "check the ", "list the ", "display the ",
        ]
        variations = []
        for p in prefixes[:n]:
            if not text.lower().startswith(p):
                variations.append(p + text.lower())
            if len(variations) >= n:
                break
        return variations

    # ── Utility: extract tool call string from API response dict ─────────────

    def _extract_tool_call_str_from_dict(self, resp_data: dict) -> str:
        """Extract tool_name(params) string from a raw /chat/completions response dict."""
        choices = resp_data.get("choices", [])
        if not choices:
            return ""
        msg = choices[0].get("message", {})

        # Standard OpenAI tool_calls
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            tc = tool_calls[0]
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}") or "{}")
                params = ", ".join(f"{k}={v!r}" for k, v in args.items())
                return f"{name}({params})"
            except json.JSONDecodeError:
                return f"{name}({fn.get('arguments', '')})"

        content = msg.get("content") or ""

        # FunctionGemma text format: tool_name(params)
        m = re.match(r'^(\w+)\((.*)\)\s*$', content.strip(), re.DOTALL)
        if m:
            return content.strip()

        # <tool_call> JSON tag
        m = re.search(r'<tool_call>(.*?)</tool_call>', content, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                name = data.get("name", "")
                args = data.get("arguments", {})
                params = ", ".join(f"{k}={v!r}" for k, v in args.items())
                return f"{name}({params})"
            except json.JSONDecodeError:
                pass

        # FunctionGemma native format — take FIRST call only (base model chains)
        m = re.search(r'<start_function_call>(.*?)<end_function_call>', content, re.DOTALL)
        if m:
            try:
                inner = m.group(1).strip()
                # "call:tool_name{args}" format
                cm = re.match(r'call:(\w+)\{(.*)\}', inner, re.DOTALL)
                if cm:
                    return cm.group(1) + "()"
                # JSON format
                data = json.loads(inner)
                name = data.get("name", "")
                args = data.get("arguments", {})
                params = ", ".join(f"{k}={v!r}" for k, v in args.items())
                return f"{name}({params})"
            except (json.JSONDecodeError, Exception):
                pass

        # FunctionGemma call: format without tags — "call:tool_name{args}"
        cm = re.match(r'call:(\w+)\{', content.strip())
        if cm:
            return cm.group(1) + "()"

        # Take first line only (prevents chained output noise)
        first_line = content.strip().split("\n")[0].strip()
        m = re.match(r'^(\w+)\((.*)\)\s*$', first_line, re.DOTALL)
        if m:
            return first_line

        return first_line
