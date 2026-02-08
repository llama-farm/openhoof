"""MLX-native inference for the fine-tuned tool router.

This loads the merged model directly via mlx-lm for fast inference
on Apple Silicon. No GGUF conversion needed.

For Linux/CUDA, use the GGUF export with llama.cpp instead.
"""

import json
import time
from pathlib import Path
from typing import Optional

# Lazy imports
_model = None
_tokenizer = None

MODEL_DIR = Path.home() / ".openhoof" / "models" / "tool-router"

TOOL_DEFINITIONS = """memory_write(file: str, content: str, append: bool = false) - Write content to agent memory files
memory_read(file: str) - Read content from workspace files
shared_write(key: str, content: str, tags: list = []) - Write to shared cross-agent knowledge store
shared_read(key: str) - Read from shared cross-agent knowledge store
shared_search(query: str, category: str = null, limit: int = 10) - Search shared knowledge across all agents
shared_log(finding: str, category: str = "general", severity: str = "info") - Log a finding to shared log
spawn_agent(task: str, agent_id: str = null, label: str = null) - Spawn a sub-agent for specialized tasks
notify(title: str, message: str, priority: str = "medium") - Send notification to human operator
exec(command: str, timeout: int = 30) - Execute a shell command
list_tools() - List all available tools"""


def get_latest_model_path() -> Optional[Path]:
    """Find the latest trained model."""
    if not MODEL_DIR.exists():
        return None
    runs = sorted([d for d in MODEL_DIR.iterdir() if d.is_dir() and (d / "merged").exists()])
    if not runs:
        # Try adapter-only
        runs = sorted([d for d in MODEL_DIR.iterdir() if d.is_dir() and (d / "adapters").exists()])
    return runs[-1] if runs else None


def load_model(model_path: Optional[Path] = None):
    """Load the fine-tuned model."""
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    if model_path is None:
        model_path = get_latest_model_path()
    if model_path is None:
        raise RuntimeError("No trained model found. Run training first.")

    merged_path = model_path / "merged"
    adapter_path = model_path / "adapters"

    from mlx_lm import load
    if merged_path.exists():
        print(f"Loading merged model from {merged_path}")
        _model, _tokenizer = load(str(merged_path))
    elif adapter_path.exists():
        print(f"Loading base + adapter from {adapter_path}")
        _model, _tokenizer = load("unsloth/functiongemma-270m-it", adapter_path=str(adapter_path))
    else:
        raise RuntimeError(f"No model found at {model_path}")

    return _model, _tokenizer


def route(user_message: str, tools: Optional[str] = None) -> dict:
    """Route a user message to the appropriate tool(s).

    Returns:
        {
            "tool_calls": [{"name": "...", "arguments": {...}}],
            "latency_ms": float,
            "raw_output": str
        }
    """
    model, tokenizer = load_model()

    if tools is None:
        tools = TOOL_DEFINITIONS

    prompt = (
        f"<start_of_turn>developer\n"
        f"You are a model that can do function calling with the following functions\n\n"
        f"{tools}\n"
        f"<end_of_turn>\n"
        f"<start_of_turn>user\n"
        f"{user_message}\n"
        f"<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )

    from mlx_lm import generate
    start = time.perf_counter()
    response = generate(model, tokenizer, prompt=prompt, max_tokens=150)
    latency = (time.perf_counter() - start) * 1000

    # Parse tool calls from response
    tool_calls = []
    response = response.strip()
    try:
        parsed = json.loads(response)
        if isinstance(parsed, list):
            tool_calls = parsed
    except json.JSONDecodeError:
        # Try to extract JSON array
        if "[" in response:
            try:
                start_idx = response.index("[")
                end_idx = response.rindex("]") + 1
                parsed = json.loads(response[start_idx:end_idx])
                if isinstance(parsed, list):
                    tool_calls = parsed
            except (json.JSONDecodeError, ValueError):
                pass

    return {
        "tool_calls": tool_calls,
        "latency_ms": latency,
        "raw_output": response,
    }


if __name__ == "__main__":
    import sys

    test_messages = sys.argv[1:] or [
        "Save a note about tomorrow's meeting",
        "What tools are available?",
        "Hello there!",
        "Search for weather reports from other agents",
        "Alert the operator: server is down!",
    ]

    for msg in test_messages:
        result = route(msg)
        tools = [tc.get("name", "?") for tc in result["tool_calls"]] or ["(none)"]
        print(f"[{result['latency_ms']:6.1f}ms] {msg:50s} → {', '.join(tools)}")
