"""Training pipeline API routes."""

import json
from pathlib import Path
from fastapi import APIRouter

router = APIRouter(prefix="/api/training", tags=["training"])

DATA_DIR = Path.home() / ".openhoof" / "data" / "function_pipeline"
MODEL_DIR = Path.home() / ".openhoof" / "models" / "tool-router"


def count_by_source(path: Path) -> dict:
    """Count examples by source and tool."""
    curated = 0
    synthetic = 0
    live = 0
    by_tool: dict = {}

    if not path.exists():
        return {"curated": curated, "synthetic": synthetic, "live": live, "by_tool": by_tool}

    for line in path.open():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            meta = entry.get("metadata", {})
            source = meta.get("source", "")

            if "curated" in source or "manual" in source:
                curated += 1
            elif "synthetic" in source or "pipeline" in source or "teacher" in source:
                synthetic += 1
            else:
                live += 1

            tool = meta.get("tool", "unknown")
            by_tool[tool] = by_tool.get(tool, 0) + 1
        except json.JSONDecodeError:
            continue

    return {"curated": curated, "synthetic": synthetic, "live": live, "by_tool": by_tool}


@router.get("/stats")
async def get_training_stats():
    """Get training pipeline statistics."""
    # Count training data
    synthetic_path = DATA_DIR / "synthetic_training.jsonl"
    live_path = DATA_DIR / "training_data.jsonl"

    synthetic_stats = count_by_source(synthetic_path)
    live_stats = count_by_source(live_path)

    total = (
        synthetic_stats["curated"]
        + synthetic_stats["synthetic"]
        + synthetic_stats["live"]
        + live_stats["curated"]
        + live_stats["synthetic"]
        + live_stats["live"]
    )

    # Merge by_tool
    by_tool = {**synthetic_stats["by_tool"]}
    for k, v in live_stats["by_tool"].items():
        by_tool[k] = by_tool.get(k, 0) + v

    # Get latest training run
    latest_run = None
    if MODEL_DIR.exists():
        runs = sorted([d for d in MODEL_DIR.iterdir() if d.is_dir()])
        for run_dir in reversed(runs):
            meta_path = run_dir / "training_meta.json"
            if meta_path.exists():
                latest_run = json.loads(meta_path.read_text())
                break

    # Get experiment results
    experiment_results = {}
    results_path = DATA_DIR / "experiment_results.json"
    if results_path.exists():
        raw = json.loads(results_path.read_text())
        for key, val in raw.items():
            if isinstance(val, dict) and "accuracy" in val:
                # Clean up key names
                name = key.replace("router_", "").replace("-GGUF", "")
                experiment_results[name] = val

    return {
        "total_examples": total,
        "curated": synthetic_stats["curated"] + live_stats["curated"],
        "synthetic": synthetic_stats["synthetic"] + live_stats["synthetic"],
        "live": synthetic_stats["live"] + live_stats["live"],
        "by_tool": by_tool,
        "latest_run": latest_run,
        "experiment_results": experiment_results,
    }
