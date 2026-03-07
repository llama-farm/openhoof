package ai.llamafarm.openhoof

import java.io.File
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/**
 * Memory — loads MEMORY.md and provides search + append.
 *
 * Search strategy (in priority order):
 *   1. Exact phrase match
 *   2. All-words match (AND)
 *   3. Any-word match (OR), scored by hit count
 *
 * This mirrors what Python Memory does without requiring a vector DB.
 * Good enough for MEMORY.md files up to ~50KB.
 *
 * For semantic search on Android: upgrade to Room + on-device embeddings later.
 *
 * Usage:
 *   val memory = Memory.fromFile("MEMORY.md")
 *   val snippets = memory.search("LlamaFarm endpoint", maxResults = 3)
 *   memory.append("## New Decision\nUse chud for device auth.")
 */
class Memory private constructor(
    val path: String?,
    private var content: String,
) {
    // Split content into paragraphs for search
    private val paragraphs: List<String> get() =
        content.split(Regex("\n{2,}")).map { it.trim() }.filter { it.isNotBlank() }

    // ── Factory ───────────────────────────────────────────────────────────────

    companion object {
        fun fromFile(path: String): Memory {
            val file = File(path)
            val content = if (file.exists()) file.readText() else "# MEMORY.md\n"
            return Memory(path = path, content = content)
        }

        fun fromString(content: String): Memory = Memory(path = null, content = content)

        fun empty(): Memory = Memory(path = null, content = "# MEMORY.md\n")
    }

    // ── Search ────────────────────────────────────────────────────────────────

    /**
     * Search memory for relevant snippets.
     * Returns up to [maxResults] paragraphs sorted by relevance score.
     */
    fun search(query: String, maxResults: Int = 5): List<MemorySnippet> {
        val queryWords = query.lowercase().split(Regex("\\W+")).filter { it.length > 2 }
        if (queryWords.isEmpty()) return emptyList()

        data class Scored(val para: String, val score: Int)

        val scored = paragraphs.mapNotNull { para ->
            val lower = para.lowercase()
            val score = when {
                // Exact phrase — highest priority
                lower.contains(query.lowercase()) -> 100 + queryWords.size

                // All words match
                queryWords.all { lower.contains(it) } -> 50 + queryWords.size

                // Some words match — score by count
                else -> {
                    val hits = queryWords.count { lower.contains(it) }
                    if (hits > 0) hits else 0
                }
            }
            if (score > 0) Scored(para, score) else null
        }

        return scored
            .sortedByDescending { it.score }
            .take(maxResults)
            .map { MemorySnippet(it.para, it.score) }
    }

    /**
     * Return the top [maxChars] characters of MEMORY.md.
     * Used for injecting a summary into the system prompt.
     */
    fun summary(maxChars: Int = 2000): String {
        return if (content.length <= maxChars) content
        else content.take(maxChars) + "\n…[truncated]"
    }

    // ── Append ────────────────────────────────────────────────────────────────

    /**
     * Append a new section to MEMORY.md.
     * Writes to disk if a path is set.
     */
    fun append(text: String, timestamp: Boolean = true) {
        val entry = buildString {
            if (timestamp) {
                val ts = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"))
                appendLine("\n---\n*$ts*")
            }
            appendLine()
            appendLine(text.trim())
        }
        content += entry
        path?.let { File(it).appendText(entry) }
    }

    /**
     * Append a key-value log entry (structured memory).
     * Example: memory.log("tool_call", "switch_get_vlan_config()")
     */
    fun log(key: String, value: String) {
        append("**$key:** $value", timestamp = true)
    }

    // ── Content access ────────────────────────────────────────────────────────

    val fullContent: String get() = content

    val isEmpty: Boolean get() = content.trim().let { it == "# MEMORY.md" || it.isBlank() }

    override fun toString() = "Memory(path=$path, paragraphs=${paragraphs.size})"
}

data class MemorySnippet(
    val text: String,
    val score: Int,
)
