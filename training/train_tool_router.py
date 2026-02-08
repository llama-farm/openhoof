#!/usr/bin/env python3
"""LoRA fine-tune FunctionGemma for OpenHoof tool routing.

Cross-platform: runs on Mac (via unsloth-mlx) and Linux (via unsloth).
Same script, just swap the import.

Usage:
    # Mac (Apple Silicon)
    python training/train_tool_router.py

    # Linux (CUDA)
    python training/train_tool_router.py --backend cuda

    # Custom settings
    python training/train_tool_router.py --epochs 5 --lr 2e-4 --batch-size 4
"""

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from datetime import datetime

# ============================================================
# Cross-platform import: unsloth-mlx on Mac, unsloth on Linux
# ============================================================
def get_backend():
    """Detect the best backend for this platform."""
    if platform.system() == "Darwin":
        return "mlx"
    else:
        return "cuda"


def import_training_libs(backend: str):
    """Import the right libraries based on backend."""
    if backend == "mlx":
        try:
            from unsloth_mlx import FastLanguageModel
            from unsloth_mlx import SFTTrainer
            print("✅ Using unsloth-mlx (Apple Silicon)")
            return FastLanguageModel, SFTTrainer, "mlx"
        except ImportError:
            print("❌ unsloth-mlx not installed. Run: pip install unsloth-mlx")
            sys.exit(1)
    else:
        try:
            from unsloth import FastLanguageModel
            from trl import SFTTrainer
            print("✅ Using unsloth (CUDA)")
            return FastLanguageModel, SFTTrainer, "cuda"
        except ImportError:
            print("❌ unsloth not installed. Run: pip install unsloth")
            sys.exit(1)


# ============================================================
# Data preparation
# ============================================================
DATA_DIR = Path.home() / ".openhoof" / "data" / "function_pipeline"
OUTPUT_DIR = Path.home() / ".openhoof" / "models" / "tool-router"

# The system prompt FunctionGemma expects
SYSTEM_PROMPT = "You are a model that can do function calling with the following functions"

# Our OpenHoof tools in the format FunctionGemma expects
TOOL_DEFINITIONS = """
memory_write(file: str, content: str, append: bool = false) - Write content to agent memory files
memory_read(file: str) - Read content from workspace files
shared_write(key: str, content: str, tags: list = []) - Write to shared cross-agent knowledge store
shared_read(key: str) - Read from shared cross-agent knowledge store
shared_search(query: str, category: str = null, limit: int = 10) - Search shared knowledge across all agents
shared_log(finding: str, category: str = "general", severity: str = "info") - Log a finding to shared log
spawn_agent(task: str, agent_id: str = null, label: str = null) - Spawn a sub-agent for specialized tasks
notify(title: str, message: str, priority: str = "medium") - Send notification to human operator
exec(command: str, timeout: int = 30) - Execute a shell command
list_tools() - List all available tools
""".strip()


def load_training_data() -> list:
    """Load and format all training data for FunctionGemma fine-tuning."""
    examples = []

    # Load from synthetic training file
    synthetic_path = DATA_DIR / "synthetic_training.jsonl"
    if synthetic_path.exists():
        for line in synthetic_path.open():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                inp = entry.get("input", {})
                out = entry.get("output", {})

                user_msg = inp.get("user_message", "")
                tool_calls = out.get("tool_calls", [])

                if not user_msg:
                    continue

                # Format the expected output
                if tool_calls:
                    output = json.dumps(tool_calls)
                else:
                    output = "[]"

                examples.append({
                    "user_message": user_msg,
                    "tool_calls": output,
                })
            except json.JSONDecodeError:
                continue

    # Also load from live routing decisions (if any)
    live_path = DATA_DIR / "training_data.jsonl"
    if live_path.exists():
        for line in live_path.open():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("metadata", {}).get("success"):
                    inp = entry.get("input", {})
                    out = entry.get("output", {})
                    user_msg = inp.get("user_message", "")
                    tool_calls = out.get("tool_calls", [])

                    if user_msg:
                        examples.append({
                            "user_message": user_msg,
                            "tool_calls": json.dumps(tool_calls) if tool_calls else "[]",
                        })
            except json.JSONDecodeError:
                continue

    print(f"Loaded {len(examples)} training examples")
    return examples


def format_for_training(examples: list) -> list:
    """Format examples into the chat format FunctionGemma expects.

    FunctionGemma uses a specific template:
    <start_of_turn>developer
    {system prompt + tool definitions}
    <end_of_turn>
    <start_of_turn>user
    {user message}
    <end_of_turn>
    <start_of_turn>model
    {tool calls as JSON}
    <end_of_turn>
    """
    formatted = []

    for ex in examples:
        # Build the conversation in chat format
        text = (
            f"<start_of_turn>developer\n"
            f"{SYSTEM_PROMPT}\n\n"
            f"{TOOL_DEFINITIONS}\n"
            f"<end_of_turn>\n"
            f"<start_of_turn>user\n"
            f"{ex['user_message']}\n"
            f"<end_of_turn>\n"
            f"<start_of_turn>model\n"
            f"{ex['tool_calls']}\n"
            f"<end_of_turn>"
        )

        formatted.append({"text": text})

    return formatted


def format_as_instruction(examples: list) -> list:
    """Alternative format using instruction/input/output (Alpaca style).

    This is a fallback if the chat template doesn't work well.
    """
    formatted = []

    for ex in examples:
        formatted.append({
            "instruction": (
                f"{SYSTEM_PROMPT}\n\n"
                f"Available functions:\n{TOOL_DEFINITIONS}\n\n"
                f"Given the user's message, determine which function(s) to call. "
                f"Respond with a JSON array of function calls."
            ),
            "input": ex["user_message"],
            "output": ex["tool_calls"],
        })

    return formatted


# ============================================================
# Training
# ============================================================
def train(
    backend: str = "auto",
    base_model: str = "unsloth/functiongemma-270m-it",
    epochs: int = 3,
    learning_rate: float = 2e-4,
    batch_size: int = 4,
    max_seq_length: int = 2048,
    lora_rank: int = 16,
    lora_alpha: int = 32,
    output_dir: str = None,
    format_style: str = "chat",  # "chat" or "instruction"
):
    """Run the LoRA fine-tuning."""

    if backend == "auto":
        backend = get_backend()

    FastLanguageModel, SFTTrainer, actual_backend = import_training_libs(backend)

    output_dir = output_dir or str(OUTPUT_DIR / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"OpenHoof Tool Router Training")
    print(f"{'='*60}")
    print(f"  Backend:    {actual_backend}")
    print(f"  Base model: {base_model}")
    print(f"  Epochs:     {epochs}")
    print(f"  LR:         {learning_rate}")
    print(f"  Batch size: {batch_size}")
    print(f"  LoRA rank:  {lora_rank}")
    print(f"  Output:     {output_dir}")
    print(f"{'='*60}\n")

    # Load data
    examples = load_training_data()
    if len(examples) < 10:
        print(f"❌ Not enough training data ({len(examples)} examples). Need at least 10.")
        print(f"   Run experiments first to generate data.")
        sys.exit(1)

    # Format data
    if format_style == "chat":
        formatted = format_for_training(examples)
    else:
        formatted = format_as_instruction(examples)

    print(f"Formatted {len(formatted)} training examples ({format_style} style)")

    # Save formatted data for inspection
    formatted_path = Path(output_dir) / "training_data.jsonl"
    with open(formatted_path, "w") as f:
        for item in formatted:
            f.write(json.dumps(item) + "\n")
    print(f"Saved formatted data to {formatted_path}")

    # Load model + LoRA
    print(f"\nLoading base model: {base_model}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base_model,
        max_seq_length=max_seq_length,
        load_in_4bit=True,
    )

    # Add LoRA adapters
    model = FastLanguageModel.get_peft_model(
        model,
        r=lora_rank,
        lora_alpha=lora_alpha,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_dropout=0.05,
        bias="none",
        use_gradient_checkpointing=True,
    )

    # Create dataset
    from datasets import Dataset
    dataset = Dataset.from_list(formatted)

    # Training arguments
    from transformers import TrainingArguments
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=2,
        learning_rate=learning_rate,
        weight_decay=0.01,
        warmup_steps=10,
        logging_steps=5,
        save_steps=50,
        save_total_limit=2,
        fp16=False if actual_backend == "mlx" else True,
        report_to="none",
    )

    # Create trainer
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text" if format_style == "chat" else None,
        args=training_args,
        max_seq_length=max_seq_length,
    )

    # Train!
    print(f"\n🚀 Starting training ({len(formatted)} examples, {epochs} epochs)...")
    stats = trainer.train()
    print(f"\n✅ Training complete!")
    print(f"   Loss: {stats.training_loss:.4f}")

    # Save the LoRA adapter
    lora_path = Path(output_dir) / "lora_adapter"
    print(f"\nSaving LoRA adapter to {lora_path}")
    model.save_pretrained(str(lora_path))
    tokenizer.save_pretrained(str(lora_path))

    # Export to GGUF for llama.cpp / LlamaFarm
    gguf_path = Path(output_dir) / "tool-router.gguf"
    print(f"Exporting merged model to GGUF: {gguf_path}")
    try:
        model.save_pretrained_gguf(
            str(gguf_path.parent / "gguf_export"),
            tokenizer,
            quantization_method="q8_0",  # Keep high quality for tiny model
        )
        print(f"✅ GGUF export complete")
    except Exception as e:
        print(f"⚠️ GGUF export failed (can do manually): {e}")

    # Save training metadata
    meta = {
        "timestamp": datetime.now().isoformat(),
        "backend": actual_backend,
        "base_model": base_model,
        "epochs": epochs,
        "learning_rate": learning_rate,
        "batch_size": batch_size,
        "lora_rank": lora_rank,
        "training_examples": len(formatted),
        "final_loss": stats.training_loss,
        "output_dir": str(output_dir),
        "format_style": format_style,
    }
    meta_path = Path(output_dir) / "training_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    print(f"\n{'='*60}")
    print(f"TRAINING COMPLETE")
    print(f"{'='*60}")
    print(f"  LoRA adapter: {lora_path}")
    print(f"  GGUF model:   {gguf_path.parent / 'gguf_export'}")
    print(f"  Metadata:     {meta_path}")
    print(f"  Final loss:   {stats.training_loss:.4f}")
    print(f"\nTo use in LlamaFarm, update the model path to the GGUF file.")
    print(f"To continue training with more data, use --resume {lora_path}")

    return meta


# ============================================================
# Automated pipeline
# ============================================================
def check_and_train(min_examples: int = 100, force: bool = False):
    """Check if we have enough data and trigger training if so.

    This is meant to be called periodically (e.g., from a cron job
    or heartbeat) to automatically retrain when enough new data
    accumulates.
    """
    # Count available training data
    total = 0
    for path_name in ["synthetic_training.jsonl", "training_data.jsonl"]:
        path = DATA_DIR / path_name
        if path.exists():
            total += sum(1 for line in path.open() if line.strip())

    print(f"Available training data: {total} examples (need {min_examples})")

    if total < min_examples and not force:
        print(f"Not enough data yet. Collect {min_examples - total} more examples.")
        return None

    # Check if we've already trained on this data
    last_meta = OUTPUT_DIR / "latest" / "training_meta.json"
    if last_meta.exists() and not force:
        meta = json.loads(last_meta.read_text())
        if meta.get("training_examples", 0) >= total:
            print(f"Already trained on {meta['training_examples']} examples. No new data.")
            return None

    print(f"🚀 Triggering training with {total} examples...")
    return train()


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Train OpenHoof tool router")
    parser.add_argument("--backend", choices=["auto", "mlx", "cuda"], default="auto",
                        help="Training backend (auto-detects)")
    parser.add_argument("--model", default="unsloth/functiongemma-270m-it",
                        help="Base model to fine-tune")
    parser.add_argument("--epochs", type=int, default=3, help="Training epochs")
    parser.add_argument("--lr", type=float, default=2e-4, help="Learning rate")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size")
    parser.add_argument("--lora-rank", type=int, default=16, help="LoRA rank")
    parser.add_argument("--format", choices=["chat", "instruction"], default="chat",
                        help="Training data format")
    parser.add_argument("--output", default=None, help="Output directory")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-mode: only train if enough new data")
    parser.add_argument("--min-examples", type=int, default=100,
                        help="Minimum examples for auto-training")
    parser.add_argument("--force", action="store_true", help="Force training")
    parser.add_argument("--stats", action="store_true", help="Show data stats and exit")

    args = parser.parse_args()

    if args.stats:
        total = 0
        for path_name in ["synthetic_training.jsonl", "training_data.jsonl"]:
            path = DATA_DIR / path_name
            if path.exists():
                count = sum(1 for line in path.open() if line.strip())
                print(f"  {path_name}: {count} examples")
                total += count
            else:
                print(f"  {path_name}: (not found)")
        print(f"  Total: {total} examples")
        print(f"  Ready for training: {'✅' if total >= args.min_examples else '❌'} (need {args.min_examples})")
        return

    if args.auto:
        check_and_train(min_examples=args.min_examples, force=args.force)
    else:
        train(
            backend=args.backend,
            base_model=args.model,
            epochs=args.epochs,
            learning_rate=args.lr,
            batch_size=args.batch_size,
            lora_rank=args.lora_rank,
            output_dir=args.output,
            format_style=args.format,
        )


if __name__ == "__main__":
    main()
