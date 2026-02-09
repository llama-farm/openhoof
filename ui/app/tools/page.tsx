"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface ToolInfo {
  name: string;
  description: string;
  parameter_names: string[];
  required_params: string[];
  requires_approval: boolean;
}

interface Agent {
  agent_id: string;
  name: string;
  tools: string[];
}

export default function ToolsPage() {
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedTool, setExpandedTool] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const [toolsRes, agentsRes] = await Promise.all([
          fetch("/api/tools"),
          fetch("/api/agents"),
        ]);
        if (toolsRes.ok) setTools(await toolsRes.json());
        if (agentsRes.ok) setAgents(await agentsRes.json());
      } catch (e) {
        console.error("Failed to fetch:", e);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  function getAgentsUsingTool(toolName: string): Agent[] {
    return agents.filter(
      (a) => !a.tools || a.tools.length === 0 || a.tools.includes(toolName)
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 dark:border-gray-100"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold">🔧 Tools Registry</h1>
        <div className="text-sm text-gray-500 dark:text-gray-400">
          {tools.length} tools available
        </div>
      </div>

      <p className="text-gray-600 dark:text-gray-400">
        Tools are capabilities that agents can use. Assign tools to agents to
        control what they can do.
      </p>

      <div className="grid gap-4">
        {tools.map((tool) => {
          const usedBy = getAgentsUsingTool(tool.name);
          const isExpanded = expandedTool === tool.name;

          return (
            <div
              key={tool.name}
              className="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900/20 border dark:border-gray-700 hover:border-blue-200 dark:hover:border-blue-700 transition-colors"
            >
              <div
                className="p-4 cursor-pointer"
                onClick={() =>
                  setExpandedTool(isExpanded ? null : tool.name)
                }
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">
                      {tool.requires_approval ? "🔒" : "🔧"}
                    </span>
                    <div>
                      <h3 className="font-semibold text-lg font-mono">
                        {tool.name}
                      </h3>
                      <p className="text-gray-500 dark:text-gray-400 text-sm">
                        {tool.description.split("\n")[0]}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded">
                      {tool.parameter_names.length} params
                    </span>
                    <span className="text-xs bg-blue-50 text-blue-600 px-2 py-1 rounded">
                      {usedBy.length} agents
                    </span>
                    <span className="text-gray-400 dark:text-gray-500">
                      {isExpanded ? "▲" : "▼"}
                    </span>
                  </div>
                </div>
              </div>

              {isExpanded && (
                <div className="border-t dark:border-gray-700 px-4 py-3 bg-gray-50 dark:bg-gray-800">
                  <div className="grid md:grid-cols-2 gap-4">
                    <div>
                      <h4 className="font-medium text-sm text-gray-700 dark:text-gray-300 mb-2">
                        Description
                      </h4>
                      <p className="text-sm text-gray-600 dark:text-gray-400 whitespace-pre-line">
                        {tool.description}
                      </p>
                    </div>
                    <div>
                      <h4 className="font-medium text-sm text-gray-700 dark:text-gray-300 mb-2">
                        Parameters
                      </h4>
                      {tool.parameter_names.length === 0 ? (
                        <p className="text-sm text-gray-400 dark:text-gray-500">No parameters</p>
                      ) : (
                        <ul className="space-y-1">
                          {tool.parameter_names.map((param) => (
                            <li
                              key={param}
                              className="text-sm flex items-center gap-2"
                            >
                              <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded text-xs">
                                {param}
                              </code>
                              {tool.required_params.includes(param) && (
                                <span className="text-red-500 text-xs">
                                  required
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}

                      <h4 className="font-medium text-sm text-gray-700 dark:text-gray-300 mt-4 mb-2">
                        Used By
                      </h4>
                      <div className="flex flex-wrap gap-1">
                        {usedBy.map((agent) => (
                          <Link
                            key={agent.agent_id}
                            href={`/agents/${agent.agent_id}`}
                            className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded hover:bg-blue-200"
                          >
                            {agent.name || agent.agent_id}
                          </Link>
                        ))}
                        {usedBy.length === 0 && (
                          <span className="text-xs text-gray-400 dark:text-gray-500">
                            No agents
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
