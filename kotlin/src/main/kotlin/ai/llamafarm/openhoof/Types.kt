package ai.llamafarm.openhoof

import kotlinx.serialization.json.JsonObject

// ── Chat messages ─────────────────────────────────────────────────────────────

data class ChatMessage(
    val role: String,
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

// ── Tool calls ────────────────────────────────────────────────────────────────

data class ToolCall(
    val id: String,
    val name: String,
    val params: Map<String, Any>,
)

// ── Completion results ────────────────────────────────────────────────────────

data class CompletionResult(
    val content: String?,
    val toolCalls: List<ToolCall>,
) {
    val hasToolCall: Boolean get() = toolCalls.isNotEmpty()
    val firstTool: ToolCall? get() = toolCalls.firstOrNull()
}
