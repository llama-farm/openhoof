package ai.llamafarm.openhoof

import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.serialization.json.*

/**
 * Agent — core runtime loop.
 *
 * Works entirely on-device with LocalCompletionProvider.
 * No LlamaFarm, no network required.
 *
 * Usage — on-device only:
 *   val agent = Agent.build {
 *     soul     = Soul.fromFile("SOUL.md")
 *     memory   = Memory.fromFile("MEMORY.md")
 *     provider = LocalCompletionProvider(modelPath = "/data/models/functiongemma-270m")
 *     tools(registry)
 *   }
 *   val result = agent.route("switch vlans")
 *
 * Usage — hybrid (local first, remote fallback):
 *   val agent = Agent.build {
 *     provider = HybridCompletionProvider(
 *       primary   = LocalCompletionProvider(modelPath = "/data/models/functiongemma-270m"),
 *       secondary = RemoteCompletionProvider(endpoint  = "http://192.168.1.5:11540/v1"),
 *     )
 *   }
 */
class Agent private constructor(
    val soul: Soul,
    val memory: Memory,
    val provider: CompletionProvider,
    val registry: ToolRegistry,
    val trainingLog: String? = null,
    val heartbeatInterval: Int = 30,
    val maxReasoningTurns: Int = 10,
    val stripToolDescriptions: Boolean = true,
) {
    private val history = mutableListOf<ChatMessage>()
    private val events  = Channel<AgentEvent>(capacity = Channel.UNLIMITED)
    private val heartbeatHandlers = mutableListOf<suspend () -> Unit>()
    private val exitConditions    = mutableListOf<() -> Boolean>()
    private var running = false
    private var scope: CoroutineScope? = null

    // ── Public API ────────────────────────────────────────────────────────────

    /**
     * Route a single query through the model (fast path).
     * Uses FunctionGemma on-device or remote — whichever provider is configured.
     * No conversation history, no multi-turn.
     */
    suspend fun route(query: String): RouteResult {
        val result = provider.complete(
            messages = listOf(
                ChatMessage.system(soul.systemPrompt),
                ChatMessage.user(query),
            ),
            tools = registry.schemas.toList().map { it.jsonObject },
            stripToolDescriptions = stripToolDescriptions,
        )

        val call = result.firstTool ?: return RouteResult(
            query = query, toolCall = null, output = null, rawContent = result.content,
        )

        logTraining(query, call)

        val output = registry.executeSafe(call.name, call.params)
        return RouteResult(query = query, toolCall = call, output = output, rawContent = result.content)
    }

    /**
     * Multi-turn reasoning loop.
     * The model sees tool results and decides next steps until it stops calling tools.
     */
    suspend fun reason(prompt: String): String {
        if (history.isEmpty()) {
            val systemContent = buildString {
                appendLine(soul.systemPrompt)
                if (!memory.isEmpty) {
                    appendLine()
                    val snippets = memory.search(prompt, maxResults = 3)
                    if (snippets.isNotEmpty()) snippets.forEach { appendLine(it.text) }
                    else append(memory.summary(maxChars = 1000))
                }
            }
            history.add(ChatMessage.system(systemContent))
        }
        history.add(ChatMessage.user(prompt))

        val tools = registry.schemas.toList().map { it.jsonObject }

        repeat(maxReasoningTurns) {
            val result = provider.complete(
                messages = history,
                tools = if (registry.size > 0) tools else null,
                stripToolDescriptions = stripToolDescriptions,
            )

            if (!result.hasToolCall) {
                val content = result.content ?: "Done."
                history.add(ChatMessage.assistant(content))
                return content
            }

            history.add(buildAssistantMessage(result))

            result.toolCalls.forEach { call ->
                logTraining(prompt, call)
                val toolResult = registry.executeSafe(call.name, call.params)
                val resultStr = when (toolResult) {
                    is ToolResult.Success     -> formatResult(toolResult.value)
                    is ToolResult.Error       -> "Error: ${toolResult.message}"
                    is ToolResult.UnknownTool -> "Error: unknown tool '${call.name}'"
                }
                history.add(ChatMessage.tool(id = call.id, content = resultStr))
            }
        }

        return "Max reasoning turns reached."
    }

    fun emit(event: AgentEvent) { events.trySend(event) }
    fun emit(name: String, data: Map<String, Any> = emptyMap()) = emit(AgentEvent(name, data))

    fun onHeartbeat(handler: suspend () -> Unit) { heartbeatHandlers.add(handler) }
    fun onExit(condition: () -> Boolean) { exitConditions.add(condition) }

    suspend fun run() {
        running = true
        scope = CoroutineScope(Dispatchers.Default + SupervisorJob())

        val heartbeatJob = if (heartbeatInterval > 0) scope!!.launch {
            while (running) {
                delay(heartbeatInterval * 1000L)
                heartbeatHandlers.forEach { it() }
                if (exitConditions.any { it() }) stop()
            }
        } else null

        while (running) {
            val event = try {
                withTimeoutOrNull(1000) { events.receive() }
            } catch (e: Exception) { null } ?: continue
            try { processEvent(event) } catch (e: Exception) { /* log, don't crash */ }
        }

        heartbeatJob?.cancel()
        scope?.cancel()
    }

    fun stop() { running = false; scope?.cancel() }
    fun resetHistory() { history.clear() }

    // ── Internal ──────────────────────────────────────────────────────────────

    private suspend fun processEvent(event: AgentEvent) {
        when (event.name) {
            "query"  -> route(event.data["text"] as? String ?: return)
            "reason" -> reason(event.data["text"] as? String ?: return)
            "stop"   -> stop()
            else     -> route("${event.name}: ${event.data}")
        }
    }

    private fun buildAssistantMessage(result: CompletionResult): ChatMessage {
        val toolCallsJson = result.toolCalls.map { call ->
            buildJsonObject {
                put("id", call.id)
                put("type", "function")
                putJsonObject("function") {
                    put("name", call.name)
                    put("arguments", Json.encodeToString(JsonObject.serializer(), buildJsonObject {
                        call.params.forEach { (k, v) ->
                            when (v) {
                                is String  -> put(k, v)
                                is Boolean -> put(k, v)
                                is Number  -> put(k, v.toDouble())
                                else       -> put(k, v.toString())
                            }
                        }
                    }))
                }
            }
        }
        return ChatMessage(role = "assistant", content = result.content, toolCalls = toolCallsJson)
    }

    private fun formatResult(value: Any?): String = when (value) {
        null        -> "null"
        is String   -> value
        is Map<*, *>, is List<*> -> Json.encodeToString(JsonElement.serializer(), anyToJson(value))
        else        -> value.toString()
    }

    private fun anyToJson(value: Any?): JsonElement = when (value) {
        null         -> JsonNull
        is String    -> JsonPrimitive(value)
        is Boolean   -> JsonPrimitive(value)
        is Number    -> JsonPrimitive(value.toDouble())
        is Map<*, *> -> buildJsonObject { value.forEach { (k, v) -> put(k.toString(), anyToJson(v)) } }
        is List<*>   -> buildJsonArray { value.forEach { add(anyToJson(it)) } }
        else         -> JsonPrimitive(value.toString())
    }

    private fun logTraining(input: String, call: ToolCall) {
        val path = trainingLog ?: return
        val paramsStr = call.params.entries.joinToString(", ") { (k, v) ->
            "$k=${if (v is String) "\"$v\"" else v}"
        }
        val line = buildJsonObject {
            putJsonArray("conversations") {
                addJsonObject { put("from", "human"); put("value", input) }
                addJsonObject { put("from", "gpt");   put("value", "${call.name}($paramsStr)") }
            }
        }
        java.io.File(path).appendText(Json.encodeToString(JsonObject.serializer(), line) + "\n")
    }

    // ── Builder ───────────────────────────────────────────────────────────────

    companion object {
        fun build(block: Builder.() -> Unit): Agent = Builder().apply(block).build()
    }

    class Builder {
        var soul: Soul = Soul.inline("Agent")
        var memory: Memory = Memory.empty()
        var provider: CompletionProvider = RemoteCompletionProvider()
        var registry: ToolRegistry = ToolRegistry()
        var trainingLog: String? = null
        var heartbeatInterval: Int = 30
        var maxReasoningTurns: Int = 10
        var stripToolDescriptions: Boolean = true

        fun tools(r: ToolRegistry) { registry = r }

        // Convenience: set a local engine directly
        fun localModel(engine: LocalInferenceEngine, maxTokens: Int = 64) {
            provider = LocalCompletionProvider(engine = engine, maxNewTokens = maxTokens)
        }

        // Convenience: set remote endpoint directly
        fun remoteModel(endpoint: String, model: String) {
            provider = RemoteCompletionProvider(endpoint = endpoint, model = model)
        }

        // Convenience: local first, remote fallback
        fun hybridModel(engine: LocalInferenceEngine, remoteEndpoint: String, remoteModel: String) {
            provider = HybridCompletionProvider(
                primary   = LocalCompletionProvider(engine = engine),
                secondary = RemoteCompletionProvider(endpoint = remoteEndpoint, model = remoteModel),
            )
        }

        fun build() = Agent(
            soul = soul, memory = memory, provider = provider, registry = registry,
            trainingLog = trainingLog, heartbeatInterval = heartbeatInterval,
            maxReasoningTurns = maxReasoningTurns, stripToolDescriptions = stripToolDescriptions,
        )
    }
}

// ── Supporting types ──────────────────────────────────────────────────────────

data class AgentEvent(val name: String, val data: Map<String, Any> = emptyMap(), val priority: Int = 0)

data class RouteResult(
    val query: String,
    val toolCall: ToolCall?,
    val output: ToolResult?,
    val rawContent: String?,
) {
    val toolName: String? get() = toolCall?.name
    val succeeded: Boolean get() = output is ToolResult.Success
    fun value(): Any? = (output as? ToolResult.Success)?.value
}
