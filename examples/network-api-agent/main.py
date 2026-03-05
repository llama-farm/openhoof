"""
Network API Agent — FunctionGemma router with live device context.

Flow:
  1. On startup, fetch /api/status (or demo fixture) → compact context prefix
  2. For each user input, prepend the context prefix
  3. Route the augmented string through FunctionGemma
  4. Execute the tool call via chud proxy
  5. Refresh context after mutations

Context prefix example:
  [radios: r0=HomeNet/2.4G/ON r1=HomeNet_5G/5G/ON r2=Guest/2.4G/OFF r3=IoT_Net/5G/ON]
  [vlans: 1=default 10=mgmt 20=data 100=guest 200=iot]
  [ports: p1=up/1G/v10 p2=up/100M/v20 p3=down p4=up/1G/trunk p5=up/1G/trunk]
  [clients: 8]

Usage:
    python main.py              # live mode (requires chud + real devices)
    python main.py --demo       # demo mode (simulated device state)
    python main.py --dry-run    # route without executing
    python main.py --eval       # accuracy eval on held-out set
    python main.py --no-context # disable context prefix (baseline)
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
from context import DeviceContext

ENDPOINT     = os.getenv("LLAMAFARM_ENDPOINT", "http://localhost:11540/v1")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "ft:ed61bef1")
CHUD_URL     = os.getenv("CHUD_URL", "http://localhost:8080")


def _fmt(result: object) -> str:
    if isinstance(result, dict) and "error" in result:
        return f"❌  {result['error']}"
    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2)
    return str(result)


def repl(dry_run: bool = False, demo: bool = False, use_context: bool = True):
    from api import NetworkToolExecutor

    # Build context
    if use_context:
        if demo:
            ctx = DeviceContext.demo()
            ctx.refresh()
        else:
            ctx = DeviceContext(chud_url=CHUD_URL)
            try:
                ctx.refresh()
            except Exception as e:
                print(f"⚠️  Could not fetch device status ({e}) — falling back to demo")
                ctx = DeviceContext.demo()
                ctx.refresh()
    else:
        ctx = None

    # Build router
    router = ToolRouter(
        endpoint=ENDPOINT,
        model=ROUTER_MODEL,
        temperature=0.0,
        max_tokens=64,
        strip_tool_descriptions=True,
    )

    # Build executor
    executor = NetworkToolExecutor(chud_url=CHUD_URL) if not dry_run else None

    # Print startup summary
    print("\n" + "=" * 60)
    print(f"Network API Agent  (FunctionGemma router)")
    print(f"Model  : {ROUTER_MODEL}")
    print(f"Mode   : {'demo' if demo else 'live'}  {'dry-run' if dry_run else ''}  {'no-context' if not use_context else ''}")
    print("=" * 60)

    if ctx and ctx.status:
        print("\nDevice state:")
        print(ctx.summary())

    if ctx:
        print(f"\nContext prefix:\n  {ctx.prefix}\n")

    print("Type a command or 'quit' to exit. 'refresh' re-fetches device state.\n")

    # Mutation tools that should trigger a context refresh
    MUTATION_TOOLS = {
        "router_create_vlan", "router_delete_vlan", "router_update_lan",
        "router_update_wifi_ssid", "router_update_firewall",
        "router_add_static_route", "router_add_dns_host",
        "switch_create_vlan", "switch_delete_vlan",
        "switch_set_vlan_membership", "switch_set_port_pvid",
    }

    while True:
        try:
            raw_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not raw_input:
            continue
        if raw_input.lower() in ("quit", "exit", "q"):
            print("Bye.")
            break
        if raw_input.lower() == "refresh":
            if ctx:
                ctx.refresh(force=True)
                print(f"Context refreshed:\n  {ctx.prefix}\n")
            continue
        if raw_input.lower() == "status":
            if ctx:
                print(ctx.summary())
            continue
        if raw_input.lower() in ("help", "?"):
            print("Available tools:")
            for t in ALL_TOOLS:
                fn = t.get("function", t)
                print(f"  {fn['name']}")
            print("\nCommands: refresh, status, quit")
            continue

        # Augment with device context
        query = ctx.augment(raw_input) if ctx else raw_input

        if ctx and query != raw_input:
            print(f"  [augmented]: {query[:120]}{'...' if len(query) > 120 else ''}")

        # Route through FunctionGemma
        try:
            result = router.route(query, ALL_TOOLS)
        except Exception as e:
            print(f"❌ Router error: {e}\n")
            continue

        tool_name = result.tool_name
        params    = result.params
        conf      = result.confidence

        if not tool_name:
            print(f"⚠️  No tool matched. Raw: {result.raw_content!r}\n")
            continue

        conf_str  = f"  ({conf:.0%} confidence)" if conf else ""
        params_str = ", ".join(f"{k}={v!r}" for k, v in params.items())
        print(f"→  {tool_name}({params_str}){conf_str}")

        if dry_run:
            print()
            continue

        # Execute via chud
        try:
            output = executor.execute(tool_name, params)
            print(_fmt(output))
        except Exception as e:
            print(f"❌ Execution error: {e}")

        # Refresh context after mutations
        if ctx and tool_name in MUTATION_TOOLS:
            try:
                ctx.refresh(force=True)
                print(f"  [context refreshed]")
            except Exception:
                pass

        print()


def run_eval(use_context: bool = True, demo: bool = True):
    """Accuracy eval on held-out set, optionally with context augmentation."""
    training_dir = Path(".microclaw/training")
    eval_files = sorted(training_dir.glob("router_eval_v3.jsonl"))
    if not eval_files:
        eval_files = sorted(training_dir.glob("router_eval_balanced.jsonl"))
    if not eval_files:
        print("No eval files found.")
        return

    eval_file = eval_files[-1]
    print(f"Eval: {eval_file.name}  Model: {ROUTER_MODEL}")

    # Build context for augmentation
    ctx = DeviceContext.demo() if (use_context and demo) else None
    if ctx:
        ctx.refresh()
        print(f"Context: {ctx.prefix[:100]}...")

    from openhoof import RefinementLoop
    loop = RefinementLoop(
        tools=ALL_TOOLS,
        training_dir=str(training_dir),
        endpoint=ENDPOINT,
        model=ROUTER_MODEL,
    )

    # If using context, augment the eval examples
    if ctx:
        # Load eval, augment, write to temp file, eval against temp
        import tempfile, json as _json
        examples = []
        with open(eval_file) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                ex = _json.loads(line)
                convs = ex.get("conversations", [])
                h = next((c["value"] for c in convs if c.get("from") == "human"), "")
                if h:
                    convs[0]["value"] = ctx.augment(h)
                examples.append(ex)

        tmp = Path(tempfile.mktemp(suffix=".jsonl"))
        with open(tmp, "w") as f:
            for ex in examples:
                f.write(_json.dumps(ex) + "\n")
        report = loop.eval(eval_file=str(tmp), verbose=True)
        tmp.unlink(missing_ok=True)
    else:
        report = loop.eval(eval_file=str(eval_file), verbose=True)

    print(report.miss_report())

    # Categorize misses
    if report.misses:
        cat_report = loop.categorize(report, verbose=True)


def main():
    parser = argparse.ArgumentParser(description="Network API Agent (FunctionGemma)")
    parser.add_argument("--demo",        action="store_true", help="Use simulated device state (no real devices)")
    parser.add_argument("--dry-run",     action="store_true", help="Route without executing")
    parser.add_argument("--no-context",  action="store_true", help="Disable context prefix")
    parser.add_argument("--eval",        action="store_true", help="Run accuracy eval")
    args = parser.parse_args()

    use_ctx = not args.no_context

    if args.eval:
        run_eval(use_context=use_ctx, demo=args.demo or True)
    else:
        repl(dry_run=args.dry_run, demo=args.demo, use_context=use_ctx)


if __name__ == "__main__":
    main()
