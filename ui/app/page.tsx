"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";

interface Agent {
  agent_id: string;
  name: string;
  description: string;
  status: string;
}

interface Activity {
  type: string;
  timestamp: string;
  agent_id: string | null;
  data: Record<string, unknown>;
}

interface LogEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: string;
  event_id?: string;
}

const EVENT_ICONS: Record<string, string> = {
  "agent:started": "🚀",
  "agent:stopped": "🛑",
  "agent:message": "💬",
  "agent:thinking": "🧠",
  "agent:tool_call": "🔧",
  "agent:tool_result": "📦",
  "agent:error": "❌",
  "subagent:spawned": "🤖",
  "subagent:completed": "✨",
};

export default function Dashboard() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [liveEvents, setLiveEvents] = useState<LogEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const [agentsRes, activityRes] = await Promise.all([
          fetch("/api/agents"),
          fetch("/api/activity?limit=10"),
        ]);

        if (agentsRes.ok) {
          setAgents(await agentsRes.json());
        }
        if (activityRes.ok) {
          setActivity(await activityRes.json());
        }
      } catch (e) {
        setError("Failed to connect to API. Is the server running?");
      } finally {
        setLoading(false);
      }
    }

    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  // SSE for live events
  useEffect(() => {
    const eventSource = new EventSource("/api/logs/stream");
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => setConnected(true);
    eventSource.onerror = () => setConnected(false);
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "connected") return;
        setLiveEvents((prev) => [...prev.slice(-19), data]);
      } catch (e) {
        console.error("Failed to parse SSE event:", e);
      }
    };

    return () => {
      eventSource.close();
      eventSourceRef.current = null;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 dark:border-gray-100"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg p-4">
        <h3 className="text-red-800 dark:text-red-200 font-medium">Connection Error</h3>
        <p className="text-red-600 dark:text-red-400">{error}</p>
        <p className="text-sm text-red-500 dark:text-red-400 mt-2">
          Make sure the API is running: <code className="bg-red-100 dark:bg-red-900 px-1 rounded">atmosphere start</code>
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold dark:text-gray-100">Dashboard</h1>
        <Link
          href="/agents/new"
          className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
        >
          + New Agent
        </Link>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Active Agents */}
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900/20 p-6">
          <h2 className="text-lg font-semibold mb-4 dark:text-gray-100">Agents</h2>
          {agents.length === 0 ? (
            <p className="text-gray-500 dark:text-gray-400">No agents yet. Create one to get started!</p>
          ) : (
            <div className="space-y-3">
              {agents.map((agent) => (
                <Link
                  key={agent.agent_id}
                  href={`/agents/${agent.agent_id}`}
                  className="block p-3 border dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="font-medium dark:text-gray-100">{agent.name}</span>
                      <span className="text-gray-500 dark:text-gray-400 text-sm ml-2">({agent.agent_id})</span>
                    </div>
                    <span
                      className={`px-2 py-1 rounded-full text-xs ${
                        agent.status === "running"
                          ? "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200"
                          : "bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200"
                      }`}
                    >
                      {agent.status}
                    </span>
                  </div>
                  {agent.description && (
                    <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">{agent.description}</p>
                  )}
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Recent Activity */}
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900/20 p-6">
          <h2 className="text-lg font-semibold mb-4 dark:text-gray-100">Recent Activity</h2>
          {activity.length === 0 ? (
            <p className="text-gray-500 dark:text-gray-400">No activity yet.</p>
          ) : (
            <div className="space-y-2">
              {activity.map((item, i) => (
                <div key={i} className="text-sm border-b dark:border-gray-700 pb-2">
                  <div className="flex items-center justify-between">
                    <span className="font-medium dark:text-gray-200">{item.type}</span>
                    <span className="text-gray-400 text-xs">
                      {new Date(item.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                  {item.agent_id && (
                    <span className="text-gray-500 dark:text-gray-400">Agent: {item.agent_id}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900/20 p-4 text-center">
          <div className="text-3xl font-bold text-blue-600">{agents.length}</div>
          <div className="text-gray-500 dark:text-gray-400">Total Agents</div>
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900/20 p-4 text-center">
          <div className="text-3xl font-bold text-green-600">
            {agents.filter((a) => a.status === "running").length}
          </div>
          <div className="text-gray-500 dark:text-gray-400">Running</div>
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900/20 p-4 text-center">
          <div className="text-3xl font-bold text-orange-600">{activity.length}</div>
          <div className="text-gray-500 dark:text-gray-400">Recent Events</div>
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900/20 p-4 text-center">
          <div className={`text-3xl font-bold ${connected ? "text-green-600" : "text-red-600"}`}>
            {connected ? "●" : "○"}
          </div>
          <div className="text-gray-500 dark:text-gray-400">{connected ? "Live" : "Offline"}</div>
        </div>
      </div>

      {/* Live Agent Activity */}
      <div className="bg-gray-900 dark:bg-gray-950 rounded-lg shadow p-4">
        <div className="flex justify-between items-center mb-3">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${connected ? "bg-green-500 animate-pulse" : "bg-red-500"}`}></span>
            Live Agent Activity
          </h2>
          <Link href="/logs" className="text-blue-400 hover:text-blue-300 text-sm">
            View All Logs →
          </Link>
        </div>
        {liveEvents.length === 0 ? (
          <p className="text-gray-500 text-center py-4">Waiting for agent activity...</p>
        ) : (
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {liveEvents.slice().reverse().map((event, i) => (
              <div
                key={event.event_id || i}
                className="flex items-center gap-3 text-sm bg-gray-800 rounded px-3 py-2"
              >
                <span className="text-lg">{EVENT_ICONS[event.type] || "📋"}</span>
                <span className="text-gray-300 font-mono text-xs">
                  {new Date(event.timestamp).toLocaleTimeString()}
                </span>
                <span className="text-gray-400">{event.type}</span>
                {event.data.agent_id ? (
                  <span className="text-blue-400 text-xs">[{String(event.data.agent_id)}]</span>
                ) : null}
                <span className="text-gray-200 truncate flex-1">
                  {event.data.message ? String(event.data.message).slice(0, 50) : ""}
                  {event.data.tool_name ? `Tool: ${event.data.tool_name}` : ""}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
