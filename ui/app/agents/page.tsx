"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface Agent {
  agent_id: string;
  name: string;
  description: string;
  status: string;
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);

  async function fetchAgents() {
    const res = await fetch("/api/agents");
    if (res.ok) {
      setAgents(await res.json());
    }
    setLoading(false);
  }

  async function startAgent(agentId: string) {
    await fetch(`/api/agents/${agentId}/start`, { method: "POST" });
    fetchAgents();
  }

  async function stopAgent(agentId: string) {
    await fetch(`/api/agents/${agentId}/stop`, { method: "POST" });
    fetchAgents();
  }

  async function deleteAgent(agentId: string) {
    if (!confirm(`Delete agent "${agentId}"?`)) return;
    await fetch(`/api/agents/${agentId}`, { method: "DELETE" });
    fetchAgents();
  }

  useEffect(() => {
    fetchAgents();
  }, []);

  if (loading) {
    return <div className="animate-pulse">Loading...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold">Agents</h1>
        <div className="flex space-x-3">
          <Link
            href="/agents/builder"
            className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
          >
            Create Agent
          </Link>
          <Link
            href="/agents/new"
            className="bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 px-4 py-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700"
          >
            + Manual
          </Link>
        </div>
      </div>

      {agents.length === 0 ? (
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900/20 p-8 text-center">
          <p className="text-gray-500 dark:text-gray-400 mb-4">No agents yet.</p>
          <Link
            href="/agents/new"
            className="text-blue-600 hover:underline"
          >
            Create your first agent →
          </Link>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900/20 overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  Agent
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
              {agents.map((agent) => (
                <tr key={agent.agent_id} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                  <td className="px-6 py-4">
                    <Link href={`/agents/${agent.agent_id}`} className="block">
                      <div className="font-medium text-gray-900 dark:text-gray-100">{agent.name}</div>
                      <div className="text-sm text-gray-500 dark:text-gray-400">{agent.agent_id}</div>
                      {agent.description && (
                        <div className="text-sm text-gray-400 dark:text-gray-500 mt-1">{agent.description}</div>
                      )}
                    </Link>
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className={`px-2 py-1 rounded-full text-xs ${
                        agent.status === "running"
                          ? "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200"
                          : "bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200"
                      }`}
                    >
                      {agent.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 space-x-2">
                    {agent.status === "running" ? (
                      <button
                        onClick={() => stopAgent(agent.agent_id)}
                        className="text-sm text-orange-600 hover:text-orange-800"
                      >
                        Stop
                      </button>
                    ) : (
                      <button
                        onClick={() => startAgent(agent.agent_id)}
                        className="text-sm text-green-600 hover:text-green-800"
                      >
                        Start
                      </button>
                    )}
                    <Link
                      href={`/agents/${agent.agent_id}/chat`}
                      className="text-sm text-blue-600 hover:text-blue-800"
                    >
                      Chat
                    </Link>
                    <button
                      onClick={() => deleteAgent(agent.agent_id)}
                      className="text-sm text-red-600 hover:text-red-800"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
