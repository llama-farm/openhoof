package ai.llamafarm.openhoof

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * OpenAI-compatible chat completions client for LlamaFarm Universal Runtime.
 *
 * Supports:
 *  - Standard text completions
 *  - Tool calls (function calling)
 *  - ft: alias resolution → local GGUF path
 *  - Configurable endpoint (LlamaFarm, OpenAI, any compatible server)
 *
 * Usage:
 *   val client = ModelClient(endpoint = "http://192.168.1.5:11540/v1", model = "ft:da674646")
 *   val result = client.complete(messages, tools)
 */
class ModelClient(
    val endpoint: String = "http://localhost:11540/v1",
    val model: String = "unsloth/functiongemma-270m-it-GGUF",
    val temperature: Float = 0.0f,
    val maxTokens: Int = 512,
) {
    private val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = false
    }

    private val http = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()

    // ── Public API ────────────────────────────────────────────────────────────

    /**
     * Run a chat completion. Returns the assistant message content.
     */
    suspend fun complete(
        messages: List<ChatMessage>,
        tools: List<JsonObject>? = null,
        stripToolDescriptions: Boolean = true,
    ): CompletionResult = withContext(Dispatchers.IO) {
        val resolvedModel = resolveModel(model)

        val slimTools = if (tools != null && stripToolDescriptions) {
            tools.map { slimTool(it) }
        } else {
            tools
        }

        val payload = buildJsonObject {
            put("model", resolvedModel)
            put("temperature", temperature)
            put("max_tokens", maxTokens)
            putJsonArray("messages") {
                messages.forEach { msg ->
                    addJsonObject {
                        put("role", msg.role)
                        if (msg.content != null) put("content", msg.content) else put("content", JsonNull)
                        msg.toolCalls?.let { tc ->
                            putJsonArray("tool_calls") {
                                tc.forEach { add(it) }
                            }
                        }
                        msg.toolCallId?.let { put("tool_call_id", it) }
                        msg.name?.let { put("name", it) }
                    }
                }
            }
            if (!slimTools.isNullOrEmpty()) {
                putJsonArray("tools") {
                    slimTools.forEach { add(it) }
                }
                put("tool_choice", "auto")
            }
        }

        val body = json.encodeToString(payload).toRequestBody(JSON_MEDIA)
        val request = Request.Builder()
            .url("$endpoint/chat/completions")
            .post(body)
            .build()

        val response = http.newCall(request).execute()
        val responseBody = response.body?.string() ?: throw RuntimeException("Empty response")

        if (!response.isSuccessful) {
            throw RuntimeException("HTTP ${response.code}: $responseBody")
        }

        parseCompletion(json.parseToJsonElement(responseBody).jsonObject)
    }

    /** Check if the endpoint is reachable. */
    suspend fun isHealthy(): Boolean = withContext(Dispatchers.IO) {
        try {
            val healthUrl = endpoint.removeSuffix("/v1")
            val request = Request.Builder().url("$healthUrl/health").get().build()
            http.newCall(request).execute().isSuccessful
        } catch (e: Exception) {
            false
        }
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    /**
     * Resolve ft: alias to direct GGUF path.
     * ft:da674646 → ~/.llamafarm/models/llm/da674646/gguf/model-q8_0.gguf
     */
    private fun resolveModel(model: String): String {
        if (!model.startsWith("ft:")) return model
        val jobId = model.removePrefix("ft:")
        val home = System.getProperty("user.home") ?: return model
        val gguf = File("$home/.llamafarm/models/llm/$jobId/gguf/model-q8_0.gguf")
        return if (gguf.exists()) gguf.absolutePath else model
    }

    /**
     * Strip descriptions from tool schemas — FunctionGemma 270M performs better
     * seeing only names and parameter types, not long descriptions.
     */
    private fun slimTool(tool: JsonObject): JsonObject {
        val fn = tool["function"]?.jsonObject ?: return tool
        val slimFn = buildJsonObject {
            put("name", fn["name"] ?: JsonPrimitive(""))
            fn["parameters"]?.jsonObject?.let { params ->
                putJsonObject("parameters") {
                    put("type", params["type"] ?: JsonPrimitive("object"))
                    params["properties"]?.jsonObject?.let { props ->
                        putJsonObject("properties") {
                            props.forEach { (k, v) ->
                                val prop = v.jsonObject
                                putJsonObject(k) {
                                    // Keep type and enum, drop description
                                    prop["type"]?.let { put("type", it) }
                                    prop["enum"]?.let { put("enum", it) }
                                }
                            }
                        }
                    }
                    params["required"]?.let { put("required", it) }
                }
            }
        }
        return buildJsonObject {
            put("type", JsonPrimitive("function"))
            put("function", slimFn)
        }
    }

    private fun parseCompletion(response: JsonObject): CompletionResult {
        val choice = response["choices"]?.jsonArray?.firstOrNull()?.jsonObject
            ?: return CompletionResult(content = null, toolCalls = emptyList())

        val message = choice["message"]?.jsonObject
            ?: return CompletionResult(content = null, toolCalls = emptyList())

        val content = message["content"]?.let {
            if (it is JsonNull) null else it.jsonPrimitive.contentOrNull
        }

        val toolCalls = message["tool_calls"]?.jsonArray?.mapNotNull { tc ->
            val obj = tc.jsonObject
            val fn = obj["function"]?.jsonObject ?: return@mapNotNull null
            val name = fn["name"]?.jsonPrimitive?.content ?: return@mapNotNull null
            val argsStr = fn["arguments"]?.jsonPrimitive?.contentOrNull ?: "{}"
            val args = try {
                json.parseToJsonElement(argsStr).jsonObject
                    .mapValues { (_, v) -> v.toPrimitive() }
            } catch (e: Exception) {
                emptyMap()
            }
            ToolCall(
                id = obj["id"]?.jsonPrimitive?.contentOrNull ?: "call_${name}",
                name = name,
                params = args,
            )
        } ?: emptyList()

        // Also try parsing text format: tool_name(param=value)
        val parsedFromText = if (toolCalls.isEmpty() && content != null) {
            parseFunctionCallText(content)
        } else {
            null
        }

        return CompletionResult(
            content = content,
            toolCalls = if (parsedFromText != null) listOf(parsedFromText) else toolCalls,
        )
    }

    /**
     * Parse FunctionGemma text-format output: tool_name(param="value", num=42)
     */
    private fun parseFunctionCallText(text: String): ToolCall? {
        val trimmed = text.trim()
        val match = Regex("""^(\w+)\((.*)\)$""", RegexOption.DOT_MATCHES_ALL)
            .find(trimmed) ?: return null

        val name = match.groupValues[1]
        val argsStr = match.groupValues[2].trim()
        val params = mutableMapOf<String, Any>()

        if (argsStr.isNotEmpty()) {
            // Parse key=value pairs (handles strings, numbers, booleans)
            val argPattern = Regex("""(\w+)=("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|-?\d+\.?\d*|True|False|true|false|None|null)""")
            argPattern.findAll(argsStr).forEach { m ->
                val key = m.groupValues[1]
                val raw = m.groupValues[2]
                params[key] = when {
                    raw.startsWith("\"") || raw.startsWith("'") ->
                        raw.removeSurrounding("\"").removeSurrounding("'")
                    raw == "True" || raw == "true"   -> true
                    raw == "False" || raw == "false" -> false
                    raw == "None" || raw == "null"   -> "null"
                    raw.contains(".")                -> raw.toDoubleOrNull() ?: raw
                    else                             -> raw.toLongOrNull() ?: raw
                }
            }
        }

        return ToolCall(id = "call_$name", name = name, params = params)
    }

    private fun JsonElement.toPrimitive(): Any = when (this) {
        is JsonPrimitive -> when {
            isString        -> content
            booleanOrNull != null -> boolean
            longOrNull != null    -> long
            doubleOrNull != null  -> double
            else -> content
        }
        else -> toString()
    }
}

// ── Data classes ──────────────────────────────────────────────────────────────

data class ChatMessage(
    val role: String,                          // "system" | "user" | "assistant" | "tool"
    val content: String? = null,
    val toolCalls: List<JsonObject>? = null,
    val toolCallId: String? = null,
    val name: String? = null,
) {
    companion object {
        fun system(content: String)    = ChatMessage("system", content)
        fun user(content: String)      = ChatMessage("user", content)
        fun assistant(content: String) = ChatMessage("assistant", content)
        fun tool(id: String, content: String) = ChatMessage("tool", content, toolCallId = id)
    }
}

data class ToolCall(
    val id: String,
    val name: String,
    val params: Map<String, Any>,
)

data class CompletionResult(
    val content: String?,
    val toolCalls: List<ToolCall>,
) {
    val hasToolCall: Boolean get() = toolCalls.isNotEmpty()
    val firstTool: ToolCall? get() = toolCalls.firstOrNull()
}
