package ai.llamafarm.openhoof

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.*
import kotlin.test.*

/**
 * Unit tests for OpenHoof Kotlin.
 * No live server or model required — all tests run offline.
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
        assertTrue(soul.systemPrompt.length < 400)
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
    }

    @Test
    fun `Memory search returns empty for no match`() {
        val memory = Memory.fromString("# MEMORY.md\n\nSome content about drones.")
        assertTrue(memory.search("quantum physics reactor").isEmpty())
    }

    @Test
    fun `Memory append adds content`() {
        val memory = Memory.empty()
        assertTrue(memory.isEmpty)
        memory.append("## Decision\nUse OkHttp for HTTP calls.")
        assertFalse(memory.isEmpty)
        assertTrue(memory.fullContent.contains("OkHttp"))
    }

    @Test
    fun `Memory summary truncates at maxChars`() {
        val memory = Memory.fromString("# MEMORY.md\n\n" + "x".repeat(5000))
        val summary = memory.summary(maxChars = 200)
        assertTrue(summary.length <= 230)
        assertTrue(summary.contains("truncated"))
    }

    // ── ToolRegistry ──────────────────────────────────────────────────────────

    @Test
    fun `ToolRegistry registers and executes tool`() = runTest {
        val registry = ToolRegistry()
        registry.register("get_time", "Get current time",
            mapOf("type" to "object", "properties" to emptyMap<String, Any>())
        ) { _ -> "12:00:00" }

        assertTrue(registry.contains("get_time"))
        assertEquals("12:00:00", registry.execute("get_time", emptyMap()))
    }

    @Test
    fun `ToolRegistry executeSafe returns UnknownTool for missing tool`() = runTest {
        val registry = ToolRegistry()
        assertTrue(registry.executeSafe("no_such_tool", emptyMap()) is ToolResult.UnknownTool)
    }

    @Test
    fun `ToolRegistry executeSafe wraps exceptions`() = runTest {
        val registry = ToolRegistry()
        registry.register("bad_tool") { _ -> throw RuntimeException("device offline") }
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

    // ── ToolParser ────────────────────────────────────────────────────────────

    @Test
    fun `ToolParser parses no-arg tool call`() {
        val result = ToolParser.parseFunctionCallText("switch_get_vlan_config()")
        assertNotNull(result)
        assertEquals("switch_get_vlan_config", result!!.name)
        assertTrue(result.params.isEmpty())
    }

    @Test
    fun `ToolParser parses tool call with string params`() {
        val result = ToolParser.parseFunctionCallText(
            """router_add_static_route(ip_network="10.0.0.0/8", gateway="172.16.0.1")"""
        )
        assertNotNull(result)
        assertEquals("router_add_static_route", result!!.name)
        assertEquals("10.0.0.0/8", result.params["ip_network"])
        assertEquals("172.16.0.1", result.params["gateway"])
    }

    @Test
    fun `ToolParser parses tool call with numeric params`() {
        val result = ToolParser.parseFunctionCallText("switch_set_port_pvid(port=3, vid=30)")
        assertNotNull(result)
        assertEquals("switch_set_port_pvid", result!!.name)
        assertEquals(3L, result.params["port"])
        assertEquals(30L, result.params["vid"])
    }

    @Test
    fun `ToolParser returns null for non-tool text`() {
        assertNull(ToolParser.parseFunctionCallText("I don't know what tool to use."))
        assertNull(ToolParser.parseFunctionCallText(""))
    }

    @Test
    fun `ToolParser slimTools strips descriptions`() {
        val tool = buildJsonObject {
            put("type", "function")
            putJsonObject("function") {
                put("name", "my_tool")
                put("description", "This is a long description that should be removed")
                putJsonObject("parameters") {
                    put("type", "object")
                    putJsonObject("properties") {
                        putJsonObject("vid") {
                            put("type", "integer")
                            put("description", "VLAN ID — also should be removed")
                        }
                    }
                }
            }
        }
        val slim = ToolParser.slimTools(listOf(tool)).first()
        val fn = slim["function"]!!.jsonObject
        assertNull(fn["description"])
        val prop = fn["parameters"]!!.jsonObject["properties"]!!.jsonObject["vid"]!!.jsonObject
        assertNull(prop["description"])
        assertEquals("integer", prop["type"]?.jsonPrimitive?.content)
    }

    // ── CompletionProvider interface ──────────────────────────────────────────

    @Test
    fun `HybridCompletionProvider falls back to secondary`() = runTest {
        // Primary always unavailable, secondary always returns a result
        val primary = object : CompletionProvider {
            override val model = "local"
            override suspend fun complete(messages: List<ChatMessage>, tools: List<JsonObject>?, stripToolDescriptions: Boolean) =
                throw IllegalStateException("not loaded")
            override suspend fun isAvailable() = false
        }
        val secondary = object : CompletionProvider {
            override val model = "remote"
            override suspend fun complete(messages: List<ChatMessage>, tools: List<JsonObject>?, stripToolDescriptions: Boolean) =
                CompletionResult(content = "router_reboot()", toolCalls = emptyList())
            override suspend fun isAvailable() = true
        }

        val hybrid = HybridCompletionProvider(primary = primary, secondary = secondary)
        val result = hybrid.complete(listOf(ChatMessage.user("reboot router")))
        assertEquals("router_reboot()", result.content)
    }

    // ── Agent builder ─────────────────────────────────────────────────────────

    @Test
    fun `Agent builds with local inference engine`() {
        val engine = OnnxInferenceEngine(modelPath = "/data/models/functiongemma")
        val agent = Agent.build {
            soul = Soul.inline("TestBot", "🧪")
            localModel(engine)
        }
        assertEquals("TestBot", agent.soul.name)
        assertTrue(agent.provider is LocalCompletionProvider)
    }

    @Test
    fun `Agent builds with remote endpoint`() {
        val agent = Agent.build {
            soul = Soul.inline("TestBot")
            remoteModel("http://192.168.1.5:11540/v1", "ft:da674646")
        }
        assertTrue(agent.provider is RemoteCompletionProvider)
        assertEquals("ft:da674646", agent.provider.model)
    }

    @Test
    fun `Agent routes query using mock provider`() = runTest {
        val mockProvider = object : CompletionProvider {
            override val model = "mock"
            override suspend fun complete(messages: List<ChatMessage>, tools: List<JsonObject>?, stripToolDescriptions: Boolean) =
                CompletionResult(
                    content = "switch_get_vlan_config()",
                    toolCalls = listOf(ToolCall("call_1", "switch_get_vlan_config", emptyMap()))
                )
            override suspend fun isAvailable() = true
        }

        val registry = ToolRegistry()
        registry.register("switch_get_vlan_config") { _ ->
            listOf(mapOf("vid" to 1, "name" to "default"), mapOf("vid" to 10, "name" to "mgmt"))
        }

        val agent = Agent.build {
            soul = Soul.inline("NetBot")
            provider = mockProvider
            tools(registry)
        }

        val result = agent.route("switch vlans")
        assertEquals("switch_get_vlan_config", result.toolName)
        assertTrue(result.succeeded)
        assertTrue((result.value() as List<*>).size == 2)
    }
}
