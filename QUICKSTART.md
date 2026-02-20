# OpenHoof v2.0 — Quickstart

**OpenHoof v2.0** is a standalone agent runtime library. No server, no dependencies on OpenClaw — just import and run.

## Install

```bash
pip install -e .
```

## 30-Second Example

```python
from openhoof import Agent

# 1. Define a tool
def add(a: int, b: int) -> dict:
    return {"result": a + b}

TOOLS = [{
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two numbers",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"}
            },
            "required": ["a", "b"]
        }
    }
}]

# 2. Create agent
agent = Agent(
    soul="SOUL.md",
    memory="MEMORY.md",
    tools=TOOLS,
    executor=lambda name, params: add(**params)
)

# 3. Push events
agent.push_event("tool_call", {
    "tool": "add",
    "params": {"a": 5, "b": 3}
})

# 4. Run (blocks until exit condition)
agent.on_exit("done", lambda: agent.tools_called >= 1)
agent.run()
```

## What Just Happened?

1. **Agent loop started** — heartbeat every 30s, polls events
2. **Tool called** — `add(5, 3)` executed
3. **Training data captured** — saved to `.microclaw/training/*.jsonl`
4. **Exit condition triggered** — agent stopped after 1 tool call
5. **Shutdown gracefully** — stats printed, memory logged

## Next Steps

### Real Agent with LlamaFarm

```python
from openhoof import Agent

agent = Agent(
    soul="SOUL.md",
    memory="MEMORY.md",
    tools=MY_TOOLS,
    executor=my_executor,
    max_turns=10  # Max reasoning loops (default: 10)
)

# Use reasoning model to decide what to do
response = agent.reason("What's the weather in Portland?")
# → Calls weather tool automatically if available
# → Loops until task complete or max_turns reached

# Override max_turns for a specific call
response = agent.reason("Complex task", max_turns=20)

agent.run()
```

### Context Files

**SOUL.md** — Who the agent is:
```markdown
# SOUL.md
- **Name:** WeatherBot
- **Emoji:** 🌤️
- **Mission:** Help users check weather anywhere
```

**MEMORY.md** — What the agent remembers:
```markdown
# MEMORY.md
Created 2026-02-20. Portland user, checks weather daily.
```

### Heartbeat + Exit Conditions

```python
# Custom state
agent.custom["battery"] = 100

# Exit when battery low
agent.on_exit("battery_low", lambda: agent.custom["battery"] < 20)

# Log on heartbeat
agent.on_heartbeat(lambda: print(f"💓 Battery: {agent.custom['battery']}%"))

agent.run()
```

### DDIL (Store-and-Forward)

```python
# Buffer important data when offline
agent.ddil.store("telemetry", {"temp": 72, "alt": 1500})

# Sync to gateway when network available
agent.ddil.sync_to_server("http://gateway.local/api/agent/sync")
```

### Training Data

Every tool call is automatically captured in JSONL format for fine-tuning:

```jsonl
{"tool":"add","params":{"a":5,"b":3},"result":{"result":8},"context":"","timestamp":1771624531}
```

Use with LlamaFarm FunctionGemma training pipeline:
```bash
python -m training.pipeline status      # Check data
python -m training.pipeline generate    # Generate synthetic samples
python -m training.pipeline run         # Train FunctionGemma
```

## Architecture

```
Agent (event loop)
  ├─ Soul (SOUL.md → system prompt)
  ├─ Memory (MEMORY.md + semantic search)
  ├─ Heartbeat (health checks, exit conditions)
  ├─ ToolRegistry (OpenAI-compatible schemas)
  ├─ EventQueue (priority queue)
  ├─ DDILBuffer (store-and-forward)
  ├─ TrainingDataCapture (JSONL logs)
  └─ ModelLoader (LlamaFarm integration)
```

## Run the Test

```bash
python3 test_simple.py
```

You should see:
```
🐴 MicroClaw Agent initialized
   Tools: 2 registered
   Heartbeat: every 2.0s

🟢 Agent TestBot starting event loop...
📩 Event: tool_call (priority=0.9)
🔧 Calling tool: add_numbers({'a': 5, 'b': 3})
   ➤ add_numbers(5, 3) = 8

🛑 Shutdown: max_heartbeats
   Events processed: 3
   Tools called: 3
   Heartbeats: 3
```

## What's Preserved from v1.x

✅ **FunctionGemma training pipeline** (`training/pipeline.py`) — THE GOLD  
✅ **OpenAI-compatible tool schemas** — What Ace's drone uses  
✅ **Training data format** — JSONL for fine-tuning  

## What's New in v2.0

✨ Standalone library (no server)  
✨ Agent runtime with event loop  
✨ Context files (SOUL.md, MEMORY.md)  
✨ Heartbeat + exit conditions  
✨ DDIL (store-and-forward)  
✨ LlamaFarm integration  
✨ Runs anywhere (Python → Kotlin → Android)  

---

**Ready for production?** Test with Ace's drone:
```bash
cd ~/clawd/projects/dji-flip-agent
pip install -e ~/clawd/projects/openhoof
python your_drone_script.py
```
