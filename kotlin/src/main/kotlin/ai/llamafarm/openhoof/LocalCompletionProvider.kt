package ai.llamafarm.openhoof

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*

/**
 * LocalCompletionProvider — on-device inference. No network. No LlamaFarm.
 *
 * Takes a LocalInferenceEngine — the platform-specific piece that actually
 * runs the model. The core library stays free of ONNX/llama.cpp dependencies.
 *
 * You provide the engine; this class handles the agent protocol:
 *   - Builds the Gemma prompt from chat messages + tool list
 *   - Calls engine.generate(prompt)
 *   - Parses the output as a function call: tool_name(param=value)
 *
 * ── Android setup (ONNX Runtime GenAI) ───────────────────────────────────
 *
 *   // app/build.gradle
 *   implementation("com.microsoft.onnxruntime:onnxruntime-genai-android:0.5.3")
 *
 *   val engine = OnnxInferenceEngine(
 *       modelPath = context.filesDir.absolutePath + "/models/functiongemma-270m"
 *   )
 *   val provider = LocalCompletionProvider(engine = engine)
 *
 * ── JVM/Desktop setup (llama.cpp) ────────────────────────────────────────
 *
 *   // build.gradle
 *   implementation("de.kherud:llama:3.4.1")
 *
 *   val engine = LlamaCppInferenceEngine(
 *       modelPath = "/home/user/.openhoof/models/functiongemma-270m.gguf"
 *   )
 *   val provider = LocalCompletionProvider(engine = engine)
 *
 * ── Model files ───────────────────────────────────────────────────────────
 *
 *   FunctionGemma-270M ONNX (int4, ~150MB):
 *     llamafarm export --model unsloth/functiongemma-270m-it --format onnx --quant int4
 *
 *   Llama 3.2-1B ONNX (int4, ~700MB):
 *     llamafarm export --model meta-llama/Llama-3.2-1B-Instruct --format onnx --quant int4
 */
class LocalCompletionProvider(
    val engine: LocalInferenceEngine,
    override val model: String = engine.modelName,
    val maxNewTokens: Int = 64,
    val temperature: Float = 0.0f,
) : CompletionProvider {

    override suspend fun complete(
        messages: List<ChatMessage>,
        tools: List<JsonObject>?,
        stripToolDescriptions: Boolean,
    ): CompletionResult = withContext(Dispatchers.Default) {

        val slimTools = if (!tools.isNullOrEmpty() && stripToolDescriptions) {
            ToolParser.slimTools(tools)
        } else tools

        val prompt = buildGemmaPrompt(messages, slimTools)
        val rawOutput = engine.generate(prompt, maxNewTokens, temperature)

        val toolCall = ToolParser.parseFunctionCallText(rawOutput)

        CompletionResult(
            content = rawOutput,
            toolCalls = if (toolCall != null) listOf(toolCall) else emptyList(),
        )
    }

    override suspend fun isAvailable(): Boolean = engine.isAvailable()

    // ── Prompt formatting ─────────────────────────────────────────────────────

    /**
     * Gemma chat template — matches FunctionGemma SFT training format exactly.
     *
     * <bos><start_of_turn>user
     * {system}\n\nAvailable tools: tool_a, tool_b\n\n{user_message}<end_of_turn>
     * <start_of_turn>model
     */
    private fun buildGemmaPrompt(messages: List<ChatMessage>, tools: List<JsonObject>?): String {
        val system = messages.firstOrNull { it.role == "system" }?.content ?: ""
        val userMsg = messages.lastOrNull { it.role == "user" }?.content ?: ""

        val toolNames = tools?.mapNotNull { t ->
            t["function"]?.jsonObject?.get("name")?.jsonPrimitive?.contentOrNull
        } ?: emptyList()

        return buildString {
            append("<bos>")
            append("<start_of_turn>user\n")
            if (system.isNotBlank()) {
                append(system)
                append("\n\n")
            }
            if (toolNames.isNotEmpty()) {
                append("Available tools: ")
                append(toolNames.joinToString(", "))
                append("\n\n")
            }
            append(userMsg)
            append("<end_of_turn>\n")
            append("<start_of_turn>model\n")
        }
    }
}

// ── LocalInferenceEngine interface ────────────────────────────────────────────

/**
 * Platform-specific inference engine interface.
 *
 * Implement this for your platform (ONNX Runtime on Android, llama.cpp on desktop).
 * The implementation loads the model, handles tokenization, and runs generation.
 */
interface LocalInferenceEngine {
    val modelName: String
    fun generate(prompt: String, maxNewTokens: Int = 64, temperature: Float = 0.0f): String
    fun isAvailable(): Boolean
    fun unload() {}
}

// ── Reference implementations ─────────────────────────────────────────────────

/**
 * OnnxInferenceEngine — Android on-device inference via ONNX Runtime GenAI.
 *
 * Requires: implementation("com.microsoft.onnxruntime:onnxruntime-genai-android:0.5.3")
 *
 * Model directory must contain ONNX model files exported via:
 *   llamafarm export --model unsloth/functiongemma-270m-it --format onnx --quant int4
 *
 * Or download pre-exported from HuggingFace:
 *   https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-onnx-cpu
 */
class OnnxInferenceEngine(val modelPath: String) : LocalInferenceEngine {
    override val modelName: String = modelPath.substringAfterLast("/")

    // Loaded lazily — doesn't hold memory until first call
    private var onnxModel: Any? = null
    private var tokenizer: Any? = null

    override fun isAvailable(): Boolean = java.io.File(modelPath).exists()

    override fun generate(prompt: String, maxNewTokens: Int, temperature: Float): String {
        ensureLoaded()

        // Use reflection so this file compiles without ONNX on the classpath.
        // On Android with onnxruntime-genai-android added, this resolves at runtime.
        val model     = onnxModel!!
        val tok       = tokenizer!!
        val tokClass  = tok.javaClass
        val modelClass = model.javaClass

        val sequences  = tokClass.getMethod("encode", String::class.java).invoke(tok, prompt)
        val paramsClass = Class.forName("ai.onnxruntime.genai.GeneratorParams")
        val params     = paramsClass.getConstructor(modelClass).newInstance(model)

        paramsClass.getMethod("setSearchOption", String::class.java, Double::class.java).let { m ->
            val seqLen = sequences.javaClass.getMethod("size").invoke(sequences) as Int
            m.invoke(params, "max_length", (seqLen + maxNewTokens).toDouble())
            m.invoke(params, "temperature", temperature.toDouble())
        }
        paramsClass.getMethod("setInput", sequences.javaClass).invoke(params, sequences)

        val generatorClass = Class.forName("ai.onnxruntime.genai.Generator")
        val generator = generatorClass.getConstructor(modelClass, paramsClass)
            .newInstance(model, params)

        val sb = StringBuilder()
        val isDone = generatorClass.getMethod("isDone")
        val computeLogits = generatorClass.getMethod("computeLogits")
        val generateNextToken = generatorClass.getMethod("generateNextToken")
        val getSequence = generatorClass.getMethod("getSequence", Int::class.java)
        val decode = tokClass.getMethod("decode", IntArray::class.java)

        while (!(isDone.invoke(generator) as Boolean)) {
            computeLogits.invoke(generator)
            generateNextToken.invoke(generator)
            val seq = getSequence.invoke(generator, 0) as IntArray
            val decoded = decode.invoke(tok, intArrayOf(seq.last())) as String
            sb.append(decoded)
        }

        (generator as AutoCloseable).close()
        (sequences as AutoCloseable).close()
        (params as AutoCloseable).close()

        return sb.toString().trim()
    }

    override fun unload() {
        (tokenizer as? AutoCloseable)?.close()
        (onnxModel as? AutoCloseable)?.close()
        tokenizer = null; onnxModel = null
    }

    private fun ensureLoaded() {
        if (onnxModel != null) return
        val modelClass = Class.forName("ai.onnxruntime.genai.Model")
        val tokClass   = Class.forName("ai.onnxruntime.genai.Tokenizer")
        onnxModel  = modelClass.getConstructor(String::class.java).newInstance(modelPath)
        tokenizer  = tokClass.getConstructor(modelClass).newInstance(onnxModel)
    }
}
