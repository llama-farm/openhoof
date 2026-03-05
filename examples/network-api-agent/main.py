"""
Network API Agent — FunctionGemma ONLY.

Routes user intents to Cradlepoint R980 and Netgear GS105Ev2 API calls
using a fine-tuned (or base) FunctionGemma 270M model.

No reasoning model. FunctionGemma sees the user intent and returns a tool call.
The app executes it and prints the result.

Usage:
    cp .env.example .env && vim .env   # set credentials
    python main.py                     # interactive REPL
    python main.py --dry-run           # show routing without calling devices
    python main.py --eval              # run accuracy eval against held-out set
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.chdir(Path(__file__).parent)

from dotenv import load_dotenv
load_dotenv()

from openhoof import ToolRouter
from tools import ALL_TOOLS


# ── Config ────────────────────────────────────────────────────────────────────

ENDPOINT      = os.getenv("LLAMAFARM_ENDPOINT", "http://localhost:11540/v1")
ROUTER_MODEL  = os.getenv("ROUTER_MODEL", "unsloth/functiongemma-270m-it-GGUF")
ROUTER_HOST   = os.getenv("ROUTER_HOST")
ROUTER_USER   = os.getenv("ROUTER_USERNAME", "admin")
ROUTER_PASS   = os.getenv("ROUTER_PASSWORD")
SWITCH_HOST   = os.getenv("SWITCH_HOST")
SWITCH_PASS   = os.getenv("SWITCH_PASSWORD")


# ── Lazy device sessions ──────────────────────────────────────────────────────

def _router_session():
    from api import CradlepointSession
    if not ROUTER_HOST or not ROUTER_PASS:
        raise RuntimeError("Set ROUTER_HOST and ROUTER_PASSWORD in .env")
    sess = CradlepointSession(ROUTER_HOST, ROUTER_USER, ROUTER_PASS)
    sess.login()
    return sess

def _switch_session():
    from api import NetgearSession
    if not SWITCH_HOST or not SWITCH_PASS:
        raise RuntimeError("Set SWITCH_HOST and SWITCH_PASSWORD in .env")
    sess = NetgearSession(SWITCH_HOST, SWITCH_PASS)
    sess.login()
    return sess


# ── Result formatter ──────────────────────────────────────────────────────────

def _fmt(result: object, tool_name: str) -> str:
    """Format a tool result for display."""
    if isinstance(result, dict) and "error" in result:
        return f"❌  Error: {result['error']}"
    if isinstance(result, list):
        if not result:
            return "(no results)"
        return json.dumps(result, indent=2)
    if isinstance(result, dict):
        return json.dumps(result, indent=2)
    return str(result)


# ── REPL ──────────────────────────────────────────────────────────────────────

def repl(dry_run: bool = False):
    from api import NetworkToolExecutor

    print("\nNetwork API Agent  (FunctionGemma router)")
    print(f"Model : {ROUTER_MODEL}")
    print(f"Mode  : {'dry-run (no device calls)' if dry_run else 'live'}")
    if not dry_run:
        if not ROUTER_HOST:
            print("⚠️   ROUTER_HOST not set — router tools will fail")
        if not SWITCH_HOST:
            print("⚠️   SWITCH_HOST not set — switch tools will fail")
    print("Type a command or 'quit' to exit.\n")

    # Build router
    router = ToolRouter(
        tools=ALL_TOOLS,
        endpoint=ENDPOINT,
        model=ROUTER_MODEL,
        temperature=0.05,
        max_tokens=256,
    )

    # Build executor (lazy — only connects when a tool is actually called)
    router_sess = switch_sess = None
    if not dry_run:
        try:
            print("Connecting to devices...")
            if ROUTER_HOST and ROUTER_PASS:
                router_sess = _router_session()
                print(f"  ✅ Router: {ROUTER_HOST}")
            if SWITCH_HOST and SWITCH_PASS:
                switch_sess = _switch_session()
                print(f"  ✅ Switch: {SWITCH_HOST}")
            print()
        except Exception as e:
            print(f"  ⚠️  Device connect warning: {e}\n")

    executor = None
    if not dry_run:
        from api import NetworkToolExecutor
        executor = NetworkToolExecutor(router=router_sess, switch=switch_sess)

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Bye.")
            break
        if user_input.lower() in ("help", "?"):
            print("Available tools:")
            for t in ALL_TOOLS:
                fn = t.get("function", t)
                print(f"  {fn['name']} — {fn.get('description','')[:60]}")
            continue

        # Route with FunctionGemma
        try:
            result = router.route(user_input)
        except Exception as e:
            print(f"❌ Router error: {e}\n")
            continue

        tool_name = result.get("tool")
        params    = result.get("parameters", {})
        conf      = result.get("confidence")

        if not tool_name:
            raw = result.get("raw_output", "")
            print(f"⚠️  No tool matched. Model output: {raw!r}\n")
            continue

        conf_str = f"  (confidence: {conf:.0%})" if conf is not None else ""
        call_str = f"{tool_name}({', '.join(f'{k}={v!r}' for k,v in params.items())})"
        print(f"→  {call_str}{conf_str}")

        if dry_run:
            print()
            continue

        if executor is None:
            print("(executor not initialized — check .env)\n")
            continue

        # Execute
        try:
            output = executor.execute(tool_name, params)
            print(_fmt(output, tool_name))
        except Exception as e:
            print(f"❌ Execution error: {e}")
        print()


# ── Eval ──────────────────────────────────────────────────────────────────────

def run_eval():
    from pathlib import Path
    from collections import defaultdict

    training_dir = Path(".microclaw/training")
    eval_files = sorted(training_dir.glob("router_synthetic_eval_*.jsonl"))
    if not eval_files:
        print("No eval files found. Run generate_training_data.py first.")
        return

    eval_file = eval_files[-1]
    print(f"\nEval file: {eval_file}")

    examples = []
    with open(eval_file) as f:
        for line in f:
            line = line.strip()
            if line:
                ex = json.loads(line)
                convs = ex.get("conversations", [])
                if len(convs) >= 2:
                    examples.append({
                        "input": convs[0]["value"],
                        "expected": convs[1]["value"],
                    })

    print(f"Examples: {len(examples)}")
    print(f"Model:    {ROUTER_MODEL}")
    print(f"Endpoint: {ENDPOINT}\n")

    router = ToolRouter(
        tools=ALL_TOOLS,
        endpoint=ENDPOINT,
        model=ROUTER_MODEL,
        temperature=0.0,
        max_tokens=256,
    )

    correct = 0
    wrong = []
    by_tool: dict = defaultdict(lambda: {"correct": 0, "total": 0})

    for i, ex in enumerate(examples):
        expected_tool = ex["expected"].split("(")[0]
        by_tool[expected_tool]["total"] += 1

        try:
            result = router.route(ex["input"])
            got_tool = result.get("tool", "")
            got_params = result.get("parameters", {})
            got_str = f"{got_tool}({', '.join(f'{k}={v!r}' for k,v in got_params.items())})"
        except Exception as e:
            got_tool = ""
            got_str = f"ERROR: {e}"

        match = got_tool == expected_tool
        if match:
            correct += 1
            by_tool[expected_tool]["correct"] += 1
        else:
            wrong.append({
                "input":    ex["input"],
                "expected": ex["expected"],
                "got":      got_str,
            })

        if (i + 1) % 10 == 0:
            pct = correct / (i + 1) * 100
            print(f"  [{i+1:3d}/{len(examples)}]  running accuracy: {pct:.1f}%")

    total = len(examples)
    accuracy = correct / total if total else 0

    print(f"\n{'='*50}")
    print(f"ACCURACY: {accuracy:.1%}  ({correct}/{total})")
    print(f"{'='*50}\n")

    if accuracy >= 0.90:
        print("✅ Ready to ship.")
    elif accuracy >= 0.80:
        print("⚠️  Acceptable — add more examples for failing tools and retrain.")
    else:
        print("❌ Below threshold — check for conflicts or distribution issues.")

    print("\nPer-tool accuracy:")
    for tool, stats in sorted(by_tool.items(), key=lambda x: x[1]["correct"] / max(x[1]["total"], 1)):
        n = stats["total"]
        c = stats["correct"]
        pct = c / n if n else 0
        bar = "█" * int(pct * 20)
        flag = "  ✅" if pct >= 0.9 else ("  ⚠️" if pct >= 0.7 else "  ❌")
        print(f"  {pct:5.0%}  {bar:<20s}  {c}/{n}  {tool}{flag}")

    if wrong:
        print(f"\nFailed examples ({len(wrong)}):")
        for ex in wrong[:20]:
            print(f"  input:    {ex['input']!r}")
            print(f"  expected: {ex['expected']}")
            print(f"  got:      {ex['got']}")
            print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Network API Agent (FunctionGemma router)")
    parser.add_argument("--dry-run", action="store_true", help="Route without calling devices")
    parser.add_argument("--eval",    action="store_true", help="Run accuracy eval on held-out set")
    args = parser.parse_args()

    if args.eval:
        run_eval()
    else:
        repl(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
