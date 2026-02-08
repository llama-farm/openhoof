# 🦙 OpenHoof Tool Router Training

LoRA fine-tune [FunctionGemma-270M](https://huggingface.co/google/functiongemma-270m-it) to route user messages to the right tool. Runs on **Mac (Apple Silicon)** and **Linux (CUDA)** with the same script.

## Results

| Model | Accuracy | Avg Latency | Notes |
|-------|----------|-------------|-------|
| FunctionGemma-270M (base) | 15.4% | 203ms | Outputs garbage — needs fine-tuning |
| Qwen3-1.7B (as router) | 38.5% | 515ms | Decent but too slow |
| **FunctionGemma-270M (fine-tuned)** | **100%** | **271ms** | 🔥 After 3 min LoRA training |

## Quick Start

```bash
# Mac (Apple Silicon)
pip install -r training/requirements-mac.txt
python training/train_tool_router.py

# Linux (CUDA)
pip install -r training/requirements-linux.txt
python training/train_tool_router.py --backend cuda
```

The script auto-detects your platform. Same code, same API — just different backend.

## How It Works

```
┌─────────────────────────────────────────────┐
│  User: "Save a note about the meeting"      │
│                    ↓                        │
│  FunctionGemma-270M (550MB RAM, ~270ms)     │
│                    ↓                        │
│  Output: [{"name": "memory_write", ...}]    │
│                    ↓                        │
│  Tool executes → Result fed to bigger model │
└─────────────────────────────────────────────┘
```

A 270M parameter model routes tool calls in <300ms. On phones, that's <100ms. The bigger model (Qwen3-8B) only runs when you need reasoning about the results.

## Pipeline Commands

```bash
# Check status (data counts, trained models, experiment results)
python training/pipeline.py status

# Generate more synthetic training data (uses Qwen as teacher)
python training/pipeline.py generate --count 50

# Export data for inspection
python training/pipeline.py export

# Full pipeline (generate if needed → train → export)
python training/pipeline.py run

# Train with custom settings
python training/train_tool_router.py \
  --epochs 5 \
  --lr 2e-4 \
  --batch-size 4 \
  --lora-rank 16 \
  --format chat

# Auto-train only if enough new data exists
python training/train_tool_router.py --auto --min-examples 200
```

## Cross-Platform Architecture

```python
# Mac (Apple Silicon)                    # Linux (CUDA)
from unsloth_mlx import FastLanguageModel   from unsloth import FastLanguageModel
from unsloth_mlx import SFTTrainer          from trl import SFTTrainer

# Everything else is identical!
model, tokenizer = FastLanguageModel.from_pretrained(...)
model = FastLanguageModel.get_peft_model(model, r=16, ...)
trainer = SFTTrainer(model=model, ...)
trainer.train()
```

### Inference

| Platform | Method | File |
|----------|--------|------|
| Mac | MLX-native (merged model) | `openhoof/inference/mlx_router.py` |
| Linux | llama.cpp via GGUF | Export with `model.save_pretrained_gguf()` |
| LlamaFarm | Universal runtime + GGUF | Point LlamaFarm at exported GGUF |

## Training Data

Training data lives at `~/.openhoof/data/function_pipeline/`:

| File | Description |
|------|-------------|
| `synthetic_training.jsonl` | Curated + teacher-generated examples |
| `training_data.jsonl` | Live routing decisions (collected during use) |
| `outcomes.jsonl` | Feedback on routing accuracy |

### Data Format

```json
{
  "input": {"user_message": "Save a note about the meeting", "tools": ["memory_write", ...]},
  "output": {"tool_calls": [{"name": "memory_write", "arguments": {}}]},
  "metadata": {"source": "manual_curated", "tool": "memory_write"}
}
```

## Training Details

- **Base model**: `unsloth/functiongemma-270m-it` (Google's FunctionGemma)
- **Method**: LoRA (rank 16, alpha 32)
- **Target modules**: q/k/v/o_proj + gate/up/down_proj (all 18 layers)
- **Data**: 226 examples (103 curated + 123 synthetic)
- **Training**: 339 iterations, 3 epochs, ~3 minutes on M-series Mac
- **Loss curve**: 4.272 → 0.024 (val loss)
- **Peak memory**: 2.1GB

## Continuous Improvement

The system collects training data from real usage:

1. Every tool routing decision is logged to `training_data.jsonl`
2. Outcome feedback is tracked in `outcomes.jsonl`
3. Periodically, run `python training/pipeline.py run` to retrain
4. Or use `--auto` mode to only retrain when enough new data exists

The goal: the model gets better the more you use it. 🦙
