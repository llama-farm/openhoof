plugins {
    kotlin("jvm") version "2.0.21"
    kotlin("plugin.serialization") version "2.0.21"
}

group = "ai.llamafarm"
version = "0.1.0"

repositories {
    mavenCentral()
    google()
}

dependencies {
    // HTTP (for RemoteCompletionProvider — optional, LlamaFarm fallback)
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // JSON
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.8.0")

    // NOTE: On-device inference (LocalCompletionProvider) requires an inference engine.
    // Add ONE of the following to your app module (not this library):
    //
    //   Android (ONNX Runtime GenAI — FunctionGemma, Phi-3, Llama 3.2):
    //     implementation("com.microsoft.onnxruntime:onnxruntime-genai-android:0.5.3")
    //
    //   Desktop/JVM (llama.cpp JNI):
    //     implementation("de.kherud:llama:3.4.1")

    // Test
    testImplementation(kotlin("test"))
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.0")
}

kotlin {
    jvmToolchain(17)
}

tasks.test {
    useJUnitPlatform()
}
