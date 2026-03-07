package ai.llamafarm.openhoof

import kotlinx.serialization.json.*

/**
 * ToolParser — shared parsing utilities for all CompletionProviders.
 *
 * Both local and remote providers produce the same tool call format.
 * FunctionGemma outputs text: tool_name(param="value", num=42)
 * This parser handles that format as well as standard JSON tool_calls.
 */
internal object ToolParser {

    /**
     * Parse FunctionGemma text-format output.
     * e.g. switch_get_vlan_config()
     *      router_add_static_route(ip_network="10.0.0.0/8", gateway="172.16.0.1")
     */
    fun parseFunctionCallText(text: String): ToolCall? {
        val trimmed = text.trim().lines().first().trim() // take first line only
        val match = Regex("""^(\w+)\((.*)\)$""", RegexOption.DOT_MATCHES_ALL)
            .find(trimmed) ?: return null

        val name = match.groupValues[1]
        val argsStr = match.groupValues[2].trim()
        val params = mutableMapOf<String, Any>()

        if (argsStr.isNotEmpty()) {
            val argPattern = Regex("""(\w+)=("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|-?\d+\.?\d*|True|False|true|false|None|null)""")
            argPattern.findAll(argsStr).forEach { m ->
                val key = m.groupValues[1]
                val raw = m.groupValues[2]
                params[key] = when {
                    raw.startsWith("\"") || raw.startsWith("'") ->
                        raw.removeSurrounding("\"").removeSurrounding("'")
                    raw == "True"  || raw == "true"  -> true
                    raw == "False" || raw == "false" -> false
                    raw == "None"  || raw == "null"  -> "null"
                    raw.contains(".")                -> raw.toDoubleOrNull() ?: raw
                    else                             -> raw.toLongOrNull() ?: raw
                }
            }
        }

        return ToolCall(id = "call_$name", name = name, params = params)
    }

    /**
     * Strip tool descriptions before sending to FunctionGemma 270M.
     * The model learns routing from SFT data, not from reading descriptions at inference.
     * Keeps: name, parameter types, enums. Drops: description, when_to_use.
     */
    fun slimTools(tools: List<JsonObject>): List<JsonObject> = tools.map { tool ->
        val fn = tool["function"]?.jsonObject ?: return@map tool
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
        buildJsonObject {
            put("type", JsonPrimitive("function"))
            put("function", slimFn)
        }
    }

    fun JsonElement.toPrimitive(): Any = when (this) {
        is JsonPrimitive -> when {
            isString              -> content
            booleanOrNull != null -> boolean
            longOrNull != null    -> long
            doubleOrNull != null  -> double
            else                  -> content
        }
        else -> toString()
    }
}
