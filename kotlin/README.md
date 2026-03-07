# OpenHoof Kotlin

Kotlin/JVM + Android implementation of the OpenHoof agent runtime.

Mirrors the Python library's five core components:

| Module | Description |
|---|---|
| `Agent` | Core runtime loop — routing, reasoning, events, heartbeat |
| `Soul` | Loads `SOUL.md`, generates lean system prompt (~200 tokens) |
| `Memory` | Loads `MEMORY.md`, keyword search + append |
| `ToolRegistry` | Registers tools, dispatches calls, surfaces schemas |
| `ModelClient` | OpenAI-compatible HTTP client for LlamaFarm / any compatible endpoint |

## Quick Start

```kotlin
// 1. Build a tool registry
val registry = ToolRegistry()
registry.register(
    name = "switch_get_vlan_config",
    description = "Get VLAN configuration from switch",
    parameters = mapOf("type" to "object", "properties" to emptyMap<String, Any>()),
) { _ ->
    mapOf("vlans" to listOf(
        mapOf("vid" to 1, "name" to "default"),
        mapOf("vid" to 10, "name" to "mgmt"),
    ))
}

// 2. Build the agent
val agent = Agent.build {
    soul   = Soul.fromFile("SOUL.md")
    memory = Memory.fromFile("MEMORY.md")
    client = ModelClient(
        endpoint = "http://192.168.1.5:11540/v1",
        model    = "ft:da674646",
    )
    tools(registry)
}

// 3. Route a single query (fast path — FunctionGemma)
val result = agent.route("switch vlans")
println(result.toolName)      // switch_get_vlan_config
println(result.value())       // {vlans: [...]}

// 4. Multi-turn reasoning
val answer = agent.reason("what vlans are on the switch and which ports use them?")
println(answer)
```

## Android

Add to `build.gradle` (app module):

```kotlin
implementation("ai.llamafarm:openhoof:0.1.0")
```

Network call goes to LlamaFarm running on a laptop/server on the same network.
No on-device model required for Option A.

For Option B (on-device ONNX), add:
```kotlin
implementation("com.microsoft.onnxruntime:onnxruntime-android:1.18.0")
```

## Running Tests

```bash
cd kotlin/
./gradlew test
```

## Building

```bash
./gradlew build
./gradlew jar
```

## Architecture

```
User query
    ↓
Agent.route(query)
    ↓
ModelClient.complete(messages, tools)   ← LlamaFarm HTTP call
    ↓
FunctionGemma output: "switch_get_vlan_config()"
    ↓
ModelClient.parseFunctionCallText()     ← text format parser
    ↓
ToolRegistry.executeSafe("switch_get_vlan_config", {})
    ↓
Your handler: chud.get("/api/switch/vlans")
    ↓
RouteResult(toolCall, output, rawContent)
```

## Differences from Python

| Python | Kotlin |
|---|---|
| `asyncio` | Kotlin Coroutines |
| `requests` | OkHttp |
| `json` | kotlinx.serialization |
| `pathlib.Path` | `java.io.File` |
| Keyword args | Named params |
| Type hints | Kotlin type system |

Logic is identical — this is a direct translation of the Python reference implementation.
