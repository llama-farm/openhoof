package ai.llamafarm.openhoof

import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.serialization.json.*

/**
 * Agent — the core runtime loop.
 *
 * Wires together Soul + Memory + ToolRegistry + ModelClient into an agent
 * that can:
 *   - Maintain conversation history
 *   - Run multi-turn reasoning loops (LLM → tool call → result → LLM → ...)
 *   - Route single queries through a fast router (FunctionGemma)
 *   - Process an event queue
 *   - Run a heartbeat on a configurable interval
 *   - Capture every tool call as training data (JSONL)
 *
 * Usage — simple one-shot:
 *   val agent = Agent.build {
 *     soul    = Soul.fromFile("SOUL.md")
 *     memory  = Memory.fromFile("MEMORY.md")
 *     client  = ModelClient(endpoint = "http://192.168.1.5:11540/v1", model = "ft:da674646")
 *     tools(registry)
 *   }
 *   val result = agent.route("switch vlans")   // single FunctionGemma call
 *   val answer = agent.reason("what vlans are on the switch?")  // multi-turn
 *
 * Usage — event loop:
 *   agent.on("battery_low") { agent.stop() }
 *   agent.heartbeatInterval = 30
 *   agent.run()   // blocks until stopped
 */
class Agent private constructor(
    val soul: Soul,
    val memory: Memory,
    val client: ModelClient,
    val registry: ToolRegistry,
    val trainingLog: String? = null,          // path to JSONL file; null = disabled
    val heartbeatInterval: Int = 30,          // seconds; 0 = disabled
    val maxReasoningTurns: Int = 10,
    val stripToolDescriptions: Boolean = true,
) {
    // Conversation history (grows across reason() calls)
    private val history = mutableListOf<ChatMessage>()

    // Event queue
    private val events = Channel<AgentEvent>(capacity = Channel.UNLIMITED)

    // Heartbeat + exit condition handlers
    private val heartbeatHandlers = mutableListOf<suspend () -> Unit>()
    private val exitConditions    = mutableListOf<() -> Boolean>()

    private var running = false
    private var scope: CoroutineScope? = null

    // ── Public API ────────────────────────────────────────────────────────────

    /**
     * Route a single query through the router model (FunctionGemma).
     * Fast path — no conversation history, no multi-turn.
     * Returns the tool call result, or null if no tool matched.
     */
    suspend fun route(query: String): RouteResult {
        val result = client.complete(
            messages = listOf(
                ChatMessage.system(soul.systemPrompt),
                ChatMessage.user(query),
            ),
            tools = registry.schemas.toList().map { it.jsonObject },
            stripToolDescriptions = stripToolDescriptions,
        )

        val call = result.firstTool ?: return RouteResult(
            query = query,
            toolCall = null,
            output = null,
            rawContent = result.content,
        )

        logTraining(query, call)

        val output = registry.executeSafe(call.name, call.params)

        return RouteResult(
            query = query,
            toolCall = call,
            output = output,
            rawContent = result.content,
        )
    }

    /**
     * Multi-turn reasoning loop.
     * LLM sees tool results and decides next steps until it stops calling tools.
     * Conversation history is maintained across calls.
     */
    suspend fun reason(prompt: String): String {
        // Ensure system message is at the start
        if (history.isEmpty()) {
            val systemContent = buildString {
                appendLine(soul.systemPrompt)
                if (!memory.isEmpty) {
                    appendLine()
                    appendLine("## Memory")
                    // Inject relevant memory snippets
                    val snippets = memory.search(prompt, maxResults = 3)
                    if (snippets.isNotEmpty()) {
                        snippets.forEach { appendLine(it.text) }
                    } else {
                        append(memory.summary(maxChars = 1000))
                    }
                }
            }
            history.add(ChatMessage.system(systemContent))
        }

        history.add(ChatMessage.user(prompt))

        val tools = registry.schemas.toList().map { it.jsonObject }

        repeat(maxReasoningTurns) { turn ->
            val result = client.complete(
                messages = history,
                tools = if (registry.size > 0) tools else null,
                stripToolDescriptions = stripToolDescriptions,
            )

            // No tool call → final answer
            if (!result.hasToolCall) {
                val content = result.content ?: "Done."
                history.add(ChatMessage.assistant(content))
                return content
            }

            // Process tool calls
            val assistantMsg = buildAssistantMessage(result)
            history.add(assistantMsg)

            result.toolCalls.forEach { call ->
                logTraining(prompt, call)
                val toolResult = registry.executeSafe(call.name, call.params)
                val resultStr = when (toolResult) {
                    is ToolResult.Success    -> formatResult(toolResult.value)
                    is ToolResult.Error      -> "Error: ${toolResult.message}"
                    is ToolResult.UnknownTool -> "Error: unknown tool '${call.name}'"
                }
                history.add(ChatMessage.tool(id = call.id, content = resultStr))
            }
        }

        return "Max reasoning turns reached."
    }

    /**
     * Push an event into the agent's event queue.
     * If the agent loop is running, it will process this event.
     */
    fun emit(event: AgentEvent) {
        events.trySend(event)
    }

    fun emit(name: String, data: Map<String, Any> = emptyMap()) {
        emit(AgentEvent(name = name, data = data))
    }

    /** Register a handler that fires on every heartbeat. */
    fun onHeartbeat(handler: suspend () -> Unit) {
        heartbeatHandlers.add(handler)
    }

    /** Register an exit condition. Agent stops when any returns true. */
    fun onExit(condition: () -> Boolean) {
        exitConditions.add(condition)
    }

    /**
     * Run the agent event loop (blocking / suspend).
     * Processes events and fires heartbeats until stopped.
     */
    suspend fun run() {
        running = true
        scope = CoroutineScope(Dispatchers.Default + SupervisorJob())

        // Start heartbeat
        val heartbeatJob = if (heartbeatInterval > 0) {
            scope!!.launch {
                while (running) {
                    delay(heartbeatInterval * 1000L)
                    if (!running) break
                    heartbeatHandlers.forEach { it() }
                    if (exitConditions.any { it() }) {
                        stop()
                    }
                }
            }
        } else null

        // Process events
        while (running) {
            val event = try {
                withTimeoutOrNull(1000) { events.receive() }
            } catch (e: Exception) {
                null
            } ?: continue

            try {
                processEvent(event)
            } catch (e: Exception) {
                // Log but don't crash the loop
            }
        }

        heartbeatJob?.cancel()
        scope?.cancel()
    }

    /** Stop the agent loop. */
    fun stop() {
        running = false
        scope?.cancel()
    }

    /** Reset conversation history. */
    fun resetHistory() {
        history.clear()
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    private suspend fun processEvent(event: AgentEvent) {
        when (event.name) {
            "query"  -> route(event.data["text"] as? String ?: return)
            "reason" -> reason(event.data["text"] as? String ?: return)
            "stop"   -> stop()
            else     -> {
                // Route unknown events as queries
                route("${event.name}: ${event.data}")
            }
        }
    }

    private fun buildAssistantMessage(result: CompletionResult): ChatMessage {
        val toolCallsJson = result.toolCalls.map { call ->
            buildJsonObject {
                put("id", call.id)
                put("type", "function")
                putJsonObject("function") {
                    put("name", call.name)
                    put("arguments", Json.encodeToString(
                        JsonObject.serializer(),
                        buildJsonObject {
                            call.params.forEach { (k, v) ->
                                when (v) {
                                    is String  -> put(k, v)
                                    is Boolean -> put(k, v)
                                    is Number  -> put(k, v.toDouble())
                                    else       -> put(k, v.toString())
                                }
                            }
                        }
                    ))
                }
            }
        }
        return ChatMessage(
            role = "assistant",
            content = result.content,
            toolCalls = toolCallsJson,
        )
    }

    private fun formatResult(value: Any?): String = when (value) {
        null       -> "null"
        is String  -> value
        is Map<*, *>, is List<*> -> Json.encodeToString(
            JsonElement.serializer(),
            anyToJson(value)
        )
        else -> value.toString()
    }

    private fun anyToJson(value: Any?): JsonElement = when (value) {
        null        -> JsonNull
        is String   -> JsonPrimitive(value)
        is Boolean  -> JsonPrimitive(value)
        is Number   -> JsonPrimitive(value.toDouble())
        is Map<*, *> -> buildJsonObject {
            value.forEach { (k, v) -> put(k.toString(), anyToJson(v)) }
        }
        is List<*>  -> buildJsonArray { value.forEach { add(anyToJson(it)) } }
        else        -> JsonPrimitive(value.toString())
    }

    private fun logTraining(input: String, call: ToolCall) {
        val path = trainingLog ?: return
        val paramsStr = call.params.entries.joinToString(", ") { (k, v) ->
            val vStr = when (v) {
                is String -> "\"$v\""
                else -> v.toString()
            }
            "$k=$vStr"
        }
        val output = "${call.name}($paramsStr)"
        val line = buildJsonObject {
            putJsonArray("conversations") {
                addJsonObject { put("from", "human"); put("value", input) }
                addJsonObject { put("from", "gpt");   put("value", output) }
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
        var client: ModelClient = ModelClient()
        var registry: ToolRegistry = ToolRegistry()
        var trainingLog: String? = null
        var heartbeatInterval: Int = 30
        var maxReasoningTurns: Int = 10
        var stripToolDescriptions: Boolean = true

        fun tools(r: ToolRegistry) { registry = r }

        fun build() = Agent(
            soul = soul,
            memory = memory,
            client = client,
            registry = registry,
            trainingLog = trainingLog,
            heartbeatInterval = heartbeatInterval,
            maxReasoningTurns = maxReasoningTurns,
            stripToolDescriptions = stripToolDescriptions,
        )
    }
}

// ── Supporting types ──────────────────────────────────────────────────────────

data class AgentEvent(
    val name: String,
    val data: Map<String, Any> = emptyMap(),
    val priority: Int = 0,
)

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
