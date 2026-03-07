package ai.llamafarm.openhoof

import ai.llamafarm.openhoof.ToolParser.toPrimitive
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * RemoteCompletionProvider — HTTP to LlamaFarm Universal Runtime or any OpenAI-compatible server.
 *
 * Use this when a LlamaFarm server is available on the same network (laptop/server).
 * For fully offline operation, use LocalCompletionProvider instead.
 * For DDIL (offline first, sync when available), use HybridCompletionProvider.
 *
 * ft: alias resolution:
 *   "ft:da674646" → ~/.llamafarm/models/llm/da674646/gguf/model-q8_0.gguf
 *   Allows referencing fine-tuned models by job ID.
 */
class RemoteCompletionProvider(
    val endpoint: String = "http://localhost:11540/v1",
    override val model: String = "unsloth/functiongemma-270m-it-GGUF",
    val temperature: Float = 0.0f,
    val maxTokens: Int = 64,
) : CompletionProvider {

    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = false }

    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

    private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()

    // ── CompletionProvider ────────────────────────────────────────────────────

    override suspend fun complete(
        messages: List<ChatMessage>,
        tools: List<JsonObject>?,
        stripToolDescriptions: Boolean,
    ): CompletionResult = withContext(Dispatchers.IO) {

        val resolvedModel = resolveModel(model)
        val slimTools = if (!tools.isNullOrEmpty() && stripToolDescriptions) {
            ToolParser.slimTools(tools)
        } else tools

        val payload = buildJsonObject {
            put("model", resolvedModel)
            put("temperature", temperature)
            put("max_tokens", maxTokens)
            putJsonArray("messages") {
                messages.forEach { msg ->
                    addJsonObject {
                        put("role", msg.role)
                        if (msg.content != null) put("content", msg.content)
                        else put("content", JsonNull)
                        msg.toolCalls?.let { tc ->
                            putJsonArray("tool_calls") { tc.forEach { add(it) } }
                        }
                        msg.toolCallId?.let { put("tool_call_id", it) }
                        msg.name?.let { put("name", it) }
                    }
                }
            }
            if (!slimTools.isNullOrEmpty()) {
                putJsonArray("tools") { slimTools.forEach { add(it) } }
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
        if (!response.isSuccessful) throw RuntimeException("HTTP ${response.code}: $responseBody")

        parseCompletion(json.parseToJsonElement(responseBody).jsonObject)
    }

    override suspend fun isAvailable(): Boolean = withContext(Dispatchers.IO) {
        try {
            val healthUrl = endpoint.removeSuffix("/v1")
            http.newCall(Request.Builder().url("$healthUrl/health").get().build())
                .execute().isSuccessful
        } catch (e: Exception) {
            false
        }
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    private fun resolveModel(model: String): String {
        if (!model.startsWith("ft:")) return model
        val jobId = model.removePrefix("ft:")
        val home = System.getProperty("user.home") ?: return model
        val gguf = File("$home/.llamafarm/models/llm/$jobId/gguf/model-q8_0.gguf")
        return if (gguf.exists()) gguf.absolutePath else model
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
            } catch (e: Exception) { emptyMap() }
            ToolCall(
                id = obj["id"]?.jsonPrimitive?.contentOrNull ?: "call_$name",
                name = name,
                params = args,
            )
        } ?: emptyList()

        val parsedFromText = if (toolCalls.isEmpty() && content != null)
            ToolParser.parseFunctionCallText(content) else null

        return CompletionResult(
            content = content,
            toolCalls = if (parsedFromText != null) listOf(parsedFromText) else toolCalls,
        )
    }
}
