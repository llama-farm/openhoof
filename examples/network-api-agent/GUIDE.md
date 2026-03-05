# From API Reference to FunctionGemma — Step by Step

A complete walkthrough of turning `API_REFERENCE.md` (Cradlepoint R980 + Netgear GS105Ev2)
into a fine-tuned FunctionGemma model and a working OpenHoof app.

**Only model used: FunctionGemma 270M.**
No reasoning model. No second LLM. FunctionGemma receives a user intent and returns
a tool call. The app executes it.

---

## How the final system works

```
User: "show me all LAN clients"
        ↓
FunctionGemma 270M  →  router_get_lan_clients()
        ↓
HTTP GET /api/status/lan/clients/
        ↓
[{mac, ip, hostname, interface}, ...]
```

FunctionGemma is a **router**, not a reasoner. It does one thing: map an intent to a
tool call. Session auth, rate-limiting, and multi-step flows are handled by the app
layer — the model never sees them.

---

## Step 1 — Read the API reference and identify operations

Before writing any code, read the entire API reference and answer:

**What are the distinct user-facing operations?**

From `API_REFERENCE.md`:

| Operation | User would say | Maps to |
|---|---|---|
| Get LAN clients | "show connected devices" | GET /api/status/lan/clients/ |
| Get WAN status | "check internet connection" | GET /api/status/wan/ |
| Get system status | "router health" | GET /api/status/system/ |
| Create a VLAN | "add VLAN 100" | POST /api/config/vlan/ |
| Update LAN | "change DHCP range" | PUT /api/config/lan/{idx}/ |
| Reboot router | "reboot the router" | PUT /api/control/system/reboot |
| Get switch port status | "switch port states" | GET /status.cgi |
| Create switch VLAN | "add VLAN 20 to switch" | POST /8021qCf.cgi |
| Set switch PVID | "set port 3 to VLAN 20" | POST /portPVID.cgi |
| Get WiFi config | "show WiFi networks" | GET /api/config/wlan/ |
| Enable/disable WiFi | "turn off guest WiFi" | PUT /api/config/wlan/radio/{N}/bss/{M}/ |

**Key insight for tool design:**
- ONE intent → ONE tool call. The model should never need to know about auth, cookies,
  or rate limits — that's the app's job.
- Don't make tools too granular (one per HTTP verb per path) — that's too many.
- Don't make tools too broad ("do anything on the router") — model can't learn it.
- Sweet spot: one tool per user-facing operation (~20–35 tools total).

---

## Step 2 — Design tool schemas

Rules from lessons learned:
1. Keep descriptions SHORT and keyword-rich — FunctionGemma 270M reads ~8 tokens
2. Use clear, consistent parameter names
3. Required params only — optional params confuse tiny models
4. Add `description` to every property (required by FunctionGemma Jinja2 template)

See `tools.py` in this directory for the complete tool definitions.

**Example — good tool schema:**
```python
create_tool_schema(
    name="router_get_lan_clients",
    summary="Get list of all devices connected to the router LAN",
    when_to_use="User asks about connected devices, clients, or who is on the network",
    parameters={"type": "object", "properties": {}, "required": []},
)
```

**Example — bad tool schema (too broad, model can't learn):**
```python
# DON'T DO THIS
create_tool_schema(
    name="router_api_call",
    summary="Make any API call to the router",
    parameters={"type": "object", "properties": {
        "method": {"type": "string"},
        "path": {"type": "string"},
        "data": {"type": "string"},
    }, "required": ["method", "path"]},
)
```

---

## Step 3 — Generate training data

Use `SyntheticDataGenerator` with GPT-4o-mini or Qwen3-8B as teacher.

**Important format choice:**

For FunctionGemma 270M, always use `output_format="text"`:
```
human: "show me connected devices"
gpt:   "router_get_lan_clients()"
```

NOT the JSON format:
```
# This is harder for 270M to learn reliably
human: "show me connected devices"
gpt:   '<tool_call>{"name": "router_get_lan_clients", "arguments": {}}</tool_call>'
```

**Run generation:**
```bash
# OpenAI teacher (recommended for quality)
python -m openhoof.synth \
    --tools examples/network-api-agent/tools.json \
    --model gpt-4o-mini \
    --endpoint https://api.openai.com/v1 \
    --type router \
    --format text \
    --count 500 \
    --synonyms 8 \
    --output .microclaw/training

# Or local LlamaFarm teacher
python -m openhoof.synth \
    --tools examples/network-api-agent/tools.json \
    --model unsloth/Qwen3-8B-GGUF \
    --endpoint http://localhost:11540/v1 \
    --type router \
    --format text \
    --count 500 \
    --synonyms 8 \
    --output .microclaw/training
```

**What the generator does:**
- Generates 8 rephrasings per base intent (synonym explosion — empirically best strategy)
- Runs conflict detection (same input → different output = accuracy killer)
- Warns if any tool has < 8 examples
- Auto-splits 10% to eval JSONL

**Validate the output:**
```bash
python -m openhoof.synth \
    --tools examples/network-api-agent/tools.json \
    --validate-only .microclaw/training/router_synthetic_<date>.jsonl
```

Check for:
- Acceptance rate > 90%
- Zero conflicts
- Every tool has coverage

---

## Step 4 — Review and augment the dataset

**This step cannot be skipped.** Generated data is a starting point — not production-ready.

### 4a. Manually review 20–30 examples

Open `.microclaw/training/router_synthetic_<date>.jsonl` and check:
- Does the intent sound natural?
- Is the tool call correct for the intent?
- Are parameter values realistic?
- Any domain-specific phrasings the generator missed?

### 4b. Add domain-specific examples by hand

The API reference has critical domain knowledge the generator can't infer:

```jsonl
{"conversations": [{"from": "human", "value": "check for pci-dss lockout"}, {"from": "gpt", "value": "router_get_system_config()"}]}
{"conversations": [{"from": "human", "value": "how many failed logins"}, {"from": "gpt", "value": "router_get_system_config()"}]}
{"conversations": [{"from": "human", "value": "vlan 100 on port 3 untagged"}, {"from": "gpt", "value": "switch_set_vlan_membership(vid=100, port_config=\"33133\")"}]}
{"conversations": [{"from": "human", "value": "trunk port membership"}, {"from": "gpt", "value": "switch_set_vlan_membership(vid=1, port_config=\"22222\")"}]}
```

Add at minimum:
- API-specific jargon ("PVID", "BSS", "ALG", "hiddenMem", "FIPS lockout")
- Error recovery intents ("re-auth", "session expired", "reconnect")
- Abbreviations users actually type ("wan ip", "dhcp range", "ssid", "wpa key")

### 4c. Check distribution

Run a quick distribution check:
```python
from collections import Counter
import json

counts = Counter()
with open(".microclaw/training/router_synthetic_<date>.jsonl") as f:
    for line in f:
        ex = json.loads(line)
        gpt = ex["conversations"][1]["value"]
        tool = gpt.split("(")[0]
        counts[tool] += 1

for tool, n in counts.most_common():
    print(f"  {n:4d}  {tool}")
```

**Do NOT artificially balance.** If `router_get_status` has 80 examples and
`switch_create_vlan` has 12, that's fine — it reflects natural usage frequency.
Artificial balancing hurts accuracy (empirically: -12 points).

---

## Step 5 — Fine-tune FunctionGemma

```python
from openhoof import FinetuneManager

ft = FinetuneManager(endpoint="http://localhost:11540/v1")

# Submit training job
job_id = ft.finetune_router(
    training_dir=".microclaw/training",
    model="unsloth/functiongemma-270m-it",  # HuggingFace format (NOT .gguf)
    epochs=10,
    lora_rank=8,
    wait=True,          # block until done (~5 min on M-series Mac)
    auto_promote=True,  # creates ft:{job_id} alias automatically
)
print(f"Trained model: ft:{job_id}")
```

**Training parameters that matter (from lessons learned):**

| Parameter | Value | Why |
|---|---|---|
| `epochs` | 10 | Converges at 10; more epochs rarely help |
| `lora_rank` | 8 | Right for 270M; rank 16 adds memory without benefit |
| `learning_rate` | 2e-4 | Default works; don't tune until data is right |
| `batch_size` | 4 | Good for M-series Mac RAM |
| `max_seq_length` | 512 | Router examples are short; 512 is plenty |
| `train_on_responses_only` | True | Only train on gpt turns, not human turns |

**What NOT to tune:** Hyperparameters don't matter much for 270M models. Data quality
dominates. If accuracy is low, fix the data — not the parameters.

---

## Step 6 — Evaluate accuracy

```python
# Load holdout eval set (auto-generated by SyntheticDataGenerator)
import json

holdout = []
with open(".microclaw/training/router_synthetic_eval_<date>.jsonl") as f:
    for line in f:
        ex = json.loads(line)
        convs = ex["conversations"]
        human = convs[0]["value"]
        expected = convs[1]["value"]
        holdout.append({
            "messages": [{"role": "user", "content": human}],
            "expected": expected,
        })

# Run eval via LlamaFarm
result = ft.eval(job_id, holdout)
print(f"Accuracy: {result['accuracy']:.1%}  ({result['correct']}/{result['total']})")

# Check failures
for ex in result["per_example"]:
    if not ex["correct"]:
        print(f"  FAIL: '{ex['input']}' → expected '{ex['expected']}', got '{ex['actual']}'")
```

**Interpreting results:**

| Accuracy | Action |
|---|---|
| > 90% | Ship it |
| 80–90% | Add more examples for failing tools; retrain |
| 70–80% | Look for conflicts or distribution issues; likely data problem |
| < 70% | Data quality issue — check for contradictions and ambiguous intents |

**Key lesson: train loss ≠ accuracy.** A model with loss 0.144 can score 50%. A model
with loss 0.184 can score 87%. Always eval on held-out data.

---

## Step 7 — Deploy to the app

After promotion (`auto_promote=True` in step 5), use the alias:

```yaml
# llamafarm.yaml
models:
  router:
    model: "ft:YOUR_JOB_ID"   # or "local/functiongemma-ft"
```

The `ft:` prefix is resolved by LlamaFarm Universal Runtime (PR #785).
No GGUF path needed. The model auto-loads on first inference call.

---

## Step 8 — Run the app

```bash
cd examples/network-api-agent
pip install -r requirements.txt

# Configure device credentials
cp .env.example .env
# Edit .env with router IP, username, password, switch IP, switch password

python main.py
```

The app starts a REPL loop:
```
Network Agent (FunctionGemma router)
Type a command or 'quit' to exit.
> show connected devices
→ router_get_lan_clients()
[{"mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.0.10", "hostname": "macbook", ...}]

> add vlan 100 to the switch
→ switch_create_vlan(vid=100)
{"success": true}
```

---

## Iterating after deployment

**When accuracy drops on new intents:**
1. Capture the failing intents
2. Add them manually to the training JSONL
3. Retrain with the full dataset (original + new)
4. Always keep original examples — they encode patterns generated data doesn't

**When adding new API operations:**
1. Add the tool to `tools.py`
2. Run the generator for ONLY the new tool (use `--cross-tool-ratio 0` to focus)
3. Append to the existing training file
4. Retrain

**Never replace the original dataset.** Append to it.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Model outputs garbage text | FunctionGemma Jinja2 template not applied | Ensure LlamaFarm PR #785 is merged; use `ft:job_id` routing |
| Same intent → different tools each run | Contradiction in training data | Run `--validate-only` and fix conflicts |
| Low accuracy on one tool | Insufficient examples | Add 5–8 more synonym examples for that tool |
| Good training loss, bad accuracy | Data leak between train/eval | Check eval file is truly held out |
| Auth fails on API calls | Session expired mid-session | The app auto-relogins; check credentials in `.env` |
| Switch API returns 302 | Stale session on switch | Switch allows 1 concurrent session; app re-auths automatically |
