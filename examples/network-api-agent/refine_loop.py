"""
Training Refinement Loop for network-api-agent FunctionGemma router.

Implements Ace's cycle: Train → Eval → Categorize misses → Fix → Repeat

Each round:
  1. Evaluate the model on held-out eval set
  2. Categorize every miss (contradiction / zero-coverage / hallucination / wrong-fallback / ambiguous)
  3. Generate targeted fixes (20-60 examples, not hundreds)
  4. Merge with existing training data (base always wins on conflict)
  5. Retrain

Rules (from Ace's experiments):
  - Change data, NOT hyperparameters (epochs=10, lora_rank=8, lr=2e-4 — always fixed)
  - Never remove examples — only append or edit
  - Base (hand-curated) data takes priority on any conflict with generated data
  - Add 3-5 examples per miss pattern (not 1, not 50)
  - Diverse volume wins; artificial balancing hurts (-12 points)

Usage:
    # Evaluate current model and see miss breakdown
    python refine_loop.py eval --job-id abc123

    # Run full round: eval → categorize → generate fixes → merge
    python refine_loop.py round --job-id abc123 --base router_train_v1.jsonl

    # Merge two datasets (base wins on conflict)
    python refine_loop.py merge --base router_train_v1.jsonl --add router_train_v2.jsonl

    # After merge, submit new fine-tuning job
    python refine_loop.py train --file router_train_merged.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.chdir(Path(__file__).parent)

from dotenv import load_dotenv
load_dotenv()

from openhoof import RefinementLoop, FinetuneManager
from tools import ALL_TOOLS

TRAINING_DIR = Path(".microclaw/training")
TODAY = date.today().isoformat()
ENDPOINT = os.getenv("LLAMAFARM_ENDPOINT", "http://localhost:11540/v1")
MODEL    = os.getenv("ROUTER_MODEL", "unsloth/functiongemma-270m-it-GGUF")

# ── Helpers ───────────────────────────────────────────────────────────────────

def latest_eval_file() -> Optional[Path]:
    files = sorted(TRAINING_DIR.glob("router_synthetic_eval_*.jsonl"))
    return files[-1] if files else None

def latest_train_file() -> Optional[Path]:
    files = sorted(TRAINING_DIR.glob("router_synthetic_[0-9]*.jsonl"))
    return files[-1] if files else None


def get_loop() -> RefinementLoop:
    return RefinementLoop(
        tools=ALL_TOOLS,
        training_dir=str(TRAINING_DIR),
        endpoint=ENDPOINT,
        model=MODEL,
        temperature=0.0,
    )


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_eval(args):
    """Evaluate a model on the held-out eval set."""
    eval_file = args.eval_file or str(latest_eval_file())
    if not eval_file:
        print("No eval file found. Run generate_training_data.py first.")
        sys.exit(1)

    loop = get_loop()
    report = loop.eval(
        eval_file=eval_file,
        job_id=args.job_id,
        verbose=True,
    )

    # Save report
    report_path = TRAINING_DIR / f"eval_report_{TODAY}_{args.job_id or 'base'}.json"
    report_data = {
        "model": report.model,
        "eval_file": report.eval_file,
        "accuracy": report.accuracy,
        "correct": report.correct,
        "total": report.total,
        "timestamp": report.timestamp,
        "misses": [
            {
                "input": e.input,
                "expected": e.expected_raw,
                "got": e.got_raw,
            }
            for e in report.misses
        ],
    }
    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=2)
    print(f"\nReport saved: {report_path}")

    if report.misses:
        print(f"\n{report.miss_report()}")

    return report


def cmd_categorize(args):
    """Categorize misses from a previous eval report."""
    report_files = sorted(TRAINING_DIR.glob("eval_report_*.json"))
    if not report_files:
        print("No eval reports found. Run 'eval' first.")
        sys.exit(1)

    # Load latest report
    report_path = report_files[-1]
    print(f"Loading: {report_path}")

    with open(report_path) as f:
        data = json.load(f)

    # Reconstruct report object
    from openhoof import EvalReport, EvalExample
    report = EvalReport(model=data["model"], eval_file=data["eval_file"])
    report.timestamp = data.get("timestamp", "")
    for miss in data.get("misses", []):
        report.examples.append(EvalExample(
            input=miss["input"],
            expected_tool=miss["expected"].split("(")[0],
            expected_raw=miss["expected"],
            got_tool=miss["got"].split("(")[0],
            got_raw=miss["got"],
            correct=False,
        ))

    loop = get_loop()
    cat_report = loop.categorize(report, training_file=str(latest_train_file()))

    # Suggest targeted fixes
    print("\n" + "=" * 60)
    print("SUGGESTED TARGETED EXAMPLES")
    print("=" * 60)
    suggestions = loop.suggest_targeted_examples(cat_report, n_per_miss=3)
    print(f"Generated {len(suggestions)} targeted examples")
    print(f"(Ace's rule: 20-60 per round max; this is {len(suggestions)} — {'✅ ok' if len(suggestions) <= 60 else '⚠️ trim it'})")

    if args.save_fixes and suggestions:
        fixes_path = TRAINING_DIR / f"targeted_fixes_{TODAY}.jsonl"
        with open(fixes_path, "a") as f:
            for ex in suggestions:
                f.write(json.dumps(ex) + "\n")
        print(f"\nFixes saved: {fixes_path}")
        print(f"Next: run 'merge' to combine with your base training data")

    return cat_report, suggestions


def cmd_merge(args):
    """Merge two datasets with base-priority conflict resolution."""
    base = args.base or str(latest_train_file())
    if not base or not Path(base).exists():
        print("No base training file found.")
        sys.exit(1)

    addition = args.add
    if not addition or not Path(addition).exists():
        # Default: merge with latest targeted fixes
        fixes = sorted(TRAINING_DIR.glob("targeted_fixes_*.jsonl"))
        if fixes:
            addition = str(fixes[-1])
        else:
            print("No addition file found. Run 'categorize --save-fixes' first.")
            sys.exit(1)

    output = args.output or str(TRAINING_DIR / f"router_train_merged_{TODAY}.jsonl")

    loop = get_loop()
    stats = loop.merge(
        base=base,
        addition=addition,
        output=output,
        base_priority=True,
        verbose=True,
    )

    print(f"\nNext step: run 'train --file {output}'")
    return stats


def cmd_train(args):
    """Submit a fine-tuning job to LlamaFarm."""
    train_file = args.file or str(latest_train_file())
    if not train_file or not Path(train_file).exists():
        print("No training file found.")
        sys.exit(1)

    ft = FinetuneManager(endpoint=ENDPOINT)

    print(f"\nSubmitting fine-tuning job...")
    print(f"  File:   {train_file}")
    print(f"  Model:  unsloth/functiongemma-270m-it")
    print(f"  Params: epochs=10, lora_rank=8, lr=2e-4  (fixed — only data changes)")

    job_id = ft.finetune_router(
        training_dir=str(TRAINING_DIR),
        training_file=train_file,
        model="unsloth/functiongemma-270m-it",
        epochs=10,
        lora_rank=8,
        wait=True,
        auto_promote=True,
    )

    print(f"\n✅ Training complete: ft:{job_id}")
    print(f"Next: run 'eval --job-id {job_id}' to check accuracy")

    return job_id


def cmd_round(args):
    """
    Run a full refinement round:
    eval → categorize → save fixes → merge → (optionally) retrain

    This is Ace's 15-minute cycle:
      5 min train → 2 min eval → 8 min analysis and data fixes
    """
    print("\n" + "=" * 60)
    print("REFINEMENT ROUND")
    print("=" * 60)

    # Step 1: Eval
    print("\n[1/4] Evaluating model...")
    args.eval_file = None
    report = cmd_eval(args)

    if report.accuracy >= 0.95:
        print(f"\n✅ Accuracy {report.accuracy:.1%} — already excellent. No round needed.")
        return

    # Step 2: Categorize misses
    print("\n[2/4] Categorizing misses...")
    args.save_fixes = True
    cat_report, suggestions = cmd_categorize(args)

    if not suggestions:
        print("No targeted fixes generated. All misses are ambiguous or unknown.")
        return

    # Step 3: Merge
    print("\n[3/4] Merging datasets...")
    fixes_path = TRAINING_DIR / f"targeted_fixes_{TODAY}.jsonl"
    args.add    = str(fixes_path)
    args.output = str(TRAINING_DIR / f"router_train_merged_{TODAY}.jsonl")
    args.base   = args.base or str(latest_train_file())
    cmd_merge(args)

    # Step 4: Optionally retrain
    if args.train:
        print("\n[4/4] Retraining...")
        args.file = args.output
        cmd_train(args)
    else:
        print(f"\n[4/4] Skipping retrain (pass --train to auto-train).")
        print(f"       Run: python refine_loop.py train --file {args.output}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Training refinement loop for network-api-agent FunctionGemma"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # eval
    p_eval = sub.add_parser("eval", help="Evaluate model on held-out eval set")
    p_eval.add_argument("--job-id",    help="Fine-tuned job ID (adds ft: prefix)")
    p_eval.add_argument("--eval-file", help="Path to eval JSONL (default: latest)")

    # categorize
    p_cat = sub.add_parser("categorize", help="Categorize misses from last eval report")
    p_cat.add_argument("--save-fixes", action="store_true", help="Save targeted fixes to JSONL")

    # merge
    p_merge = sub.add_parser("merge", help="Merge datasets (base wins on conflict)")
    p_merge.add_argument("--base",   help="Base JSONL (higher priority)")
    p_merge.add_argument("--add",    help="Addition JSONL to merge in")
    p_merge.add_argument("--output", help="Output JSONL path")

    # train
    p_train = sub.add_parser("train", help="Submit fine-tuning job to LlamaFarm")
    p_train.add_argument("--file", help="Training JSONL to use")

    # round
    p_round = sub.add_parser("round", help="Full refinement round (eval → categorize → merge → retrain)")
    p_round.add_argument("--job-id",    help="Fine-tuned job ID to evaluate")
    p_round.add_argument("--base",      help="Base training JSONL")
    p_round.add_argument("--eval-file", help="Eval JSONL (default: latest)")
    p_round.add_argument("--train",     action="store_true", help="Auto-retrain after merge")

    args = parser.parse_args()

    TRAINING_DIR.mkdir(parents=True, exist_ok=True)

    commands = {
        "eval":       cmd_eval,
        "categorize": cmd_categorize,
        "merge":      cmd_merge,
        "train":      cmd_train,
        "round":      cmd_round,
    }
    commands[args.command](args)


# Allow Optional import without typing module at top level
from typing import Optional
if __name__ == "__main__":
    main()
