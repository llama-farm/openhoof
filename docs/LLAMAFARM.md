# LlamaFarm Integration

<p align="center">
  <img src="openhoof-logo.png" alt="OpenHoof Logo" width="120">
</p>

OpenHoof is designed to work seamlessly with [LlamaFarm](https://github.com/llama-farm/llamafarm) for local LLM inference.

## What is LlamaFarm?

LlamaFarm is a local AI inference platform that:
- Runs LLMs entirely on your machine
- Supports multiple models (Qwen, Llama, Mistral, etc.)
- Provides OpenAI-compatible API
- Works completely offline

## Setup

### 1. Install LlamaFarm

```bash
# Clone and setup LlamaFarm
git clone https://github.com/llama-farm/llamafarm.git
cd llamafarm
pip install -e .

# Start LlamaFarm (default: port 14345)
llamafarm start
```

### 2. Verify LlamaFarm is Running

```bash
curl http://localhost:14345/health
# {"status": "healthy", ...}
```

### 3. Create a Project for OpenHoof

LlamaFarm uses "projects" to organize configurations:

```bash
# Create config file
cat > openhoof-project.yaml << 'EOF'
version: v1
name: openhoof
namespace: default

runtime:
  models:
    - name: default
      provider: universal
      model: unsloth/Qwen3-4B-GGUF:Q4_K_M
      default: true
      prompt_format: unstructured
      prompts: [default]

prompts:
  - name: default
    content: |
      {{system}}
      {{user}}
EOF

# Register the project
curl -X POST "http://localhost:14345/v1/projects/default" \
  -H "Content-Type: application/x-yaml" \
  --data-binary @openhoof-project.yaml
```

### 4. Configure OpenHoof

Edit `~/.openhoof/config.yaml`:

```yaml
inference:
  base_url: http://localhost:14345
  namespace: default
  project: openhoof
  api_key: null  # Not needed for local LlamaFarm
  default_model: null  # Use project's default model
```

### 5. Test the Connection

```bash
# Start OpenHoof
openhoof start

# Check health (should show inference: true)
curl http://localhost:18765/api/health
# {"status":"healthy","components":{"api":true,"inference":true}}
```

## How OpenHoof Uses LlamaFarm

OpenHoof sends chat completion requests to LlamaFarm:

```
OpenHoof                           LlamaFarm
   │                                   │
   │  POST /v1/projects/default/       │
   │       openhoof/chat/completions   │
   ├──────────────────────────────────▶│
   │                                   │
   │  {                                │
   │    "messages": [                  │
   │      {"role": "system", ...},     │
   │      {"role": "user", ...}        │
   │    ]                              │
   │  }                                │
   │                                   │
   │◀──────────────────────────────────┤
   │  {"choices": [{"message": ...}]}  │
   │                                   │
```

## Model Selection

### Project Default
If you don't specify a model, OpenHoof uses the project's default:

```yaml
# In LlamaFarm project config
runtime:
  models:
    - name: default
      model: unsloth/Qwen3-4B-GGUF:Q4_K_M
      default: true  # ← This one
```

### Per-Agent Override
Set a specific model for an agent in `~/.openhoof/agents/{id}/config.yaml`:

```yaml
model: unsloth/Qwen3-8B-GGUF:Q4_K_M
```

### Per-Request Override
Specify model in API calls:

```bash
curl -X POST http://localhost:18765/api/agents/my-agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hello",
    "model": "unsloth/Qwen3-8B-GGUF:Q4_K_M"
  }'
```

## Recommended Models

| Model | Size | Good For |
|-------|------|----------|
| Qwen3-1.7B | ~1GB | Quick responses, simple tasks |
| Qwen3-4B | ~3GB | General purpose, balanced |
| Qwen3-8B | ~5GB | Complex reasoning |
| Llama-3.2-3B | ~2GB | Instruction following |
| Mistral-7B | ~4GB | Creative writing |

## Offline Operation

One of OpenHoof's key features is **offline capability**:

1. LlamaFarm runs entirely locally
2. No internet required after model download
3. Data never leaves your machine

This is critical for:
- Air-gapped environments
- Sensitive data handling
- Disconnected operations (SATCOM denied)

## Troubleshooting

### "Inference unhealthy"

LlamaFarm isn't reachable:

```bash
# Check if LlamaFarm is running
curl http://localhost:14345/health

# Check if project exists
curl http://localhost:14345/v1/projects/default/openhoof

# Check OpenHoof config
cat ~/.openhoof/config.yaml | grep -A5 inference
```

### "Model not found"

The specified model isn't available:

```bash
# List available models in LlamaFarm
curl http://localhost:14345/v1/models

# Check project config
curl http://localhost:14345/v1/projects/default/openhoof
```

### Slow Responses

Model might be too large for your hardware:

```bash
# Try a smaller model
# In LlamaFarm project config:
model: unsloth/Qwen3-1.7B-GGUF:Q4_K_M

# Or use quantized version
model: unsloth/Qwen3-4B-GGUF:Q2_K  # Smaller but less accurate
```

### Memory Issues

```bash
# Check available memory
free -h  # Linux
vm_stat  # macOS

# Use a smaller model or increase swap
```

## Using Other Backends

OpenHoof's inference adapter is pluggable. To use a different backend:

### OpenAI API

```yaml
# ~/.openhoof/config.yaml
inference:
  backend: openai
  api_key: sk-...
  base_url: https://api.openai.com/v1
  default_model: gpt-4
```

### Anthropic (Claude)

```yaml
inference:
  backend: anthropic
  api_key: sk-ant-...
  default_model: claude-3-sonnet
```

### Ollama

```yaml
inference:
  backend: ollama
  base_url: http://localhost:11434
  default_model: llama3
```

### Custom Backend

Implement `InferenceAdapter`:

```python
from openhoof.inference import InferenceAdapter

class MyAdapter(InferenceAdapter):
    async def chat(self, messages, **kwargs):
        # Your implementation
        pass
```

## Best Practices

1. **Start small** — Use 1.7B-4B models initially
2. **Match model to task** — Simple tasks don't need big models
3. **Test offline** — Verify it works without internet
4. **Monitor memory** — Watch for OOM issues
5. **Warm up models** — First request is slow (loading)
