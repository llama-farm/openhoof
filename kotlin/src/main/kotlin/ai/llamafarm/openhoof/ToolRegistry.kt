package ai.llamafarm.openhoof

import kotlinx.serialization.json.*

/**
 * ToolRegistry — registers tools and dispatches calls.
 *
 * A tool is:
 *   - A schema (OpenAI function-calling format JSON)
 *   - A handler (suspend function that takes params, returns Any?)
 *
 * Supports:
 *   - Manual registration (register { ... })
 *   - Bulk registration from JSON schema list
 *   - OpenHoof Python-compatible schema format
 *
 * Usage:
 *   val registry = ToolRegistry()
 *
 *   registry.register(
 *     name = "get_wan_status",
 *     description = "Get WAN connection status",
 *     parameters = mapOf("type" to "object", "properties" to mapOf<String, Any>()),
 *   ) { _ ->
 *     mapOf("status" to "connected", "ip" to "1.2.3.4")
 *   }
 *
 *   val result = registry.execute("get_wan_status", emptyMap())
 */
class ToolRegistry {

    private val tools = mutableMapOf<String, RegisteredTool>()

    // ── Registration ──────────────────────────────────────────────────────────

    /** Register a tool with explicit schema components. */
    fun register(
        name: String,
        description: String = "",
        parameters: Map<String, Any> = emptyMap(),
        handler: suspend (params: Map<String, Any>) -> Any?,
    ) {
        val schema = buildJsonObject {
            put("type", "function")
            putJsonObject("function") {
                put("name", name)
                if (description.isNotBlank()) put("description", description)
                put("parameters", mapToJson(parameters))
            }
        }
        tools[name] = RegisteredTool(name = name, schema = schema, handler = handler)
    }

    /** Register a tool directly from an OpenAI-format JSON schema + handler. */
    fun register(schema: JsonObject, handler: suspend (params: Map<String, Any>) -> Any?) {
        val fn = schema["function"]?.jsonObject ?: schema
        val name = fn["name"]?.jsonPrimitive?.content
            ?: throw IllegalArgumentException("Tool schema missing 'name'")
        val normalized = if (schema.containsKey("function")) schema else buildJsonObject {
            put("type", "function")
            put("function", schema)
        }
        tools[name] = RegisteredTool(name = name, schema = normalized, handler = handler)
    }

    /** Register multiple tools from a JSON array of OpenAI-format schemas. */
    fun registerAll(schemas: JsonArray, handler: (name: String) -> (suspend (Map<String, Any>) -> Any?)) {
        schemas.forEach { element ->
            val obj = element.jsonObject
            val fn = obj["function"]?.jsonObject ?: obj
            val name = fn["name"]?.jsonPrimitive?.content ?: return@forEach
            register(obj) { params -> handler(name)(params) }
        }
    }

    // ── Execution ─────────────────────────────────────────────────────────────

    /** Execute a tool call. Throws [UnknownToolException] if not registered. */
    suspend fun execute(name: String, params: Map<String, Any>): Any? {
        val tool = tools[name] ?: throw UnknownToolException(name, tools.keys.toList())
        return tool.handler(params)
    }

    /** Execute, returning a Result wrapper instead of throwing. */
    suspend fun executeSafe(name: String, params: Map<String, Any>): ToolResult {
        return try {
            ToolResult.Success(name, execute(name, params))
        } catch (e: UnknownToolException) {
            ToolResult.UnknownTool(name, tools.keys.toList())
        } catch (e: Exception) {
            ToolResult.Error(name, e.message ?: e.toString())
        }
    }

    // ── Schema access ─────────────────────────────────────────────────────────

    /** All registered tool schemas as a JsonArray (for passing to ModelClient). */
    val schemas: JsonArray get() = buildJsonArray {
        tools.values.forEach { add(it.schema) }
    }

    /** Names of all registered tools. */
    val names: Set<String> get() = tools.keys.toSet()

    fun contains(name: String): Boolean = name in tools

    val size: Int get() = tools.size

    // ── Helpers ───────────────────────────────────────────────────────────────

    private fun mapToJson(map: Map<String, Any>): JsonElement = when (map["type"]) {
        "object" -> buildJsonObject {
            put("type", "object")
            @Suppress("UNCHECKED_CAST")
            (map["properties"] as? Map<String, Any>)?.let { props ->
                putJsonObject("properties") {
                    props.forEach { (k, v) ->
                        put(k, if (v is Map<*, *>) {
                            @Suppress("UNCHECKED_CAST")
                            mapToJson(v as Map<String, Any>)
                        } else JsonPrimitive(v.toString()))
                    }
                }
            }
            (map["required"] as? List<*>)?.let { req ->
                putJsonArray("required") { req.forEach { add(it.toString()) } }
            }
        }
        else -> buildJsonObject {
            map.forEach { (k, v) ->
                when (v) {
                    is String  -> put(k, v)
                    is Number  -> put(k, v.toDouble())
                    is Boolean -> put(k, v)
                    is List<*> -> putJsonArray(k) { v.forEach { add(it.toString()) } }
                    else       -> put(k, v.toString())
                }
            }
        }
    }
}

// ── Supporting types ──────────────────────────────────────────────────────────

private data class RegisteredTool(
    val name: String,
    val schema: JsonObject,
    val handler: suspend (Map<String, Any>) -> Any?,
)

sealed class ToolResult {
    abstract val toolName: String

    data class Success(override val toolName: String, val value: Any?) : ToolResult()
    data class Error(override val toolName: String, val message: String) : ToolResult()
    data class UnknownTool(override val toolName: String, val available: List<String>) : ToolResult()
}

class UnknownToolException(name: String, available: List<String>) :
    Exception("Unknown tool '$name'. Available: ${available.joinToString()}")
