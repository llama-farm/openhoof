package ai.llamafarm.openhoof

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.*
import kotlin.test.*

/**
 * Unit tests for the core OpenHoof Kotlin components.
 * These run without a live LlamaFarm instance.
 */
class AgentTest {

    // ── Soul ──────────────────────────────────────────────────────────────────

    @Test
    fun `Soul inline creates minimal system prompt`() {
        val soul = Soul.inline("Ace", "🚁", "Fly drone missions autonomously.")
        assertEquals("Ace", soul.name)
        assertEquals("🚁", soul.emoji)
        assertTrue(soul.systemPrompt.contains("Ace"))
        assertTrue(soul.systemPrompt.contains("tool"))
        println("System prompt (${soul.systemPrompt.length} chars):\n${soul.systemPrompt}")
    }

    @Test
    fun `Soul fromString parses name and emoji`() {
        val md = """
            # SOUL.md — Drone Agent
            
            **Name:** Ace
            **Emoji:** 🚁
            
            ## Mission
            Fly autonomous drone missions. Handle DDIL. Capture training data.
        """.trimIndent()
        val soul = Soul.fromString(md)
        assertEquals("Ace", soul.name)
        assertEquals("🚁", soul.emoji)
        assertTrue(soul.systemPrompt.contains("Ace"))
    }

    @Test
    fun `Soul system prompt is under 400 chars`() {
        val soul = Soul.inline("NetworkBot", "🌐", "Route network management commands to the right tool.")
        assertTrue(soul.systemPrompt.length < 400,
            "System prompt too long: ${soul.systemPrompt.length} chars")
    }

    // ── Memory ────────────────────────────────────────────────────────────────

    @Test
    fun `Memory search finds exact match`() {
        val memory = Memory.fromString("""
            # MEMORY.md
            
            LlamaFarm endpoint is http://localhost:11540/v1.
            
            The router model is ft:da674646 with 87% accuracy.
            
            chud proxy handles all device authentication.
        """.trimIndent())

        val results = memory.search("LlamaFarm endpoint")
        assertTrue(results.isNotEmpty())
        assertTrue(results.first().text.contains("LlamaFarm"))
        assertTrue(results.first().score >= 100)
    }

    @Test
    fun `Memory search returns empty for no match`() {
        val memory = Memory.fromString("# MEMORY.md\n\nSome content about drones.")
        val results = memory.search("quantum physics reactor")
        assertTrue(results.isEmpty())
    }

    @Test
    fun `Memory append adds content`() {
        val memory = Memory.empty()
        assertTrue(memory.isEmpty)
        memory.append("## Test Decision\nUse OkHttp for HTTP calls.")
        assertFalse(memory.isEmpty)
        assertTrue(memory.fullContent.contains("OkHttp"))
    }

    @Test
    fun `Memory summary truncates at maxChars`() {
        val long = "x".repeat(5000)
        val memory = Memory.fromString("# MEMORY.md\n\n$long")
        val summary = memory.summary(maxChars = 200)
        assertTrue(summary.length <= 230) // maxChars + header + ellipsis slack
        assertTrue(summary.contains("truncated"))
    }

    // ── ToolRegistry ──────────────────────────────────────────────────────────

    @Test
    fun `ToolRegistry registers and executes tool`() = runTest {
        val registry = ToolRegistry()
        registry.register(
            name = "get_time",
            description = "Get current time",
            parameters = mapOf(
                "type" to "object",
                "properties" to emptyMap<String, Any>(),
            ),
        ) { _ -> "12:00:00" }

        assertTrue(registry.contains("get_time"))
        assertEquals(1, registry.size)

        val result = registry.execute("get_time", emptyMap())
        assertEquals("12:00:00", result)
    }

    @Test
    fun `ToolRegistry executeSafe returns UnknownTool for missing tool`() = runTest {
        val registry = ToolRegistry()
        val result = registry.executeSafe("nonexistent_tool", emptyMap())
        assertTrue(result is ToolResult.UnknownTool)
    }

    @Test
    fun `ToolRegistry executeSafe wraps handler exceptions`() = runTest {
        val registry = ToolRegistry()
        registry.register("bad_tool", handler = { _ -> throw RuntimeException("device offline") })
        val result = registry.executeSafe("bad_tool", emptyMap())
        assertTrue(result is ToolResult.Error)
        assertTrue((result as ToolResult.Error).message.contains("device offline"))
    }

    @Test
    fun `ToolRegistry schemas produces valid JsonArray`() = runTest {
        val registry = ToolRegistry()
        registry.register("tool_a", "Does A", emptyMap()) { _ -> "a" }
        registry.register("tool_b", "Does B", emptyMap()) { _ -> "b" }

        val schemas = registry.schemas
        assertEquals(2, schemas.size)
        schemas.forEach { el ->
            val obj = el.jsonObject
            assertEquals("function", obj["type"]?.jsonPrimitive?.content)
            assertNotNull(obj["function"]?.jsonObject?.get("name"))
        }
    }

    // ── ModelClient text parser ───────────────────────────────────────────────

    @Test
    fun `ModelClient parses text format tool call`() {
        // Access parseFunctionCallText via a test-visible route
        // We use RouteResult / CompletionResult from a mock completion
        val client = ModelClient()

        // Test the text-format parser indirectly by building a mock completion response
        // that returns text-format output
        val parseMethod = client.javaClass.getDeclaredMethod(
            "parseFunctionCallText", String::class.java
        ).also { it.isAccessible = true }

        val result = parseMethod.invoke(client, "switch_get_vlan_config()") as ToolCall?
        assertNotNull(result)
        assertEquals("switch_get_vlan_config", result!!.name)
        assertTrue(result.params.isEmpty())
    }

    @Test
    fun `ModelClient parses text format with params`() {
        val client = ModelClient()
        val parseMethod = client.javaClass.getDeclaredMethod(
            "parseFunctionCallText", String::class.java
        ).also { it.isAccessible = true }

        val result = parseMethod.invoke(client, """router_add_static_route(ip_network="10.0.0.0/8", gateway="172.16.0.1")""") as ToolCall?
        assertNotNull(result)
        assertEquals("router_add_static_route", result!!.name)
        assertEquals("10.0.0.0/8", result.params["ip_network"])
        assertEquals("172.16.0.1", result.params["gateway"])
    }

    // ── Agent builder ─────────────────────────────────────────────────────────

    @Test
    fun `Agent builds with defaults`() {
        val agent = Agent.build {
            soul = Soul.inline("TestBot", "🧪")
        }
        assertEquals("TestBot", agent.soul.name)
        assertEquals(0, agent.registry.size)
    }

    @Test
    fun `Agent builds with tools`() = runTest {
        val registry = ToolRegistry()
        registry.register("ping", handler = { _ -> "pong" })

        val agent = Agent.build {
            soul = Soul.inline("TestBot")
            tools(registry)
        }

        assertEquals(1, agent.registry.size)
        assertTrue(agent.registry.contains("ping"))
    }
}
