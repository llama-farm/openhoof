#!/usr/bin/env python3
"""Direct experiment against the universal runtime (bypass LlamaFarm server).

Tests FunctionGemma tool routing with our OpenHoof tools.
"""

import asyncio
import json
import time
import aiohttp

UNIVERSAL_URL = "http://localhost:11540/v1/chat/completions"

# Our OpenHoof tools
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

# OpenAI-format tools for the big model
OPENAI_TOOLS = [
    {"type": "function", "function": {"name": "memory_write", "description": "Write content to agent memory files", "parameters": {"type": "object", "properties": {"file": {"type": "string"}, "content": {"type": "string"}, "append": {"type": "boolean"}}, "required": ["file", "content"]}}},
    {"type": "function", "function": {"name": "memory_read", "description": "Read content from workspace files", "parameters": {"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"]}}},
    {"type": "function", "function": {"name": "shared_write", "description": "Write to shared cross-agent knowledge store", "parameters": {"type": "object", "properties": {"key": {"type": "string"}, "content": {"type": "string"}}, "required": ["key", "content"]}}},
    {"type": "function", "function": {"name": "shared_read", "description": "Read from shared cross-agent knowledge store", "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}}},
    {"type": "function", "function": {"name": "shared_search", "description": "Search shared knowledge across all agents", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "shared_log", "description": "Log a finding to the shared log", "parameters": {"type": "object", "properties": {"finding": {"type": "string"}, "category": {"type": "string"}, "severity": {"type": "string"}}, "required": ["finding"]}}},
    {"type": "function", "function": {"name": "spawn_agent", "description": "Spawn a sub-agent for specialized tasks", "parameters": {"type": "object", "properties": {"task": {"type": "string"}, "agent_id": {"type": "string"}}, "required": ["task"]}}},
    {"type": "function", "function": {"name": "notify", "description": "Send notification to human operator", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "message": {"type": "string"}, "priority": {"type": "string"}}, "required": ["title", "message"]}}},
    {"type": "function", "function": {"name": "exec", "description": "Execute a shell command", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "list_tools", "description": "List all available tools", "parameters": {"type": "object", "properties": {}}}},
]

TEST_CASES = [
    ("Remember that the fuel burn rate was 15% above normal today", ["memory_write"], "Simple memory write"),
    ("What's in my daily notes from yesterday?", ["memory_read"], "Simple memory read"),
    ("Share the fuel analysis results with other agents", ["shared_write"], "Shared write"),
    ("What have other agents found about weather patterns?", ["shared_search"], "Shared search"),
    ("Log that we detected a fuel anomaly", ["shared_log"], "Log a finding"),
    ("I need a fuel specialist to analyze this data", ["spawn_agent"], "Spawn sub-agent"),
    ("Alert the operator about the critical fuel shortage", ["notify"], "Send notification"),
    ("Check the disk space on the server", ["exec"], "Execute command"),
    ("What tools do I have available?", ["list_tools"], "List tools"),
    ("Hello, how are you today?", [], "No tool - greeting"),
    ("What's the capital of France?", [], "No tool - general knowledge"),
    ("Save this analysis AND notify the operator it's ready", ["memory_write", "notify"], "Multi-tool"),
    ("Run the diagnostic and log the results", ["exec", "shared_log"], "Multi-tool chain"),
]

# Synthetic data generation prompts for each tool
SYNTHETIC_PROMPTS_PER_TOOL = {
    "memory_write": [
        "Save a note that the meeting is tomorrow at 2pm",
        "Write down that system latency improved by 30%",
        "Update my memory with the new deployment schedule",
        "Record that the API was down for 5 minutes",
        "Log today's weather observation to my notes",
        "Jot down that the team agreed to switch frameworks",
        "Note: server migration completed successfully",
        "Remember to follow up with the vendor next week",
        "Add to my daily log: completed the security audit",
        "Document the new error handling procedure",
    ],
    "memory_read": [
        "Show me what happened yesterday",
        "Read my SOUL.md file",
        "What are my current notes?",
        "Check my memory from last Tuesday",
        "Open my TOOLS.md",
        "What did I write earlier today?",
        "Look up my previous analysis notes",
        "Read the project status from my workspace",
    ],
    "shared_write": [
        "Publish the weather analysis for all agents",
        "Share the fuel efficiency data with the team",
        "Store the network topology map for everyone",
        "Post the updated maintenance schedule",
        "Make the security findings available to all agents",
    ],
    "shared_search": [
        "Find anything about supply chain issues",
        "Search for fuel-related data from other agents",
        "Look up what the weather agent reported",
        "Any findings about system performance?",
        "Check if anyone logged security concerns",
    ],
    "shared_log": [
        "Report: detected unusual network traffic patterns",
        "Flag: temperature sensor reading out of range",
        "Warning: storage reaching 90% capacity",
        "Observation: API response times degraded by 40%",
        "Finding: new correlation between fuel and altitude",
    ],
    "notify": [
        "Alert the team: critical system failure detected",
        "Send an urgent message about the deadline change",
        "Notify the operator that maintenance is required",
        "Inform the human: the report is ready for review",
        "Page the on-call person about the outage",
    ],
    "exec": [
        "Check how much disk space is left",
        "Run the backup script",
        "Show me the running processes",
        "What's the current CPU usage?",
        "List files in the data directory",
    ],
    "spawn_agent": [
        "Get a specialist to analyze the fuel data",
        "Delegate the weather report to the forecast agent",
        "Have the intel analyst investigate this anomaly",
        "Send this to a code review specialist",
        "Spin up a data cleaning agent for this dataset",
    ],
    "list_tools": [
        "What can I do?",
        "Show my capabilities",
        "List available functions",
    ],
    "none": [
        "Hello there!",
        "Thanks for the update",
        "I understand, let me think about that",
        "What is quantum computing?",
        "Tell me a joke",
        "How does photosynthesis work?",
        "That makes sense",
        "Good morning!",
    ],
}


async def chat(session, model, messages, tools=None, max_tokens=256, temperature=0.1):
    """Send a chat completion request to the universal runtime."""
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        body["tools"] = tools

    start = time.time()
    async with session.post(UNIVERSAL_URL, json=body, timeout=aiohttp.ClientTimeout(total=300)) as resp:
        latency = (time.time() - start) * 1000
        if resp.status != 200:
            text = await resp.text()
            return None, latency, f"HTTP {resp.status}: {text[:200]}"
        data = await resp.json()
        return data, latency, None


def parse_router_output(content):
    """Parse tool names from router model output."""
    try:
        if "[" in content:
            start = content.index("[")
            depth = 0
            for i in range(start, len(content)):
                if content[i] == "[": depth += 1
                elif content[i] == "]":
                    depth -= 1
                    if depth == 0:
                        arr = json.loads(content[start:i+1])
                        names = []
                        for item in arr:
                            if isinstance(item, str):
                                names.append(item)
                            elif isinstance(item, dict):
                                names.append(item.get("name", ""))
                        return sorted([n for n in names if n])
        return []
    except:
        return []


def extract_tool_calls(data):
    """Extract tool call names from OpenAI format response."""
    if not data:
        return []
    choice = data.get("choices", [{}])[0]
    msg = choice.get("message", {})
    calls = msg.get("tool_calls", [])
    return sorted([c.get("function", {}).get("name", "") for c in calls if c.get("function", {}).get("name")])


async def experiment_1_functiongemma(session, model):
    """Test FunctionGemma routing accuracy."""
    print(f"\n{'='*70}")
    print(f"EXPERIMENT 1: {model} Tool Routing")
    print(f"{'='*70}")

    correct = 0
    total = len(TEST_CASES)
    total_latency = 0

    for user_msg, expected, desc in TEST_CASES:
        prompt = f"""{TOOLS_DESC}

User message: {user_msg}

Which function(s) should be called? Respond ONLY with a JSON array of function call objects like [{{"name":"func_name","arguments":{{}}}}], or [] if none needed.

Function calls:"""

        data, latency, err = await chat(session, model, [{"role": "user", "content": prompt}], max_tokens=256)
        total_latency += latency

        if err:
            print(f"  ❌ {desc}: ERROR - {err}")
            continue

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        predicted = parse_router_output(content)
        expected_sorted = sorted(expected)

        match = predicted == expected_sorted
        if match:
            correct += 1

        status = "✅" if match else "❌"
        print(f"  {status} {desc}: expected={expected_sorted} got={predicted} ({latency:.0f}ms)")
        if not match:
            print(f"      raw: {content[:100]}")

    accuracy = correct / total * 100
    avg_lat = total_latency / total
    print(f"\n  RESULT: {correct}/{total} ({accuracy:.1f}%) | avg latency: {avg_lat:.0f}ms")
    return correct, total, avg_lat


async def experiment_2_big_model(session, model):
    """Test big model with native tool calling."""
    print(f"\n{'='*70}")
    print(f"EXPERIMENT 2: {model} Native Tool Calling")
    print(f"{'='*70}")

    correct = 0
    total = min(len(TEST_CASES), 8)  # Limit for speed
    total_latency = 0

    for user_msg, expected, desc in TEST_CASES[:total]:
        data, latency, err = await chat(
            session, model,
            [{"role": "system", "content": "You are a helpful assistant. Use tools when appropriate."},
             {"role": "user", "content": user_msg}],
            tools=OPENAI_TOOLS,
            max_tokens=256,
        )
        total_latency += latency

        if err:
            print(f"  ❌ {desc}: ERROR - {err}")
            continue

        predicted = extract_tool_calls(data) if data else []
        expected_sorted = sorted(expected)

        match = predicted == expected_sorted
        if match:
            correct += 1

        status = "✅" if match else "❌"
        content = (data or {}).get("choices", [{}])[0].get("message", {}).get("content", "")[:60]
        print(f"  {status} {desc}: expected={expected_sorted} got={predicted} ({latency:.0f}ms)")

    accuracy = correct / total * 100
    avg_lat = total_latency / total
    print(f"\n  RESULT: {correct}/{total} ({accuracy:.1f}%) | avg latency: {avg_lat:.0f}ms")
    return correct, total, avg_lat


async def experiment_3_generate_synthetic(session, teacher_model):
    """Generate synthetic training data using the teacher model."""
    print(f"\n{'='*70}")
    print(f"EXPERIMENT 3: Synthetic Data Generation ({teacher_model})")
    print(f"{'='*70}")

    from pathlib import Path
    data_path = Path.home() / ".openhoof" / "data" / "function_pipeline" / "synthetic_training.jsonl"
    data_path.parent.mkdir(parents=True, exist_ok=True)

    generated = 0

    for tool_name, prompts in SYNTHETIC_PROMPTS_PER_TOOL.items():
        expected_tool = [] if tool_name == "none" else [tool_name]

        for user_msg in prompts:
            entry = {
                "input": {"user_message": user_msg, "tools": [t["function"]["name"] for t in OPENAI_TOOLS]},
                "output": {"tool_calls": [{"name": t, "arguments": {}} for t in expected_tool]},
                "metadata": {"source": "synthetic_manual", "tool": tool_name}
            }

            with open(data_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
            generated += 1

    # Also generate diverse examples using the teacher model
    print(f"  Wrote {generated} manual synthetic examples")
    print(f"  Now generating diverse examples with {teacher_model}...")

    for tool_name in ["memory_write", "shared_search", "notify", "exec", "spawn_agent", "none"]:
        prompt = f"""Generate 5 diverse, realistic user messages that should trigger the "{tool_name}" function (or no function if "none").

Available functions:
{TOOLS_DESC}

Output ONLY a JSON array of objects, each with "user_message" and "tool_calls" fields:
[{{"user_message": "...", "tool_calls": [{{"name": "...", "arguments": {{}}}}]}}]"""

        data, latency, err = await chat(
            session, teacher_model,
            [{"role": "system", "content": "You generate training data. Output ONLY valid JSON."},
             {"role": "user", "content": prompt}],
            max_tokens=1024, temperature=0.8,
        )

        if err:
            print(f"  ⚠️ Teacher generation failed for {tool_name}: {err}")
            continue

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        try:
            if "[" in content:
                start = content.index("[")
                end = content.rindex("]") + 1
                examples = json.loads(content[start:end])

                for ex in examples:
                    if isinstance(ex, dict) and "user_message" in ex:
                        entry = {
                            "input": {"user_message": ex["user_message"], "tools": [t["function"]["name"] for t in OPENAI_TOOLS]},
                            "output": {"tool_calls": ex.get("tool_calls", [])},
                            "metadata": {"source": "synthetic_teacher", "teacher": teacher_model, "target_tool": tool_name}
                        }
                        with open(data_path, "a") as f:
                            f.write(json.dumps(entry) + "\n")
                        generated += 1
        except:
            pass

        print(f"  Generated for {tool_name} ({latency:.0f}ms)")

    # Count total
    total_lines = sum(1 for _ in open(data_path) if _.strip())
    print(f"\n  Total training examples: {total_lines}")
    print(f"  Data path: {data_path}")
    return total_lines


async def main():
    print("🦙 OpenHoof Function Calling Pipeline Experiment")
    print(f"   Runtime: {UNIVERSAL_URL}")
    print(f"   Tools: {len(OPENAI_TOOLS)}")
    print(f"   Test cases: {len(TEST_CASES)}\n")

    # Models to test
    # FunctionGemma is 270M — might not be downloaded yet
    # We'll try multiple models
    router_models = [
        "unsloth/Qwen3-1.7B-GGUF:Q4_K_M",  # Already downloaded, use as baseline
    ]
    big_model = "unsloth/Qwen3-1.7B-GGUF:Q4_K_M"  # Use what we have

    async with aiohttp.ClientSession() as session:
        # Quick health check
        try:
            async with session.get("http://localhost:11540/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    print("❌ Universal runtime not available")
                    return
                health = await resp.json()
                print(f"✅ Connected: {health.get('device', {}).get('gpu_name', '?')}")
        except:
            print("❌ Cannot connect to universal runtime")
            return

        # Try FunctionGemma first
        print("\nAttempting to load FunctionGemma-270M...")
        test_data, test_lat, test_err = await chat(
            session,
            "unsloth/functiongemma-270m-it-GGUF:functiongemma-270m-it-Q8_0.gguf",
            [{"role": "user", "content": "hi"}],
            max_tokens=5,
        )
        if not test_err:
            print(f"✅ FunctionGemma loaded ({test_lat:.0f}ms)")
            router_models.insert(0, "unsloth/functiongemma-270m-it-GGUF:functiongemma-270m-it-Q8_0.gguf")
        else:
            print(f"⚠️ FunctionGemma not available: {test_err}")

        # Try Qwen3-8B
        print("\nAttempting to load Qwen3-8B...")
        test_data, test_lat, test_err = await chat(
            session,
            "Qwen/Qwen3-8B-GGUF:Qwen3-8B-Q4_K_M.gguf",
            [{"role": "user", "content": "hi"}],
            max_tokens=5,
        )
        if not test_err:
            print(f"✅ Qwen3-8B loaded ({test_lat:.0f}ms)")
            big_model = "Qwen/Qwen3-8B-GGUF:Qwen3-8B-Q4_K_M.gguf"
        else:
            print(f"⚠️ Qwen3-8B not available yet: {test_err[:100]}")

        results = {}

        # Experiment 1: Router accuracy (test each available model)
        for model in router_models:
            short_name = model.split("/")[-1].split(":")[0]
            correct, total, avg_lat = await experiment_1_functiongemma(session, model)
            results[f"router_{short_name}"] = {"accuracy": correct/total*100, "avg_latency_ms": avg_lat}

        # Experiment 2: Big model native tool calling
        try:
            correct, total, avg_lat = await experiment_2_big_model(session, big_model)
            results["big_model"] = {"accuracy": correct/total*100, "avg_latency_ms": avg_lat}
        except Exception as e:
            print(f"\n⚠️ Big model experiment failed: {e}")

        # Experiment 3: Generate synthetic training data
        try:
            total_examples = await experiment_3_generate_synthetic(session, big_model)
            results["training_data"] = {"total_examples": total_examples}
        except Exception as e:
            print(f"\n⚠️ Synthetic data generation failed: {e}")

        # Summary
        print(f"\n{'='*70}")
        print("SUMMARY")
        print(f"{'='*70}")
        for name, data in results.items():
            print(f"  {name}: {json.dumps(data)}")

        # Save results
        from pathlib import Path
        results_path = Path.home() / ".openhoof" / "data" / "function_pipeline" / "experiment_results.json"
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text(json.dumps(results, indent=2))
        print(f"\nResults saved to {results_path}")


if __name__ == "__main__":
    asyncio.run(main())
