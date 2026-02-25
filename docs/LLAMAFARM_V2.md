# LlamaFarm Integration

OpenHoof v2.0 integrates with LlamaFarm for local model inference.

---

## LlamaFarm Architecture

**LlamaFarm** (https://github.com/llama-farm/llamafarm) is a complete AI platform with three services:

| Service | Port | Purpose |
|---------|------|---------|
| **Server** | 14345 | FastAPI API, Designer UI, project management |
| **RAG Worker** | - | Background document processing (Celery) |
| **Universal Runtime** | 11540 | Direct model inference (HuggingFace, embeddings, OCR, etc.) |

---

## OpenHoof Uses Universal Runtime

OpenHoof agents call the **Universal Runtime** directly at port **11540** for model inference.

### Endpoint
```
http://localhost:11540/v1/chat/completions
```

### Why Universal Runtime?
- Direct model access (no project scaffolding needed)
- OpenAI-compatible API
- Tools + prompts passed through in request
- Supports any HuggingFace model
- Fast (<100ms for small models)

---

## Configuration

OpenHoof's `llamafarm.yaml` is **NOT** a LlamaFarm project config. It's a **model definition file** for the OpenHoof agent runtime.

```yaml
# llamafarm.yaml (OpenHoof agent config)
endpoint: "http://localhost:11540/v1"  # Universal Runtime

models:
  router:
    model: "functiongemma:270m"  # Fast tool routing
    temperature: 0.1
  
  reasoning:
    model: "qwen2.5:8b"  # Agent reasoning
    temperature: 0.7
  
  mobile:
    model: "llama3.2:1b"  # Future Android
  
  fallback:
    model: "gpt-4o-mini"  # Cloud fallback
```

---

## Usage in OpenHoof

### Agent with LlamaFarm
```python
from openhoof import Agent

agent = Agent(
    soul="SOUL.md",
    memory="MEMORY.md",
    tools=my_tools,
    llamafarm_config="llamafarm.yaml"  # Uses Universal Runtime
)

# Calls http://localhost:11540/v1/chat/completions
response = agent.reason("What should I do next?")
```

### Direct Model Loader
```python
from openhoof import ModelLoader

loader = ModelLoader("llamafarm.yaml")

# Fast routing (FunctionGemma 270M)
response = loader.route_tool(prompt, tools, system_prompt)

# Full reasoning (Qwen 8B)
response = loader.reason(prompt, tools, system_prompt)
```

---

## API Format

OpenHoof sends OpenAI-compatible requests to Universal Runtime:

### Request
```json
POST http://localhost:11540/v1/chat/completions

{
  "model": "qwen2.5:8b",
  "messages": [
    {"role": "system", "content": "You are a helpful agent..."},
    {"role": "user", "content": "What should I do?"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "drone_takeoff",
        "description": "Take off and hover",
        "parameters": {...}
      }
    }
  ],
  "tool_choice": "auto",
  "temperature": 0.7,
  "max_tokens": 2048
}
```

### Response
```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "I recommend taking off to survey the area.",
        "tool_calls": [
          {
            "id": "call_123",
            "type": "function",
            "function": {
              "name": "drone_takeoff",
              "arguments": "{\"alt_m\": 15.0}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "usage": {
    "prompt_tokens": 150,
    "completion_tokens": 50,
    "total_tokens": 200
  }
}
```

---

## Starting LlamaFarm

### Option 1: CLI
```bash
# Install LlamaFarm CLI
curl -fsSL https://raw.githubusercontent.com/llama-farm/llamafarm/main/install.sh | bash

# Start services
lf start  # Starts all three services
```

### Option 2: Desktop App
Download from: https://github.com/llama-farm/llamafarm/releases/latest

### Option 3: From Source
```bash
cd ~/clawd/projects/llamafarm-core

# Start Universal Runtime only (what OpenHoof needs)
nx start universal-runtime  # Port 11540
```

---

## Model Management

### Universal Runtime Auto-Downloads Models

When you request a model (e.g., `qwen2.5:8b`), Universal Runtime:
1. Checks if it's cached locally
2. If not, downloads from HuggingFace
3. Loads into memory
4. Serves via OpenAI-compatible API

### Supported Model Formats
- HuggingFace models (e.g., `Qwen/Qwen2.5-1.5B-Instruct`)
- Ollama references (e.g., `qwen3:8b`)
- GGUF models (e.g., `unsloth/Qwen3-1.7B-GGUF:Q4_K_M`)

---

## FunctionGemma Training

OpenHoof's **FunctionGemma training pipeline** (`training/pipeline.py`) generates fine-tuning data and trains models for fast tool routing.

### Workflow
1. **Collect data** — Every tool call logged by `TrainingDataCapture`
2. **Generate synthetic** — `pipeline.py generate --count 100`
3. **Train** — `pipeline.py run` (LoRA fine-tune FunctionGemma)
4. **Export GGUF** — For deployment
5. **Load in LlamaFarm** — Use trained model as `router` model

### Why FunctionGemma?
- 270M parameters = fast (<100ms)
- Specialized for function calling
- Can be fine-tuned on your specific tools
- Works offline (no API calls)

---

## Differences: OpenHoof vs LlamaFarm Config

| Aspect | OpenHoof `llamafarm.yaml` | LlamaFarm `llamafarm.yaml` |
|--------|---------------------------|----------------------------|
| **Purpose** | Agent model definitions | Full project config |
| **Format** | Simple YAML (models only) | Complex YAML (RAG, prompts, datasets, etc.) |
| **Scope** | Client-side (what to call) | Server-side (how to run) |
| **Usage** | Loaded by `ModelLoader` | Loaded by LlamaFarm server |
| **Location** | Agent workspace | LlamaFarm project directory |

---

## Summary

✅ **OpenHoof calls LlamaFarm Universal Runtime** (port 11540)  
✅ **Tools + prompts passed through** in API request  
✅ **No project scaffolding needed** — just call the API  
✅ **FunctionGemma training** for fast tool routing  
✅ **OpenAI-compatible** format  

**To use:**
1. Start LlamaFarm: `lf start` or `nx start universal-runtime`
2. Create agent: `Agent(llamafarm_config="llamafarm.yaml")`
3. Call reasoning: `agent.reason("What should I do?")`

LlamaFarm handles model loading, inference, and caching. OpenHoof handles agent runtime, tools, memory, and DDIL.

---

**Status:** ✅ **Fully integrated and tested** (port 11540, Universal Runtime)
