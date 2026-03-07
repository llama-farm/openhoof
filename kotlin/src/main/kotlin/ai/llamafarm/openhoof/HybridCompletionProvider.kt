package ai.llamafarm.openhoof

import kotlinx.serialization.json.JsonObject

/**
 * HybridCompletionProvider — local first, remote fallback.
 *
 * This is the right default for a phone agent running in DDIL environments:
 *   1. Try LocalCompletionProvider (always fast, always available)
 *   2. If local model is unavailable, fall back to RemoteCompletionProvider
 *
 * The inverse is also supported (remote-first for accuracy, local as offline fallback).
 *
 * Usage:
 *   val provider = HybridCompletionProvider(
 *       primary   = LocalCompletionProvider(modelPath = ".../functiongemma-270m"),
 *       secondary = RemoteCompletionProvider(endpoint  = "http://192.168.1.5:11540/v1"),
 *   )
 *   val agent = Agent.build { provider(provider) }
 */
class HybridCompletionProvider(
    val primary: CompletionProvider,
    val secondary: CompletionProvider? = null,
) : CompletionProvider {

    override val model: String get() = primary.model

    override suspend fun complete(
        messages: List<ChatMessage>,
        tools: List<JsonObject>?,
        stripToolDescriptions: Boolean,
    ): CompletionResult {
        if (primary.isAvailable()) {
            return try {
                primary.complete(messages, tools, stripToolDescriptions)
            } catch (e: Exception) {
                secondary?.complete(messages, tools, stripToolDescriptions)
                    ?: throw e
            }
        }
        return secondary?.complete(messages, tools, stripToolDescriptions)
            ?: throw IllegalStateException("No provider available")
    }

    override suspend fun isAvailable(): Boolean =
        primary.isAvailable() || secondary?.isAvailable() == true
}
