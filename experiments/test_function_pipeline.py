#!/usr/bin/env python3
"""Experiment: Test the FunctionGemma two-stage pipeline.

Run with: python -m experiments.test_function_pipeline

This script:
1. Defines our standard OpenHoof tools
2. Tests FunctionGemma's ability to route tool calls
3. Compares with the big model's tool calling
4. Generates synthetic training data
5. Reports results
"""

import asyncio
import json
import time
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openhoof.inference.llamafarm import LlamaFarmAdapter
from openhoof.inference.function_pipeline import (
    FunctionCallingPipeline,
    SyntheticTrainingGenerator,
    ToolDefinition,
)


# Define our standard tools
TOOLS = [
    ToolDefinition(
        name="memory_write",
        description="Write content to agent memory files. Use for daily logs, MEMORY.md updates, etc.",
        parameters={
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path relative to workspace"},
                "content": {"type": "string", "description": "Content to write"},
                "append": {"type": "boolean", "description": "Append instead of replace"},
            },
            "required": ["file", "content"],
        },
        examples=[
            {"input": "Remember that the meeting is at 3pm", "output": [{"name": "memory_write", "arguments": {"file": "memory/2026-02-07.md", "content": "Meeting at 3pm", "append": True}}]},
            {"input": "Update my notes about the fuel analysis", "output": [{"name": "memory_write", "arguments": {"file": "MEMORY.md", "content": "Fuel analysis results: ...", "append": True}}]},
        ],
    ),
    ToolDefinition(
        name="memory_read",
        description="Read content from workspace files. Use to check SOUL.md, daily memory, etc.",
        parameters={
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path relative to workspace"},
            },
            "required": ["file"],
        },
        examples=[
            {"input": "What did I do yesterday?", "output": [{"name": "memory_read", "arguments": {"file": "memory/2026-02-06.md"}}]},
        ],
    ),
    ToolDefinition(
        name="shared_write",
        description="Write to shared knowledge store that all agents can access.",
        parameters={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Knowledge entry key"},
                "content": {"type": "string", "description": "Content to store"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["key", "content"],
        },
    ),
    ToolDefinition(
        name="shared_read",
        description="Read from shared cross-agent knowledge store.",
        parameters={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Knowledge entry key"},
            },
            "required": ["key"],
        },
    ),
    ToolDefinition(
        name="shared_search",
        description="Search shared knowledge and findings across all agents.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "category": {"type": "string", "description": "Filter by category"},
                "limit": {"type": "integer", "description": "Max results"},
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="shared_log",
        description="Log a finding or event to the shared append-only log.",
        parameters={
            "type": "object",
            "properties": {
                "finding": {"type": "string", "description": "The finding to log"},
                "category": {"type": "string", "description": "Category (anomaly, insight, warning, status)"},
                "severity": {"type": "string", "description": "info, warning, critical"},
            },
            "required": ["finding"],
        },
    ),
    ToolDefinition(
        name="spawn_agent",
        description="Spawn a sub-agent for specialized tasks.",
        parameters={
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Task for the sub-agent"},
                "agent_id": {"type": "string", "description": "Agent type to spawn"},
                "label": {"type": "string", "description": "Human-readable label"},
            },
            "required": ["task"],
        },
    ),
    ToolDefinition(
        name="notify",
        description="Send a notification to the human operator.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Notification title"},
                "message": {"type": "string", "description": "Notification body"},
                "priority": {"type": "string", "description": "low, medium, high, critical"},
            },
            "required": ["title", "message"],
        },
    ),
    ToolDefinition(
        name="exec",
        description="Execute a shell command. Use for running scripts, checking system status, etc.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
            },
            "required": ["command"],
        },
    ),
    ToolDefinition(
        name="list_tools",
        description="List all tools currently available to you.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
]


# Test cases: (user_message, expected_tool_names, description)
TEST_CASES = [
    ("Remember that the fuel burn rate was 15% above normal today", ["memory_write"], "Simple memory write"),
    ("What's in my daily notes?", ["memory_read"], "Simple memory read"),
    ("Share the fuel analysis results with other agents", ["shared_write"], "Shared write"),
    ("What have other agents found about weather?", ["shared_search"], "Shared search"),
    ("Log that we detected an anomaly in sector 7", ["shared_log"], "Log a finding"),
    ("I need a fuel specialist to analyze this data", ["spawn_agent"], "Spawn sub-agent"),
    ("Alert the operator about the critical fuel shortage", ["notify"], "Send notification"),
    ("Check disk space on the server", ["exec"], "Execute command"),
    ("What tools do I have?", ["list_tools"], "List tools"),
    ("Hello, how are you?", [], "No tool needed - greeting"),
    ("What is 2+2?", [], "No tool needed - simple question"),
    ("Save this analysis and also notify the operator", ["memory_write", "notify"], "Multi-tool"),
    ("Read yesterday's notes and share them with the team", ["memory_read", "shared_write"], "Multi-tool chain"),
    ("Search for any fuel-related findings and log a summary", ["shared_search", "shared_log"], "Search then log"),
    ("Run the diagnostic script and save the output to memory", ["exec", "memory_write"], "Exec then save"),
]


async def test_router(pipeline: FunctionCallingPipeline):
    """Test the FunctionGemma router on our test cases."""
    print("\n" + "="*70)
    print("EXPERIMENT 1: FunctionGemma Tool Routing Accuracy")
    print("="*70)
    
    correct = 0
    total = len(TEST_CASES)
    results = []
    
    for user_msg, expected_tools, desc in TEST_CASES:
        result = await pipeline.route_tools(user_msg, TOOLS)
        
        predicted_tools = sorted([tc.name for tc in result.tool_calls])
        expected_sorted = sorted(expected_tools)
        
        match = predicted_tools == expected_sorted
        if match:
            correct += 1
        
        status = "✅" if match else "❌"
        print(f"\n{status} {desc}")
        print(f"   Input: \"{user_msg[:60]}...\"" if len(user_msg) > 60 else f"   Input: \"{user_msg}\"")
        print(f"   Expected: {expected_sorted}")
        print(f"   Got:      {predicted_tools}")
        print(f"   Latency:  {result.router_latency_ms:.0f}ms | Confidence: {result.confidence:.2f}")
        
        results.append({
            "desc": desc,
            "match": match,
            "expected": expected_sorted,
            "predicted": predicted_tools,
            "latency_ms": result.router_latency_ms,
            "confidence": result.confidence,
        })
    
    accuracy = correct / total * 100
    avg_latency = sum(r["latency_ms"] for r in results) / len(results)
    
    print(f"\n{'='*70}")
    print(f"RESULTS: {correct}/{total} correct ({accuracy:.1f}%)")
    print(f"Average latency: {avg_latency:.0f}ms")
    print(f"{'='*70}")
    
    return results, accuracy


async def test_big_model_comparison(inference: LlamaFarmAdapter):
    """Compare tool calling between FunctionGemma and Qwen3-8B."""
    print("\n" + "="*70)
    print("EXPERIMENT 2: Qwen3-8B Direct Tool Calling (Baseline)")
    print("="*70)
    
    # Convert tools to OpenAI format
    openai_tools = []
    for t in TOOLS:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description.split("\n")[0],
                "parameters": t.parameters,
            }
        })
    
    correct = 0
    total = len(TEST_CASES)
    
    for user_msg, expected_tools, desc in TEST_CASES[:5]:  # Just test first 5 (big model is slow)
        start = time.time()
        
        try:
            response = await inference.chat_completion(
                messages=[
                    {"role": "system", "content": "You are a helpful assistant. Use tools when appropriate."},
                    {"role": "user", "content": user_msg},
                ],
                tools=openai_tools,
                model="qwen3-8b",
                stateless=True,
                rag_enabled=False,
                max_tokens=256,
            )
            
            latency = (time.time() - start) * 1000
            predicted = sorted([tc.name for tc in response.tool_calls])
            expected_sorted = sorted(expected_tools)
            match = predicted == expected_sorted
            if match:
                correct += 1
            
            status = "✅" if match else "❌"
            print(f"\n{status} {desc}")
            print(f"   Expected: {expected_sorted} | Got: {predicted} | {latency:.0f}ms")
            
        except Exception as e:
            print(f"\n❌ {desc}: ERROR - {e}")
    
    print(f"\nQwen3-8B: {correct}/5 on first 5 cases")


async def generate_synthetic_data(generator: SyntheticTrainingGenerator):
    """Generate synthetic training examples using the big model."""
    print("\n" + "="*70)
    print("EXPERIMENT 3: Synthetic Training Data Generation")
    print("="*70)
    
    print("Generating synthetic examples using Qwen3-8B as teacher...")
    count = await generator.generate_examples(TOOLS, num_examples=50)
    print(f"Generated {count} synthetic training examples")
    
    total = generator.get_training_data_count()
    print(f"Total training data available: {total} examples")
    
    if total >= 20:
        output = generator.export_for_finetuning()
        print(f"Exported fine-tuning dataset to: {output}")


async def main():
    print("🦙 OpenHoof Function Calling Pipeline Experiment")
    print(f"   Testing {len(TOOLS)} tools with {len(TEST_CASES)} test cases\n")
    
    # Initialize
    inference = LlamaFarmAdapter(
        base_url="http://localhost:14345",
        namespace="atmosphere",
        project="openhoof",
    )
    
    # Check health
    healthy = await inference.health_check()
    if not healthy:
        print("❌ LlamaFarm not available. Start it first.")
        return
    print("✅ LlamaFarm connected\n")
    
    pipeline = FunctionCallingPipeline(inference)
    generator = SyntheticTrainingGenerator(inference)
    
    # Run experiments
    try:
        # Experiment 1: Test router accuracy
        router_results, accuracy = await test_router(pipeline)
        
        # Experiment 2: Compare with big model (if available)
        try:
            await test_big_model_comparison(inference)
        except Exception as e:
            print(f"\nSkipping big model comparison: {e}")
        
        # Experiment 3: Generate synthetic data
        try:
            await generate_synthetic_data(generator)
        except Exception as e:
            print(f"\nSkipping synthetic data generation: {e}")
        
        # Final stats
        stats = pipeline.get_stats()
        print(f"\n{'='*70}")
        print("PIPELINE STATS")
        print(f"{'='*70}")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        
    except Exception as e:
        print(f"\n❌ Experiment failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
