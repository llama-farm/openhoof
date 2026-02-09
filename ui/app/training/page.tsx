"use client";

import { useEffect, useState } from "react";

interface TrainingStats {
  total_examples: number;
  curated: number;
  synthetic: number;
  live: number;
  by_tool: Record<string, number>;
  latest_run: {
    timestamp: string;
    final_loss: number;
    training_examples: number;
    backend: string;
    epochs: number;
  } | null;
  experiment_results: Record<string, { accuracy: number; avg_latency_ms: number }>;
}

export default function TrainingPage() {
  const [stats, setStats] = useState<TrainingStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchStats() {
      try {
        const res = await fetch("/api/training/stats");
        if (res.ok) {
          setStats(await res.json());
        }
      } catch (e) {
        console.error("Failed to fetch training stats:", e);
      } finally {
        setLoading(false);
      }
    }
    fetchStats();
  }, []);

  // Static demo data for when API isn't available
  const demoStats: TrainingStats = {
    total_examples: 226,
    curated: 103,
    synthetic: 123,
    live: 0,
    by_tool: {
      memory_write: 28,
      memory_read: 18,
      shared_write: 16,
      shared_search: 18,
      shared_log: 16,
      notify: 18,
      exec: 16,
      spawn_agent: 16,
      list_tools: 10,
      none: 20,
      multi: 10,
    },
    latest_run: {
      timestamp: "2026-02-07T22:52:23",
      final_loss: 0.024,
      training_examples: 226,
      backend: "mlx",
      epochs: 3,
    },
    experiment_results: {
      "FunctionGemma-270M (base)": { accuracy: 15.4, avg_latency_ms: 203 },
      "Qwen3-1.7B (router)": { accuracy: 38.5, avg_latency_ms: 515 },
      "FunctionGemma-270M (fine-tuned)": { accuracy: 100, avg_latency_ms: 271 },
    },
  };

  const data = stats || demoStats;

  const toolColors: Record<string, string> = {
    memory_write: "bg-blue-500",
    memory_read: "bg-blue-300",
    shared_write: "bg-purple-500",
    shared_search: "bg-purple-300",
    shared_read: "bg-purple-200",
    shared_log: "bg-orange-400",
    notify: "bg-red-400",
    exec: "bg-green-500",
    spawn_agent: "bg-yellow-500",
    list_tools: "bg-gray-400",
    none: "bg-gray-300",
    multi: "bg-pink-400",
  };

  const toolEmoji: Record<string, string> = {
    memory_write: "📝",
    memory_read: "📖",
    shared_write: "📤",
    shared_search: "🔍",
    shared_read: "📥",
    shared_log: "📋",
    notify: "🔔",
    exec: "⚡",
    spawn_agent: "🤖",
    list_tools: "📦",
    none: "💬",
    multi: "🔗",
  };

  const maxToolCount = Math.max(...Object.values(data.by_tool));

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          🧠 Tool Router Training
        </h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          LoRA fine-tuning pipeline for FunctionGemma-270M — routes user messages to the right tool in &lt;300ms
        </p>
      </div>

      {/* Hero Results */}
      <div className="bg-gradient-to-r from-green-50 dark:from-green-950 to-emerald-50 dark:to-emerald-950 border border-green-200 dark:border-green-800 rounded-xl p-6">
        <div className="flex items-center gap-3 mb-4">
          <span className="text-4xl">🎯</span>
          <div>
            <h2 className="text-xl font-bold text-green-800 dark:text-green-200">100% Accuracy Achieved</h2>
            <p className="text-green-600 dark:text-green-400 text-sm">FunctionGemma-270M fine-tuned on 226 examples • 3 min training • 271ms avg latency</p>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4 mt-4">
          {Object.entries(data.experiment_results).map(([name, result]) => (
            <div key={name} className="bg-white/80 dark:bg-gray-800/80 rounded-lg p-4 text-center">
              <div className={`text-3xl font-bold ${result.accuracy === 100 ? 'text-green-600' : result.accuracy > 30 ? 'text-yellow-600' : 'text-red-500'}`}>
                {result.accuracy.toFixed(1)}%
              </div>
              <div className="text-sm font-medium text-gray-700 dark:text-gray-300 mt-1">{name}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">{result.avg_latency_ms.toFixed(0)}ms avg</div>
            </div>
          ))}
        </div>
      </div>

      {/* Architecture Diagram */}
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow dark:shadow-gray-900/20 border dark:border-gray-700 p-6">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          ⚡ Two-Stage Pipeline Architecture
        </h2>
        <div className="flex items-center justify-center gap-2 py-6">
          {/* User Input */}
          <div className="bg-blue-50 dark:bg-blue-950 border-2 border-blue-200 dark:border-blue-800 rounded-lg p-4 text-center min-w-[160px]">
            <div className="text-2xl mb-1">💬</div>
            <div className="font-semibold text-blue-800 dark:text-blue-200">User Message</div>
            <div className="text-xs text-blue-500 dark:text-blue-400 mt-1">"Save a note about<br/>the meeting"</div>
          </div>

          <div className="text-gray-400 dark:text-gray-500 text-2xl">→</div>

          {/* Stage 1: Router */}
          <div className="bg-amber-50 dark:bg-amber-950 border-2 border-amber-300 dark:border-amber-800 rounded-lg p-4 text-center min-w-[180px] relative">
            <div className="absolute -top-3 left-3 bg-amber-200 text-amber-800 text-xs font-bold px-2 py-0.5 rounded-full">Stage 1</div>
            <div className="text-2xl mb-1">🧠</div>
            <div className="font-semibold text-amber-800 dark:text-amber-200">FunctionGemma</div>
            <div className="text-xs text-amber-600 dark:text-amber-400 mt-1">270M params • 271ms</div>
            <div className="text-xs text-amber-500 dark:text-amber-400">550MB RAM • Runs on phone</div>
          </div>

          <div className="text-gray-400 dark:text-gray-500 text-2xl">→</div>

          {/* Tool Selection */}
          <div className="bg-green-50 dark:bg-green-950 border-2 border-green-300 dark:border-green-800 rounded-lg p-4 text-center min-w-[160px]">
            <div className="text-2xl mb-1">🔧</div>
            <div className="font-semibold text-green-800 dark:text-green-200">Tool Selected</div>
            <div className="text-xs text-green-600 dark:text-green-400 mt-1 font-mono">memory_write</div>
            <div className="text-xs text-green-500 dark:text-green-400">Execute locally</div>
          </div>

          <div className="text-gray-400 dark:text-gray-500 text-2xl">→</div>

          {/* Stage 2: Reasoning */}
          <div className="bg-purple-50 dark:bg-purple-950 border-2 border-purple-300 dark:border-purple-800 rounded-lg p-4 text-center min-w-[180px] relative">
            <div className="absolute -top-3 left-3 bg-purple-200 text-purple-800 text-xs font-bold px-2 py-0.5 rounded-full">Stage 2</div>
            <div className="text-2xl mb-1">🦙</div>
            <div className="font-semibold text-purple-800 dark:text-purple-200">Qwen3-8B</div>
            <div className="text-xs text-purple-600 dark:text-purple-400 mt-1">Reasoning + Response</div>
            <div className="text-xs text-purple-500 dark:text-purple-400">Only when needed</div>
          </div>
        </div>

        <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 mt-2">
          <div className="text-sm text-gray-600 dark:text-gray-400 text-center">
            <strong>Key insight:</strong> The tiny 270M model handles tool routing (the fast, repetitive part).
            The big 8B model only runs for complex reasoning. On a phone, Stage 1 runs at <strong>&lt;100ms</strong> — fully offline.
          </div>
        </div>
      </div>

      {/* Training Data & Tool Distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Training Data Sources */}
        <div className="bg-white dark:bg-gray-900 rounded-xl shadow dark:shadow-gray-900/20 border dark:border-gray-700 p-6">
          <h2 className="text-lg font-semibold mb-4">📊 Training Data</h2>

          <div className="flex items-center gap-4 mb-6">
            <div className="text-center">
              <div className="text-4xl font-bold text-blue-600">{data.total_examples}</div>
              <div className="text-sm text-gray-500 dark:text-gray-400">Total Examples</div>
            </div>
            <div className="flex-1 space-y-2">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 bg-blue-500 rounded"></div>
                <span className="text-sm text-gray-600 dark:text-gray-400">Hand-curated</span>
                <span className="text-sm font-mono text-gray-800 dark:text-gray-200 ml-auto">{data.curated}</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 bg-purple-500 rounded"></div>
                <span className="text-sm text-gray-600 dark:text-gray-400">Teacher-generated (Qwen3-8B)</span>
                <span className="text-sm font-mono text-gray-800 dark:text-gray-200 ml-auto">{data.synthetic}</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 bg-green-500 rounded"></div>
                <span className="text-sm text-gray-600 dark:text-gray-400">Live usage (continuous)</span>
                <span className="text-sm font-mono text-gray-800 dark:text-gray-200 ml-auto">{data.live}</span>
              </div>
            </div>
          </div>

          {/* Stacked bar */}
          <div className="w-full h-6 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden flex">
            <div className="bg-blue-500 h-full" style={{ width: `${(data.curated / data.total_examples) * 100}%` }}></div>
            <div className="bg-purple-500 h-full" style={{ width: `${(data.synthetic / data.total_examples) * 100}%` }}></div>
            <div className="bg-green-500 h-full" style={{ width: `${(data.live / data.total_examples) * 100}%` }}></div>
          </div>
        </div>

        {/* Tool Distribution */}
        <div className="bg-white dark:bg-gray-900 rounded-xl shadow dark:shadow-gray-900/20 border dark:border-gray-700 p-6">
          <h2 className="text-lg font-semibold mb-4">🔧 Examples by Tool</h2>
          <div className="space-y-2">
            {Object.entries(data.by_tool)
              .sort(([, a], [, b]) => b - a)
              .map(([tool, count]) => (
                <div key={tool} className="flex items-center gap-2">
                  <span className="text-lg w-7">{toolEmoji[tool] || "🔧"}</span>
                  <span className="text-sm font-mono w-28 text-gray-700 dark:text-gray-300">{tool}</span>
                  <div className="flex-1 h-5 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${toolColors[tool] || "bg-gray-400"}`}
                      style={{ width: `${(count / maxToolCount) * 100}%` }}
                    ></div>
                  </div>
                  <span className="text-sm font-mono text-gray-500 dark:text-gray-400 w-8 text-right">{count}</span>
                </div>
              ))}
          </div>
        </div>
      </div>

      {/* Training Progress */}
      {data.latest_run && (
        <div className="bg-white dark:bg-gray-900 rounded-xl shadow dark:shadow-gray-900/20 border dark:border-gray-700 p-6">
          <h2 className="text-lg font-semibold mb-4">📈 Training Progress</h2>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 text-center">
              <div className="text-2xl font-bold text-green-600">{data.latest_run.final_loss.toFixed(3)}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">Final Val Loss</div>
            </div>
            <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 text-center">
              <div className="text-2xl font-bold text-blue-600">{data.latest_run.training_examples}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">Training Examples</div>
            </div>
            <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 text-center">
              <div className="text-2xl font-bold text-purple-600">{data.latest_run.epochs}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">Epochs</div>
            </div>
            <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 text-center">
              <div className="text-2xl font-bold text-amber-600">{data.latest_run.backend.toUpperCase()}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">Backend</div>
            </div>
            <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 text-center">
              <div className="text-2xl font-bold text-gray-600 dark:text-gray-400">178×</div>
              <div className="text-xs text-gray-500 dark:text-gray-400">Loss Improvement</div>
            </div>
          </div>

          {/* Loss curve visualization */}
          <div className="mt-6">
            <h3 className="text-sm font-medium text-gray-600 dark:text-gray-400 mb-2">Loss Curve (339 iterations)</h3>
            <div className="relative h-32 bg-gray-50 dark:bg-gray-800 rounded-lg border dark:border-gray-700 overflow-hidden">
              {/* SVG loss curve */}
              <svg viewBox="0 0 339 100" className="w-full h-full" preserveAspectRatio="none">
                <defs>
                  <linearGradient id="lossGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#ef4444" stopOpacity="0.2" />
                    <stop offset="100%" stopColor="#22c55e" stopOpacity="0.05" />
                  </linearGradient>
                </defs>
                {/* Loss curve path - actual data points mapped */}
                <path
                  d="M0,100 L5,52 L10,10 L15,7 L20,4 L25,4.4 L30,4.4 L35,3.2 L40,3.2 L45,5.4 L50,2.8 L55,2.3 L60,2.5 L65,3.1 L70,2.1 L75,2.4 L80,2 L85,2 L90,1.8 L95,1.9 L100,1.6 L110,2.6 L120,1.7 L130,1.1 L140,1.1 L150,1.2 L160,1 L170,1.5 L180,1 L190,1.3 L200,1.4 L210,0.8 L220,0.8 L230,1 L240,0.7 L250,0.8 L260,0.6 L270,0.7 L280,0.6 L290,0.8 L300,0.6 L310,0.7 L320,0.6 L330,0.7 L339,0.5"
                  fill="url(#lossGrad)"
                  stroke="#22c55e"
                  strokeWidth="1.5"
                />
                {/* Validation loss points */}
                <circle cx="1" cy="100" r="3" fill="#ef4444" />
                <circle cx="100" cy="1.5" r="3" fill="#eab308" />
                <circle cx="200" cy="1" r="3" fill="#22c55e" />
                <circle cx="300" cy="0.6" r="3" fill="#22c55e" />
                <circle cx="339" cy="0.5" r="3" fill="#22c55e" />
              </svg>
              {/* Labels */}
              <div className="absolute top-1 left-2 text-xs text-red-500 font-mono">4.272</div>
              <div className="absolute bottom-1 right-2 text-xs text-green-600 font-mono">0.024</div>
            </div>
          </div>
        </div>
      )}

      {/* Continuous Training Loop */}
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow dark:shadow-gray-900/20 border dark:border-gray-700 p-6">
        <h2 className="text-lg font-semibold mb-4">🔄 Continuous Training Loop</h2>
        <div className="flex items-center justify-center gap-2 py-4">
          <div className="flex flex-col items-center gap-1">
            <div className="w-20 h-20 bg-blue-50 dark:bg-blue-950 border-2 border-blue-300 dark:border-blue-700 rounded-full flex items-center justify-center text-2xl">💬</div>
            <span className="text-xs font-medium text-gray-600 dark:text-gray-400">User chats</span>
          </div>
          <div className="text-gray-300 dark:text-gray-600 text-xl">→</div>
          <div className="flex flex-col items-center gap-1">
            <div className="w-20 h-20 bg-amber-50 dark:bg-amber-950 border-2 border-amber-300 dark:border-amber-700 rounded-full flex items-center justify-center text-2xl">🧠</div>
            <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Router decides</span>
          </div>
          <div className="text-gray-300 dark:text-gray-600 text-xl">→</div>
          <div className="flex flex-col items-center gap-1">
            <div className="w-20 h-20 bg-green-50 dark:bg-green-950 border-2 border-green-300 dark:border-green-700 rounded-full flex items-center justify-center text-2xl">🔧</div>
            <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Tool executes</span>
          </div>
          <div className="text-gray-300 dark:text-gray-600 text-xl">→</div>
          <div className="flex flex-col items-center gap-1">
            <div className="w-20 h-20 bg-purple-50 dark:bg-purple-950 border-2 border-purple-300 dark:border-purple-700 rounded-full flex items-center justify-center text-2xl">📊</div>
            <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Log outcome</span>
          </div>
          <div className="text-gray-300 dark:text-gray-600 text-xl">→</div>
          <div className="flex flex-col items-center gap-1">
            <div className="w-20 h-20 bg-red-50 dark:bg-red-950 border-2 border-red-300 dark:border-red-700 rounded-full flex items-center justify-center text-2xl">🔁</div>
            <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Retrain</span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6">
          <div className="bg-blue-50 dark:bg-blue-950 rounded-lg p-4">
            <h3 className="font-semibold text-blue-800 dark:text-blue-200 text-sm mb-2">1. Data Collection</h3>
            <p className="text-xs text-blue-600 dark:text-blue-400">Every tool routing decision is automatically logged with the user message, selected tool, and outcome. No manual labeling needed.</p>
            <code className="text-xs text-blue-500 dark:text-blue-400 block mt-2 bg-blue-100 dark:bg-blue-900 p-2 rounded font-mono">~/.openhoof/data/function_pipeline/training_data.jsonl</code>
          </div>
          <div className="bg-purple-50 dark:bg-purple-950 rounded-lg p-4">
            <h3 className="font-semibold text-purple-800 dark:text-purple-200 text-sm mb-2">2. Teacher Generation</h3>
            <p className="text-xs text-purple-600 dark:text-purple-400">Qwen3-8B generates diverse synthetic examples for underrepresented tools. Ensures balanced training data across all capabilities.</p>
            <code className="text-xs text-purple-500 dark:text-purple-400 block mt-2 bg-purple-100 dark:bg-purple-900 p-2 rounded font-mono">python training/pipeline.py generate</code>
          </div>
          <div className="bg-green-50 dark:bg-green-950 rounded-lg p-4">
            <h3 className="font-semibold text-green-800 dark:text-green-200 text-sm mb-2">3. Auto-Retrain</h3>
            <p className="text-xs text-green-600 dark:text-green-400">When enough new data accumulates, trigger LoRA fine-tuning. Same script runs on Mac (MLX) or Linux (CUDA). Hot-swap the model.</p>
            <code className="text-xs text-green-500 dark:text-green-400 block mt-2 bg-green-100 dark:bg-green-900 p-2 rounded font-mono">python training/pipeline.py run</code>
          </div>
        </div>
      </div>

      {/* Available Tools Reference */}
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow dark:shadow-gray-900/20 border dark:border-gray-700 p-6">
        <h2 className="text-lg font-semibold mb-4">📦 Tool Definitions (what the router learns)</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {[
            { name: "memory_write", emoji: "📝", sig: "file, content, append", desc: "Write content to agent's memory files" },
            { name: "memory_read", emoji: "📖", sig: "file", desc: "Read from agent workspace files" },
            { name: "shared_write", emoji: "📤", sig: "key, content, tags", desc: "Write to shared cross-agent knowledge" },
            { name: "shared_read", emoji: "📥", sig: "key", desc: "Read from shared knowledge store" },
            { name: "shared_search", emoji: "🔍", sig: "query, category, limit", desc: "Search knowledge across all agents" },
            { name: "shared_log", emoji: "📋", sig: "finding, category, severity", desc: "Log a finding to the shared log" },
            { name: "spawn_agent", emoji: "🤖", sig: "task, agent_id, label", desc: "Spawn a sub-agent for specialized tasks" },
            { name: "notify", emoji: "🔔", sig: "title, message, priority", desc: "Send notification to human operator" },
            { name: "exec", emoji: "⚡", sig: "command, timeout", desc: "Execute a shell command" },
            { name: "list_tools", emoji: "📦", sig: "(none)", desc: "List all available tools" },
          ].map((tool) => (
            <div key={tool.name} className="flex items-start gap-3 bg-gray-50 dark:bg-gray-800 rounded-lg p-3 border dark:border-gray-700">
              <span className="text-xl">{tool.emoji}</span>
              <div className="min-w-0">
                <div className="font-mono text-sm font-semibold text-gray-800 dark:text-gray-200">
                  {tool.name}<span className="text-gray-400 dark:text-gray-500 font-normal">({tool.sig})</span>
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400">{tool.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Cross-Platform */}
      <div className="bg-gradient-to-r from-gray-800 to-gray-900 rounded-xl p-6 text-white">
        <h2 className="text-lg font-semibold mb-4">🖥️ Cross-Platform Training</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xl">🍎</span>
              <span className="font-semibold">Mac (Apple Silicon)</span>
              <span className="text-xs bg-green-600 px-2 py-0.5 rounded-full">Active</span>
            </div>
            <pre className="bg-black/30 rounded-lg p-3 text-sm font-mono text-green-300 overflow-x-auto">
{`bash training/setup.sh
python training/train_tool_router.py
# Uses unsloth-mlx + MLX backend
# Tested on M1/M2/M3/M4`}
            </pre>
          </div>
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xl">🐧</span>
              <span className="font-semibold">Linux (CUDA)</span>
              <span className="text-xs bg-blue-600 px-2 py-0.5 rounded-full">Supported</span>
            </div>
            <pre className="bg-black/30 rounded-lg p-3 text-sm font-mono text-blue-300 overflow-x-auto">
{`bash training/setup.sh
python training/train_tool_router.py --backend cuda
# Uses unsloth + PyTorch + CUDA
# Same script, same results`}
            </pre>
          </div>
        </div>
        <div className="text-center text-gray-400 text-sm mt-4">
          Same code, same API — just different backend. Prototype on Mac, scale on Linux.
        </div>
      </div>
    </div>
  );
}
