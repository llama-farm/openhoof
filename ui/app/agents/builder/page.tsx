"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import Link from "next/link";

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp?: number;
}

interface AgentCard {
  agent_id: string;
  name: string;
  action: string;
}

const QUICK_ACTIONS = [
  "Create a new agent",
  "Modify an existing agent",
  "List my agents",
];

function parseAgentCards(content: string): AgentCard[] {
  const cards: AgentCard[] = [];

  // Match patterns like: Created agent 'stock-watcher' (Stock Watcher)
  const createMatch = content.match(
    /Created agent '([^']+)' \(([^)]+)\)/
  );
  if (createMatch) {
    cards.push({
      agent_id: createMatch[1],
      name: createMatch[2],
      action: "created",
    });
  }

  // Match patterns like: Updated agent 'stock-watcher'
  const updateMatch = content.match(/Updated agent '([^']+)'/);
  if (updateMatch && !createMatch) {
    cards.push({
      agent_id: updateMatch[1],
      name: updateMatch[1],
      action: "updated",
    });
  }

  return cards;
}

function AgentStatusCard({ card }: { card: AgentCard }) {
  return (
    <div className="mt-2 border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/30 rounded-lg p-3 flex items-center justify-between">
      <div>
        <div className="font-medium text-blue-900 dark:text-blue-100">{card.name}</div>
        <div className="text-sm text-blue-600 dark:text-blue-400">
          {card.agent_id} &middot; {card.action}
        </div>
      </div>
      <Link
        href={`/agents/${card.agent_id}`}
        className="text-sm bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700"
      >
        View Agent
      </Link>
    </div>
  );
}

export default function BuilderPage() {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<
    "checking" | "starting" | "ready" | "error"
  >("checking");
  const [errorMsg, setErrorMsg] = useState("");

  // Check and auto-start builder agent
  useEffect(() => {
    async function ensureRunning() {
      try {
        const res = await fetch("/api/agents/agent-builder");
        if (!res.ok) {
          setStatus("error");
          setErrorMsg(
            "The agent builder is not available. Please restart the openhoof system to re-provision it."
          );
          return;
        }

        const data = await res.json();
        if (data.status === "running") {
          setStatus("ready");
          return;
        }

        // Try to start it
        setStatus("starting");
        const startRes = await fetch("/api/agents/agent-builder/start", {
          method: "POST",
        });
        if (startRes.ok) {
          setStatus("ready");
        } else {
          setStatus("error");
          setErrorMsg("Failed to start the agent builder. Please try again.");
        }
      } catch {
        setStatus("error");
        setErrorMsg("Cannot connect to the server.");
      }
    }
    ensureRunning();
  }, []);

  // Scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || loading) return;

      setInput("");
      setMessages((prev) => [...prev, { role: "user", content: text.trim() }]);
      setLoading(true);

      try {
        const res = await fetch("/api/agents/agent-builder/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text.trim() }),
        });

        if (res.ok) {
          const data = await res.json();
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: data.response },
          ]);
        } else {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: "Error: Failed to get response" },
          ]);
        }
      } catch {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "Error: Connection failed" },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [loading]
  );

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    sendMessage(input);
  }

  if (status === "checking" || status === "starting") {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4" />
          <p className="text-gray-500 dark:text-gray-400">
            {status === "checking"
              ? "Checking agent builder..."
              : "Starting agent builder..."}
          </p>
        </div>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="space-y-4">
        <div className="flex items-center space-x-3">
          <Link
            href="/agents"
            className="text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
          >
            &larr; Back to Agents
          </Link>
          <h1 className="text-xl font-bold">Agent Builder</h1>
        </div>
        <div className="bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg p-6 text-center">
          <p className="text-red-700 dark:text-red-300">{errorMsg}</p>
        </div>
      </div>
    );
  }

  const showSuggestions = messages.length === 0;

  return (
    <div className="flex flex-col h-[calc(100vh-200px)]">
      {/* Header */}
      <div className="flex justify-between items-center mb-4">
        <div className="flex items-center space-x-3">
          <Link
            href="/agents"
            className="text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
          >
            &larr; Back to Agents
          </Link>
          <h1 className="text-xl font-bold">Agent Builder</h1>
        </div>
        {messages.length > 0 && (
          <button
            onClick={() => setMessages([])}
            className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
          >
            Clear Chat
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900/20 overflow-y-auto p-4 space-y-4">
        {showSuggestions ? (
          <div className="flex flex-col items-center justify-center h-full space-y-6">
            <div className="text-center">
              <h2 className="text-lg font-semibold text-gray-700 dark:text-gray-300 mb-1">
                What would you like to build?
              </h2>
              <p className="text-sm text-gray-400 dark:text-gray-500">
                Describe your agent and I'll help you create it
              </p>
            </div>
            <div className="flex flex-wrap gap-2 justify-center">
              {QUICK_ACTIONS.map((action) => (
                <button
                  key={action}
                  onClick={() => sendMessage(action)}
                  className="px-4 py-2 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-full hover:bg-gray-200 dark:hover:bg-gray-700 text-sm transition-colors"
                >
                  {action}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, i) => {
            const cards =
              msg.role === "assistant" ? parseAgentCards(msg.content) : [];
            return (
              <div
                key={i}
                className={`flex ${
                  msg.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                <div
                  className={`max-w-[80%] rounded-lg px-4 py-2 ${
                    msg.role === "user"
                      ? "bg-blue-500 text-white"
                      : "bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200"
                  }`}
                >
                  <div className="text-xs opacity-70 mb-1">
                    {msg.role === "user" ? "You" : "Agent Builder"}
                  </div>
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                  {cards.map((card) => (
                    <AgentStatusCard key={card.agent_id} card={card} />
                  ))}
                </div>
              </div>
            );
          })
        )}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 dark:bg-gray-800 rounded-lg px-4 py-2 text-gray-500 dark:text-gray-400">
              <div className="flex items-center space-x-2">
                <div className="animate-bounce">&#9679;</div>
                <div
                  className="animate-bounce"
                  style={{ animationDelay: "0.1s" }}
                >
                  &#9679;
                </div>
                <div
                  className="animate-bounce"
                  style={{ animationDelay: "0.2s" }}
                >
                  &#9679;
                </div>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="mt-4">
        <div className="flex space-x-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Describe the agent you want to create..."
            className="flex-1 px-4 py-3 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-800 dark:border-gray-700 dark:text-gray-100"
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="px-6 py-3 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
