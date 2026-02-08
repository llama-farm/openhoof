#!/usr/bin/env python3
"""Automated training pipeline for the OpenHoof tool router.

This is the full pipeline:
1. Collect training data (from live usage + synthetic generation)
2. Prepare dataset
3. LoRA fine-tune FunctionGemma
4. Export to GGUF
5. Hot-swap the model in LlamaFarm
6. Validate with test cases

Can be triggered manually or via cron/heartbeat.

Usage:
    # Full pipeline
    python training/pipeline.py run

    # Just generate more synthetic data
    python training/pipeline.py generate --count 50

    # Check status
    python training/pipeline.py status

    # Export existing training data for inspection
    python training/pipeline.py export
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime

DATA_DIR = Path.home() / ".openhoof" / "data" / "function_pipeline"
MODEL_DIR = Path.home() / ".openhoof" / "models" / "tool-router"


def cmd_status():
    """Show pipeline status."""
    print("🦙 OpenHoof Tool Router Pipeline Status\n")

    # Training data
    total = 0
    for name in ["synthetic_training.jsonl", "training_data.jsonl"]:
        path = DATA_DIR / name
        if path.exists():
            count = sum(1 for line in path.open() if line.strip())
            print(f"  📊 {name}: {count} examples")
            total += count
        else:
            print(f"  📊 {name}: (none)")

    print(f"  📊 Total training data: {total}")
    print(f"  {'✅' if total >= 100 else '⏳'} Ready for training: {'Yes' if total >= 100 else f'Need {100-total} more'}")

    # Outcomes
    outcomes_path = DATA_DIR / "outcomes.jsonl"
    if outcomes_path.exists():
        count = sum(1 for line in outcomes_path.open() if line.strip())
        print(f"  📊 Outcome feedback: {count}")

    # Trained models
    print()
    if MODEL_DIR.exists():
        runs = sorted(MODEL_DIR.iterdir())
        for run_dir in runs:
            meta_path = run_dir / "training_meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                print(f"  🧠 {run_dir.name}:")
                print(f"     Examples: {meta.get('training_examples', '?')}")
                print(f"     Loss:     {meta.get('final_loss', '?'):.4f}" if isinstance(meta.get('final_loss'), (int, float)) else f"     Loss:     {meta.get('final_loss', '?')}")
                print(f"     Backend:  {meta.get('backend', '?')}")
                print(f"     Date:     {meta.get('timestamp', '?')[:19]}")
    else:
        print("  🧠 No trained models yet")

    # Experiment results
    results_path = DATA_DIR / "experiment_results.json"
    if results_path.exists():
        results = json.loads(results_path.read_text())
        print(f"\n  📈 Last experiment results:")
        for name, data in results.items():
            if isinstance(data, dict) and "accuracy" in data:
                print(f"     {name}: {data['accuracy']:.1f}% accuracy, {data.get('avg_latency_ms', 0):.0f}ms")


def cmd_generate(count: int = 50):
    """Generate more synthetic training data."""
    print(f"Generating {count} synthetic training examples...\n")

    # Use the experiment script's synthetic generation
    sys.path.insert(0, str(Path(__file__).parent.parent))

    async def _generate():
        import aiohttp

        UNIVERSAL_URL = "http://localhost:11540/v1/chat/completions"
        TOOLS_DESC = """Available functions:
  memory_write(file, content, append): Write content to agent memory files
  memory_read(file): Read content from workspace files
  shared_write(key, content, tags): Write to shared cross-agent knowledge store
  shared_read(key): Read from shared cross-agent knowledge store
  shared_search(query, category, limit): Search shared knowledge and findings
  shared_log(finding, category, severity): Log a finding to shared log
  spawn_agent(task, agent_id, label): Spawn a sub-agent for specialized tasks
  notify(title, message, priority): Send notification to human operator
  exec(command, timeout): Execute a shell command
  list_tools(): List all available tools"""

        tools = ['memory_write','memory_read','shared_write','shared_read',
                 'shared_search','shared_log','spawn_agent','notify','exec','list_tools']

        categories = [
            ("memory_write", "writing notes, saving data, recording events, updating memory"),
            ("memory_read", "reading files, checking notes, looking up past data"),
            ("shared_write", "sharing data with other agents, publishing findings"),
            ("shared_search", "searching for data from other agents, finding information"),
            ("shared_log", "logging findings, recording anomalies, flagging issues"),
            ("notify", "alerting humans, sending notifications, urgent messages"),
            ("exec", "running commands, checking system status, executing scripts"),
            ("spawn_agent", "delegating tasks, getting specialist help, spawning sub-agents"),
            ("none", "casual conversation, general knowledge questions, greetings"),
            ("multi", "tasks requiring multiple tools in combination"),
        ]

        data_path = DATA_DIR / "synthetic_training.jsonl"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        generated = 0

        async with aiohttp.ClientSession() as session:
            # Check runtime
            try:
                async with session.get("http://localhost:11540/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        print("❌ Universal runtime not available")
                        return 0
            except:
                print("❌ Cannot connect to universal runtime at localhost:11540")
                return 0

            per_category = max(1, count // len(categories))

            for tool_name, desc in categories:
                if tool_name == "multi":
                    prompt = f"""Generate {per_category} realistic user messages that require MULTIPLE tools from the list.

{TOOLS_DESC}

Output a JSON array. Each element: {{"user_message": "...", "tool_calls": [{{"name": "tool1", "arguments": {{}}}}, {{"name": "tool2", "arguments": {{}}}}]}}
Generate diverse examples combining 2-3 tools."""
                elif tool_name == "none":
                    prompt = f"""Generate {per_category} user messages that do NOT require any tool call. These should be casual chat, general questions, or acknowledgments.

Output a JSON array: [{{"user_message": "...", "tool_calls": []}}]"""
                else:
                    prompt = f"""Generate {per_category} diverse, realistic user messages for the "{tool_name}" function ({desc}).

{TOOLS_DESC}

Output a JSON array: [{{"user_message": "...", "tool_calls": [{{"name": "{tool_name}", "arguments": {{...}}}}]}}]
Include realistic argument values."""

                try:
                    body = {
                        "model": "unsloth/Qwen3-1.7B-GGUF:Q4_K_M",  # Use what we have
                        "messages": [
                            {"role": "system", "content": "Generate training data. Output ONLY valid JSON arrays."},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 1500,
                        "temperature": 0.9,
                    }

                    async with session.post(UNIVERSAL_URL, json=body, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                        if resp.status != 200:
                            print(f"  ⚠️ Failed for {tool_name}")
                            continue
                        data = await resp.json()

                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                    if "[" in content:
                        start = content.index("[")
                        end = content.rindex("]") + 1
                        examples = json.loads(content[start:end])

                        batch = 0
                        for ex in examples:
                            if isinstance(ex, dict) and "user_message" in ex:
                                entry = {
                                    "input": {"user_message": ex["user_message"], "tools": tools},
                                    "output": {"tool_calls": ex.get("tool_calls", [])},
                                    "metadata": {"source": "pipeline_synthetic", "target": tool_name,
                                                 "timestamp": datetime.now().isoformat()}
                                }
                                with open(data_path, "a") as f:
                                    f.write(json.dumps(entry) + "\n")
                                generated += 1
                                batch += 1
                        print(f"  ✅ {tool_name}: {batch} examples")

                except Exception as e:
                    print(f"  ⚠️ {tool_name}: {e}")

        return generated

    generated = asyncio.run(_generate())
    total = sum(1 for line in (DATA_DIR / "synthetic_training.jsonl").open() if line.strip())
    print(f"\nGenerated {generated} new examples. Total: {total}")


def cmd_export():
    """Export training data in different formats for inspection."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Load all data
    examples = []
    for name in ["synthetic_training.jsonl", "training_data.jsonl"]:
        path = DATA_DIR / name
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
                examples.append({
                    "user_message": inp.get("user_message", ""),
                    "tool_calls": out.get("tool_calls", []),
                    "source": entry.get("metadata", {}).get("source", "unknown"),
                })
            except json.JSONDecodeError:
                continue

    # Export as Alpaca format
    alpaca_path = DATA_DIR / "export_alpaca.jsonl"
    with open(alpaca_path, "w") as f:
        for ex in examples:
            f.write(json.dumps({
                "instruction": "Select the appropriate tool(s) for the user's request. Respond with a JSON array.",
                "input": ex["user_message"],
                "output": json.dumps(ex["tool_calls"]),
            }) + "\n")

    # Export as CSV for easy viewing
    csv_path = DATA_DIR / "export_overview.csv"
    with open(csv_path, "w") as f:
        f.write("user_message,tools_called,source\n")
        for ex in examples:
            tools_str = ";".join(c.get("name", "") for c in ex["tool_calls"] if isinstance(c, dict))
            msg = ex["user_message"].replace('"', '""')
            f.write(f'"{msg}","{tools_str}","{ex["source"]}"\n')

    # Stats by tool
    from collections import Counter
    tool_counts = Counter()
    for ex in examples:
        for tc in ex["tool_calls"]:
            if isinstance(tc, dict):
                tool_counts[tc.get("name", "unknown")] += 1
        if not ex["tool_calls"]:
            tool_counts["(no tool)"] += 1

    print(f"Exported {len(examples)} examples:")
    print(f"  Alpaca: {alpaca_path}")
    print(f"  CSV:    {csv_path}")
    print(f"\nTool distribution:")
    for tool, count in tool_counts.most_common():
        print(f"  {tool}: {count}")


def cmd_run(args):
    """Run the full training pipeline."""
    print("🦙 OpenHoof Tool Router Training Pipeline\n")

    # Step 1: Check data
    total = 0
    for name in ["synthetic_training.jsonl", "training_data.jsonl"]:
        path = DATA_DIR / name
        if path.exists():
            total += sum(1 for line in path.open() if line.strip())

    print(f"Step 1: Data check — {total} examples available")

    if total < 50 and not args.force:
        print(f"  Need at least 50 examples. Generating more...")
        cmd_generate(100)
        total = sum(1 for line in (DATA_DIR / "synthetic_training.jsonl").open() if line.strip())

    # Step 2: Train
    print(f"\nStep 2: Training with {total} examples...")
    from training.train_tool_router import train
    meta = train(
        backend=args.backend,
        epochs=args.epochs,
        learning_rate=args.lr,
        batch_size=args.batch_size,
        format_style=args.format,
    )

    if meta:
        print(f"\n✅ Pipeline complete! Model saved to {meta.get('output_dir')}")
    else:
        print(f"\n❌ Training failed")


def main():
    parser = argparse.ArgumentParser(description="OpenHoof Tool Router Pipeline")
    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="Show pipeline status")

    # generate
    gen = sub.add_parser("generate", help="Generate synthetic training data")
    gen.add_argument("--count", type=int, default=50, help="Number of examples")

    # export
    sub.add_parser("export", help="Export training data")

    # run
    run = sub.add_parser("run", help="Run full training pipeline")
    run.add_argument("--backend", choices=["auto", "mlx", "cuda"], default="auto")
    run.add_argument("--epochs", type=int, default=3)
    run.add_argument("--lr", type=float, default=2e-4)
    run.add_argument("--batch-size", type=int, default=4)
    run.add_argument("--format", choices=["chat", "instruction"], default="chat")
    run.add_argument("--force", action="store_true")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "generate":
        cmd_generate(args.count)
    elif args.command == "export":
        cmd_export()
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
