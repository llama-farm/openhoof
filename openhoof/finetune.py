"""
FinetuneManager — convert captured training data to LlamaFarm SFT jobs.

## Architecture

Training data flows:
    agent.reason() → TrainingDataCapture → JSONL files
                                             ↓
                                       FinetuneManager
                                             ↓
                               LlamaFarm SFT API (/v1/finetune/sft)
                                             ↓
                               Trained GGUF → ~/.llamafarm/models/llm/{job_id}/

## Dataset formats

### Router dataset (FunctionGemma 270M)

Captured format (router_YYYY-MM-DD.jsonl):
    {"model": "router", "messages": [{"role": "user", "content": "..."}],
     "tool_call": {"name": "get_flight_data", "arguments": {"flight_id": "MAY101"}}}

LlamaFarm SFT format (ShareGPT):
    {"conversations": [
        {"from": "human", "value": "Get fuel state for MAY101"},
        {"from": "gpt",   "value": "<tool_call>{\"name\": \"get_flight_data\", \"arguments\": {\"flight_id\": \"MAY101\"}}</tool_call>"}
    ]}

Teaching FunctionGemma to output <tool_call> JSON — the format UR can
parse natively without custom post-processing.

### Reasoner dataset (Qwen3-1.7B)

Captured format (reasoner_YYYY-MM-DD.jsonl):
    {"model": "reasoner", "messages": [...full conversation...], "turn_count": 3}

LlamaFarm SFT format (Chat / OpenAI-style):
    {"messages": [
        {"role": "system",    "content": "..."},
        {"role": "user",      "content": "Analyze fuel for MAY101"},
        {"role": "assistant", "content": null, "tool_calls": [...]},
        {"role": "tool",      "content": "..."},
        {"role": "assistant", "content": "STATUS: GREEN ..."}
    ]}

## Usage

    from openhoof.finetune import FinetuneManager

    ft = FinetuneManager(endpoint="http://localhost:11540/v1")

    # Fine-tune FunctionGemma on captured router data
    job_id = ft.finetune_router(
        training_dir=".microclaw/training",
        epochs=10,
        lora_rank=8,
    )

    # Fine-tune Qwen3 on captured reasoning chains
    job_id = ft.finetune_reasoner(
        training_dir=".microclaw/training",
        epochs=3,
        lora_rank=16,
    )

    # Monitor progress
    status = ft.poll(job_id)
    print(status["progress"], status["metrics"])

    # When complete, load the trained GGUF
    gguf_path = ft.gguf_path(job_id)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Job status ────────────────────────────────────────────────────────────────

class JobStatus:
    """Status of a LlamaFarm SFT/CPT training job."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    @property
    def job_id(self) -> str:
        return self._data.get("job_id", "")

    @property
    def status(self) -> str:
        return self._data.get("status", "unknown")

    @property
    def progress(self) -> float:
        return self._data.get("progress", 0.0)

    @property
    def metrics(self) -> Optional[Dict[str, Any]]:
        return self._data.get("metrics")

    @property
    def output_dir(self) -> Optional[str]:
        return self._data.get("output_dir")

    @property
    def error(self) -> Optional[str]:
        return self._data.get("error")

    @property
    def done(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"

    def __repr__(self) -> str:
        return (
            f"JobStatus(id={self.job_id!r}, status={self.status!r}, "
            f"progress={self.progress:.0%})"
        )


# ── Dataset converters ────────────────────────────────────────────────────────

class RouterDatasetBuilder:
    """
    Convert router JSONL captures → ShareGPT format for FunctionGemma SFT.

    The output teaches FunctionGemma to produce <tool_call> JSON format:
        human: "Get flight data for MAY101"
        gpt:   '<tool_call>{"name": "get_flight_data", "arguments": {"flight_id": "MAY101"}}</tool_call>'

    This is the format that UR's detect_tool_call_in_content() already parses,
    so after fine-tuning the router integrates natively with no extra parsing.
    """

    @staticmethod
    def convert(captures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert router captures to ShareGPT format.

        Filters out:
        - Entries without a user intent message
        - Entries without a named tool call
        - Entries where Router disagreed with Reasoner (agreed=False) — those
          are ambiguous training signal
        """
        dataset = []
        for entry in captures:
            # Skip non-router entries
            if entry.get("model") != "router":
                continue

            # Extract user intent (first user message)
            messages = entry.get("messages", [])
            user_intent = next(
                (m["content"] for m in messages if m.get("role") == "user" and m.get("content")),
                None,
            )
            if not user_intent:
                continue

            # Extract tool call
            tool_call = entry.get("tool_call", {})
            tool_name = tool_call.get("name")
            arguments = tool_call.get("arguments", {})
            if not tool_name:
                continue

            # Skip if router disagreed (ambiguous training signal)
            if entry.get("agreed") is False:
                continue

            # Format gpt response: <tool_call> JSON (UR-parseable format)
            tool_call_json = json.dumps(
                {"name": tool_name, "arguments": arguments},
                ensure_ascii=False,
            )
            gpt_response = f"<tool_call>{tool_call_json}</tool_call>"

            dataset.append({
                "conversations": [
                    {"from": "human", "value": user_intent},
                    {"from": "gpt",   "value": gpt_response},
                ]
            })

        return dataset

    @staticmethod
    def deduplicate(dataset: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate (intent, tool_call) pairs."""
        seen = set()
        unique = []
        for item in dataset:
            convs = item.get("conversations", [])
            key = tuple(c.get("value", "") for c in convs)
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique


class ReasonerDatasetBuilder:
    """
    Convert reasoner JSONL captures → Chat format for Qwen3 SFT.

    Multi-turn conversations teach the Reasoner how to chain tool calls:
    task → tool call → result → tool call → result → final answer.
    """

    @staticmethod
    def convert(captures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert reasoner captures to OpenAI Chat format.

        Filters out:
        - Incomplete chains (turn_count < 1)
        - Chains without a final assistant text response
        """
        dataset = []
        for entry in captures:
            if entry.get("model") != "reasoner":
                continue

            messages = entry.get("messages", [])
            if not messages:
                continue

            # Require at least one tool call turn
            turn_count = entry.get("turn_count", 0)
            if turn_count < 1:
                continue

            # Require a final text response
            last = messages[-1]
            if last.get("role") != "assistant" or not last.get("content"):
                continue

            dataset.append({"messages": messages})

        return dataset


# ── FinetuneManager ───────────────────────────────────────────────────────────

class FinetuneManager:
    """
    Manage fine-tuning jobs via LlamaFarm's Universal Runtime SFT API.

    All endpoints are on the Universal Runtime (default: http://localhost:11540/v1).

    Fine-tuning works with HuggingFace model IDs (not GGUF paths).
    GGUF export is enabled by default — trained adapters are merged and
    quantized to GGUF for local inference.
    """

    # Default models — HuggingFace format (not GGUF)
    ROUTER_MODEL   = "unsloth/functiongemma-270m-it"
    REASONER_MODEL = "unsloth/Qwen3-1.7B"

    def __init__(self, endpoint: str = "http://localhost:11540/v1"):
        self.endpoint = endpoint.rstrip("/")

    # ── Dataset building ───────────────────────────────────────────────────────

    def load_captures(
        self,
        training_dir: str,
        model_type: str = "all",
    ) -> List[Dict[str, Any]]:
        """
        Load all captured JSONL data from a training directory.

        Args:
            training_dir: Path to .microclaw/training/ or equivalent
            model_type:   "router", "reasoner", or "all"

        Returns:
            List of raw capture dicts
        """
        base = Path(training_dir)
        entries = []

        patterns = {
            "router":   "router_*.jsonl",
            "reasoner": "reasoner_*.jsonl",
            "all":      "*.jsonl",
        }
        glob_pattern = patterns.get(model_type, "*.jsonl")

        for path in sorted(base.glob(glob_pattern)):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        return entries

    def build_router_dataset(
        self,
        training_dir: str,
        deduplicate: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Build a ShareGPT dataset for FunctionGemma fine-tuning.

        Args:
            training_dir: Directory containing router_*.jsonl files
            deduplicate:  Remove duplicate (intent → tool) pairs

        Returns:
            List of ShareGPT conversation dicts
        """
        captures = self.load_captures(training_dir, model_type="router")
        dataset = RouterDatasetBuilder.convert(captures)
        if deduplicate:
            dataset = RouterDatasetBuilder.deduplicate(dataset)
        return dataset

    def build_reasoner_dataset(
        self,
        training_dir: str,
    ) -> List[Dict[str, Any]]:
        """
        Build a Chat format dataset for Qwen3 fine-tuning.

        Args:
            training_dir: Directory containing reasoner_*.jsonl files

        Returns:
            List of OpenAI Chat format dicts
        """
        captures = self.load_captures(training_dir, model_type="reasoner")
        return ReasonerDatasetBuilder.convert(captures)

    # ── API calls ──────────────────────────────────────────────────────────────

    def validate_dataset(
        self,
        dataset: List[Dict[str, Any]],
        dataset_format: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate a dataset via LlamaFarm's /v1/finetune/validate endpoint.

        Returns:
            {"valid": bool, "format": str, "example_count": int,
             "warnings": [...], "errors": [...]}
        """
        import requests

        payload: Dict[str, Any] = {"dataset": dataset}
        if dataset_format:
            payload["dataset_format"] = dataset_format

        r = requests.post(
            f"{self.endpoint}/finetune/validate",
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def submit_sft(
        self,
        model: str,
        dataset: List[Dict[str, Any]],
        dataset_format: str = "auto",
        chat_template: str = "auto",
        epochs: int = 5,
        batch_size: int = 2,
        learning_rate: float = 2e-4,
        lora_rank: int = 8,
        lora_alpha: int = 16,
        max_seq_length: int = 1024,
        train_on_responses_only: bool = True,
        output_gguf: bool = True,
        quantization: str = "q8_0",
        **kwargs: Any,
    ) -> str:
        """
        Submit a supervised fine-tuning job to LlamaFarm.

        Args:
            model:        HuggingFace model ID (NOT a .gguf path)
            dataset:      Training data in ShareGPT or Chat format
            epochs:       Training epochs (5–10 for router, 3–5 for reasoner)
            lora_rank:    LoRA rank (8 for 270M router, 16 for 1.7B reasoner)
            output_gguf:  Export merged GGUF after training
            **kwargs:     Any additional LlamaFarm SFT parameters

        Returns:
            job_id string
        """
        import requests

        payload: Dict[str, Any] = {
            "model":                    model,
            "dataset":                  dataset,
            "dataset_format":           dataset_format,
            "chat_template":            chat_template,
            "epochs":                   epochs,
            "batch_size":               batch_size,
            "learning_rate":            learning_rate,
            "lora_rank":                lora_rank,
            "lora_alpha":               lora_alpha,
            "max_seq_length":           max_seq_length,
            "train_on_responses_only":  train_on_responses_only,
            "output_gguf":              output_gguf,
            "quantization":             quantization,
            **kwargs,
        }

        r = requests.post(
            f"{self.endpoint}/finetune/sft",
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["job_id"]

    def poll(self, job_id: str) -> JobStatus:
        """
        Poll a training job's current status.

        Args:
            job_id: Job ID returned by submit_sft()

        Returns:
            JobStatus with progress, metrics, and output path
        """
        import requests

        r = requests.get(
            f"{self.endpoint}/finetune/jobs/{job_id}",
            timeout=10,
        )
        r.raise_for_status()
        return JobStatus(r.json())

    def wait(
        self,
        job_id: str,
        poll_interval: float = 10.0,
        timeout: Optional[float] = None,
        on_progress: Optional[Any] = None,
    ) -> JobStatus:
        """
        Block until a training job completes (or fails/is cancelled).

        Args:
            job_id:        Job to wait for
            poll_interval: Seconds between status checks (default 10s)
            timeout:       Max seconds to wait (None = no limit)
            on_progress:   Optional callback(status: JobStatus) called each poll

        Returns:
            Final JobStatus

        Raises:
            TimeoutError: If timeout is exceeded
            RuntimeError: If job fails
        """
        start = time.time()
        while True:
            status = self.poll(job_id)
            if on_progress:
                on_progress(status)
            if status.done:
                if not status.succeeded:
                    raise RuntimeError(
                        f"Fine-tuning job {job_id} {status.status}: {status.error}"
                    )
                return status
            if timeout and (time.time() - start) > timeout:
                raise TimeoutError(f"Fine-tuning job {job_id} timed out after {timeout}s")
            time.sleep(poll_interval)

    def list_jobs(self) -> List[Dict[str, Any]]:
        """List all training jobs."""
        import requests

        r = requests.get(f"{self.endpoint}/finetune/jobs", timeout=10)
        r.raise_for_status()
        return r.json().get("jobs", [])

    def cancel(self, job_id: str) -> Dict[str, Any]:
        """Cancel a queued or running job."""
        import requests

        r = requests.delete(
            f"{self.endpoint}/finetune/jobs/{job_id}",
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    # ── Convenience methods ────────────────────────────────────────────────────

    def finetune_router(
        self,
        training_dir: str,
        model: str = ROUTER_MODEL,
        min_examples: int = 10,
        **kwargs: Any,
    ) -> str:
        """
        End-to-end: load router captures → build dataset → submit SFT job.

        Args:
            training_dir: .microclaw/training/ directory with router_*.jsonl
            model:        Model to fine-tune (default: unsloth/functiongemma-270m-it)
            min_examples: Minimum examples required (raises if insufficient)
            **kwargs:     Passed to submit_sft()

        Returns:
            job_id

        Raises:
            ValueError: If insufficient training data
        """
        dataset = self.build_router_dataset(training_dir)
        if len(dataset) < min_examples:
            raise ValueError(
                f"Router dataset has {len(dataset)} examples — need at least {min_examples}. "
                f"Run more agent sessions to collect training data."
            )

        # Router-specific defaults (small model, response-only training)
        kwargs.setdefault("epochs", 10)
        kwargs.setdefault("lora_rank", 8)
        kwargs.setdefault("max_seq_length", 512)
        kwargs.setdefault("learning_rate", 2e-4)
        kwargs.setdefault("batch_size", 4)
        kwargs.setdefault("dataset_format", "sharegpt")
        kwargs.setdefault("chat_template", "gemma")

        print(f"🔧 Router fine-tune: {len(dataset)} examples → {model}")
        job_id = self.submit_sft(model=model, dataset=dataset, **kwargs)
        print(f"✅ Job submitted: {job_id}")
        return job_id

    def finetune_reasoner(
        self,
        training_dir: str,
        model: str = REASONER_MODEL,
        min_examples: int = 5,
        **kwargs: Any,
    ) -> str:
        """
        End-to-end: load reasoner captures → build dataset → submit SFT job.

        Args:
            training_dir: .microclaw/training/ directory with reasoner_*.jsonl
            model:        Model to fine-tune (default: unsloth/Qwen3-1.7B)
            min_examples: Minimum examples required
            **kwargs:     Passed to submit_sft()

        Returns:
            job_id

        Raises:
            ValueError: If insufficient training data
        """
        dataset = self.build_reasoner_dataset(training_dir)
        if len(dataset) < min_examples:
            raise ValueError(
                f"Reasoner dataset has {len(dataset)} examples — need at least {min_examples}. "
                f"Run more agent.reason() calls to collect training data."
            )

        # Reasoner-specific defaults (larger context, more turns)
        kwargs.setdefault("epochs", 3)
        kwargs.setdefault("lora_rank", 16)
        kwargs.setdefault("max_seq_length", 4096)
        kwargs.setdefault("learning_rate", 1e-4)
        kwargs.setdefault("batch_size", 2)
        kwargs.setdefault("dataset_format", "chat")

        print(f"🧠 Reasoner fine-tune: {len(dataset)} examples → {model}")
        job_id = self.submit_sft(model=model, dataset=dataset, **kwargs)
        print(f"✅ Job submitted: {job_id}")
        return job_id

    def gguf_path(self, job_id: str) -> Optional[Path]:
        """
        Return the path to the trained GGUF file for a completed job.

        Returns:
            Path to the GGUF file, or None if not yet available.
        """
        status = self.poll(job_id)
        if not status.output_dir:
            return None
        # LlamaFarm saves GGUF to: {output_dir}/gguf/model-{quantization}.gguf
        gguf_dir = Path(status.output_dir) / "gguf"
        candidates = list(gguf_dir.glob("*.gguf")) if gguf_dir.exists() else []
        return candidates[0] if candidates else None

    def __repr__(self) -> str:
        return f"FinetuneManager(endpoint={self.endpoint!r})"
