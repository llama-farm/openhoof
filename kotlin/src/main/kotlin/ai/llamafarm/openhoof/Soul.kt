package ai.llamafarm.openhoof

import java.io.File

/**
 * Soul — loads SOUL.md and generates the agent system prompt.
 *
 * Keeps the system prompt minimal (target: ~200 tokens).
 * Full SOUL.md is referenced but only the first section is used
 * as the live system prompt — the rest is available as context on demand.
 *
 * Usage:
 *   val soul = Soul.fromFile("SOUL.md")
 *   val soul = Soul.fromString("You are Ace, an autonomous drone agent...")
 *   println(soul.systemPrompt)   // lean prompt for inference
 *   println(soul.fullContent)    // complete SOUL.md
 */
class Soul private constructor(
    val name: String,
    val emoji: String,
    val fullContent: String,
    val systemPrompt: String,
) {
    companion object {
        private val NAME_PATTERN  = Regex("""(?:^|\n)#\s+SOUL\.md\s*[-–—]\s*(.+)""")
        private val IDENT_PATTERN = Regex("""(?i)\*\*Name:\*\*\s*(.+)""")
        private val EMOJI_PATTERN = Regex("""(?i)\*\*Emoji:\*\*\s*(\S+)""")

        fun fromFile(path: String): Soul = fromString(File(path).readText())

        fun fromString(content: String): Soul {
            val name  = IDENT_PATTERN.find(content)?.groupValues?.get(1)?.trim()
                ?: NAME_PATTERN.find(content)?.groupValues?.get(1)?.trim()
                ?: "Agent"
            val emoji = EMOJI_PATTERN.find(content)?.groupValues?.get(1)?.trim() ?: "🤖"

            // Build lean system prompt from SOUL.md
            // Use content up to the first "##" section (the identity block)
            val systemPrompt = buildSystemPrompt(name, emoji, content)

            return Soul(name = name, emoji = emoji, fullContent = content, systemPrompt = systemPrompt)
        }

        /** Minimal inline soul — useful for testing or embedded agents. */
        fun inline(name: String, emoji: String = "🤖", mission: String = ""): Soul {
            val content = "# SOUL.md — $name\n\n**Name:** $name\n**Emoji:** $emoji\n\n## Mission\n$mission"
            return Soul(
                name = name,
                emoji = emoji,
                fullContent = content,
                systemPrompt = buildLeanPrompt(name, emoji, mission),
            )
        }

        // ── Private ───────────────────────────────────────────────────────────

        private fun buildSystemPrompt(name: String, emoji: String, content: String): String {
            // Extract mission line if present
            val missionMatch = Regex("""(?i)##\s+Mission\s*\n+(.*?)(?:\n\n|\n##|$)""", RegexOption.DOT_MATCHES_ALL)
                .find(content)
            val mission = missionMatch?.groupValues?.get(1)?.trim()
                ?.lines()?.take(3)?.joinToString(" ")
                ?: ""

            return buildLeanPrompt(name, emoji, mission)
        }

        private fun buildLeanPrompt(name: String, emoji: String, mission: String): String {
            val lines = mutableListOf(
                "You are $name $emoji.",
            )
            if (mission.isNotBlank()) {
                lines.add(mission.take(300))
            }
            lines.add("Respond to requests by calling the appropriate tool. Return a single tool call only.")
            return lines.joinToString("\n")
        }
    }

    override fun toString() = "Soul(name=$name, emoji=$emoji)"
}
