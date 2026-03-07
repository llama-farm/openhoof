package ai.llamafarm.openhoof

import kotlinx.serialization.json.JsonObject

/**
 * CompletionProvider — interface for model inference.
 *
 * Two implementations:
 *   LocalCompletionProvider  — on-device via ONNX Runtime GenAI (primary, no network)
 *   RemoteCompletionProvider — HTTP to LlamaFarm/OpenAI (fallback when network available)
 *
 * The Agent accepts any CompletionProvider — it doesn't care where inference runs.
 */
interface CompletionProvider {
    val model: String

    suspend fun complete(
        messages: List<ChatMessage>,
        tools: List<JsonObject>? = null,
        stripToolDescriptions: Boolean = true,
    ): CompletionResult

    suspend fun isAvailable(): Boolean
}
