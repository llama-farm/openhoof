# OpenHoof Overhaul Plan
**Date:** 2026-02-07
**Goal:** Make agents actually work — persistent memory, reliable tool calling, proper sub-agents, cross-agent sharing

---

## 🔍 Diagnosis: What's Wrong

### 1. **Context Loss (CRITICAL)**
- `_run_agent_turn` reloads workspace every turn but transcripts are only saved AFTER the response
- No shared knowledge base — agents can't see what other agents learned
- Session store is a flat JSON file that gets rewritten on every update (race conditions)
- `get_messages_for_context` returns raw messages but no summary compaction is triggered automatically
- Daily memories are loaded but never auto-created by the system

### 2. **Weak Tool Calling**
- Dual-path tool handling: OpenAI-format tool_calls AND XML-style regex parsing — messy
- XML parsing uses brittle regexes that miss multi-line arguments
- `_parse_tool_calls_from_text` only handles 3 hardcoded patterns
- Qwen3-1.7B is too small for reliable structured tool calling
- No tool call training/fine-tuning pipeline
- Tools aren't listed in the UI — users can't see/manage them

### 3. **Sub-agent Problems**
- `SpawnAgentTool.spawn_callback` is never wired up in `AgentManager.__init__`
- Sub-agents don't receive their purpose, tools list, or parent context
- No report-back mechanism — parent agent gets a "pending_execution" stub
- `SubagentRegistry` exists but is never instantiated by `AgentManager`

### 4. **No Central Data Store**
- Each agent's workspace is isolated — no shared memory directory
- No cross-agent event log that agents can query
- Transcripts stored per-session but no way for Agent B to read Agent A's findings

### 5. **UI Missing Tools Management**
- No tools listing page
- No way to add/remove tools from agents in the UI
- Agent detail page doesn't show assigned tools

---

## 🏗️ The Plan

### Phase 1: Fix the Foundation (Sessions, Memory, Data Store)

**1a. Central shared data directory**
```
~/.openhoof/
├── data/
│   ├── sessions.db          # SQLite instead of JSON
│   ├── transcripts/          # Per-session transcript files
│   ├── shared/               # Cross-agent shared knowledge
│   │   ├── findings.jsonl    # Append-only findings log
│   │   ├── events.jsonl      # All agent events
│   │   └── knowledge/        # Named knowledge files any agent can read
│   └── subagent_runs.db      # SQLite for subagent tracking
├── agents/                   # Agent workspaces
└── config.yaml
```

**1b. Auto-compaction** — When transcript exceeds 30 messages, auto-summarize older ones using the LLM and store the summary. This prevents context overflow.

**1c. Shared knowledge tools** — New tools:
- `shared_write(key, content)` — Write to shared knowledge
- `shared_read(key)` — Read shared knowledge  
- `shared_log(finding)` — Append to findings log
- `shared_search(query)` — Search across all shared data

### Phase 2: Fix Tool Calling

**2a. Upgrade default model to Qwen3-8B-Q4_K_M** — Much better at structured output and tool calling.

**2b. Eliminate XML parsing** — Use proper OpenAI-format tool calling exclusively. LlamaFarm's universal runtime supports this natively via llama.cpp's grammar-based tool calling.

**2c. Multi-model LlamaFarm config** — Set up multiple models:
- `qwen3-8b` — Main reasoning model (Qwen/Qwen3-8B-Q4_K_M.gguf)
- `qwen3-1.7b` — Fast/cheap model for summaries, compaction
- `functiongemma-270m` — Specialist tool-call router (experimental)

**2d. FunctionGemma pipeline (experimental)** — Use the tiny 270M model as a "tool router":
1. User message comes in
2. FunctionGemma-270M classifies: which tool(s) should be called? (fast, <100ms)
3. Main model gets the tool selection as a hint
4. This creates a training loop: as tools are added, we fine-tune the router

### Phase 3: Fix Sub-agents

**3a. Wire up SubagentRegistry** in AgentManager.__init__

**3b. Sub-agent bootstrap protocol:**
- Parent provides: purpose, tools list, relevant context, expected output format
- Sub-agent gets its own session with parent's session_key as `spawned_by`
- Sub-agent writes findings to shared knowledge
- On completion, parent gets notified via event bus with full results

**3c. Sub-agent creation from chat:**
```python
# When spawning, build a proper context:
sub_system_prompt = f"""You are a sub-agent spawned by {parent_agent_id}.

## Your Task
{task_description}

## Tools Available
{tool_descriptions}

## Report Back
When done, use shared_write to save your findings.
End with a clear summary of what you found."""
```

### Phase 4: UI — Tools Management

**4a. New `/tools` page** — List all registered tools with:
- Name, description, parameter schema
- Which agents use them
- Enable/disable toggle per agent

**4b. Agent detail page** — Add tools section:
- Show assigned tools with toggle switches
- Drag to reorder (priority hint)
- "Add Tool" dropdown

**4c. API endpoints:**
- `GET /api/tools` — List all tools
- `GET /api/agents/:id/tools` — List agent's tools
- `PUT /api/agents/:id/tools` — Update agent's tool list

### Phase 5: FunctionGemma Training Pipeline (Experimental)

**5a. Collect training data** — Every tool call (input → selected tool → result) gets logged as training data

**5b. LoRA fine-tuning** — When enough data accumulates (100+ examples), trigger a LoRA fine-tune of FunctionGemma on the tool-calling patterns

**5c. Pipeline integration** — The trained router runs as a pre-filter before the main model, making tool selection near-instant

---

## 🔧 Implementation Order

1. **Download Qwen3-8B model** and update LlamaFarm config
2. **Fix SubagentRegistry wiring** (quick win)
3. **Add shared knowledge directory + tools**
4. **Eliminate XML parsing**, use only OpenAI tool format
5. **Auto-compaction** for transcripts
6. **UI: Tools page + agent tools management**
7. **Download FunctionGemma-270M** and experiment with tool routing
8. **Training data collection** for future fine-tuning

---

## Models to Configure in LlamaFarm

| Model | Size | Purpose | HF Repo |
|-------|------|---------|---------|
| Qwen3-8B-Q4_K_M | ~5GB | Main agent reasoning + tool calling | Qwen/Qwen3-8B-GGUF |
| Qwen3-1.7B-Q4_K_M | ~1.2GB | Fast summaries, compaction | unsloth/Qwen3-1.7B-GGUF |
| FunctionGemma-270M | ~200MB | Tool call routing (experimental) | unsloth/functiongemma-270m-it-GGUF |
| Granite-3.3-2B | ~1.5GB | Alternative reasoning | ibm-granite/granite-3.3-2b-instruct-GGUF |
| Llama-3.2-3B | ~2GB | General purpose backup | bartowski/Llama-3.2-3B-Instruct-GGUF |
| Gemma-3-4B | ~2.5GB | Code + structured output | google/gemma-3-4b-it-qat-q4_0-gguf |
