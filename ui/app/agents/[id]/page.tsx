"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

interface Agent {
  agent_id: string;
  name: string;
  description: string;
  status: string;
  workspace_dir: string;
  tools?: string[];
  model?: string;
}

interface ToolAssignment {
  name: string;
  description: string;
  assigned: boolean;
}

export default function AgentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const agentId = params.id as string;

  const [agent, setAgent] = useState<Agent | null>(null);
  const [files, setFiles] = useState<string[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [assignedTools, setAssignedTools] = useState<ToolAssignment[]>([]);
  const [availableTools, setAvailableTools] = useState<ToolAssignment[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);

  async function fetchAgent() {
    const res = await fetch(`/api/agents/${agentId}`);
    if (res.ok) {
      setAgent(await res.json());
    }
  }

  async function fetchFiles() {
    const res = await fetch(`/api/agents/${agentId}/workspace`);
    if (res.ok) {
      setFiles(await res.json());
    }
    setLoading(false);
  }

  async function fetchFileContent(filename: string) {
    setSelectedFile(filename);
    const res = await fetch(`/api/agents/${agentId}/workspace/${filename}`);
    if (res.ok) {
      const data = await res.json();
      setFileContent(data.content);
    }
  }

  async function saveFile() {
    if (!selectedFile) return;
    setSaving(true);
    await fetch(`/api/agents/${agentId}/workspace/${selectedFile}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: fileContent }),
    });
    setSaving(false);
  }

  async function startAgent() {
    await fetch(`/api/agents/${agentId}/start`, { method: "POST" });
    fetchAgent();
  }

  async function stopAgent() {
    await fetch(`/api/agents/${agentId}/stop`, { method: "POST" });
    fetchAgent();
  }

  async function deleteAgent() {
    if (!confirm(`Delete agent "${agentId}"? This cannot be undone.`)) return;
    await fetch(`/api/agents/${agentId}`, { method: "DELETE" });
    router.push("/agents");
  }

  async function fetchTools() {
    try {
      const res = await fetch(`/api/tools/agents/${agentId}`);
      if (res.ok) {
        const data = await res.json();
        setAssignedTools(data.assigned_tools || []);
        setAvailableTools(data.available_tools || []);
      }
    } catch (e) {
      console.error("Failed to fetch tools:", e);
    }
  }

  async function toggleTool(toolName: string, currentlyAssigned: boolean) {
    setToolsLoading(true);
    const currentTools = assignedTools.map((t) => t.name);
    const newTools = currentlyAssigned
      ? currentTools.filter((n) => n !== toolName)
      : [...currentTools, toolName];

    try {
      const res = await fetch(`/api/tools/agents/${agentId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tools: newTools }),
      });
      if (res.ok) {
        await fetchTools();
      }
    } catch (e) {
      console.error("Failed to update tools:", e);
    }
    setToolsLoading(false);
  }

  useEffect(() => {
    fetchAgent();
    fetchFiles();
    fetchTools();
  }, [agentId]);

  if (loading) {
    return <div className="animate-pulse">Loading...</div>;
  }

  if (!agent) {
    return <div className="text-red-500">Agent not found</div>;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <div className="flex items-center space-x-3">
            <h1 className="text-2xl font-bold">{agent.name}</h1>
            <span
              className={`px-2 py-1 rounded-full text-xs ${
                agent.status === "running"
                  ? "bg-green-100 text-green-800"
                  : "bg-gray-100 text-gray-800"
              }`}
            >
              {agent.status}
            </span>
          </div>
          <p className="text-gray-500">{agent.agent_id}</p>
          {agent.description && <p className="text-gray-600 mt-1">{agent.description}</p>}
        </div>
        <div className="flex space-x-2">
          {agent.status === "running" ? (
            <button
              onClick={stopAgent}
              className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={startAgent}
              className="px-4 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600"
            >
              Start
            </button>
          )}
          <Link
            href={`/agents/${agentId}/chat`}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
          >
            Chat
          </Link>
          <Link
            href={`/agents/${agentId}/logs`}
            className="px-4 py-2 bg-purple-500 text-white rounded-lg hover:bg-purple-600"
          >
            Logs
          </Link>
          <button
            onClick={deleteAgent}
            className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600"
          >
            Delete
          </button>
        </div>
      </div>

      {/* Tools Management */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold">🔧 Tools</h2>
          <span className="text-sm text-gray-500">
            {assignedTools.length} assigned
          </span>
        </div>

        {/* Assigned Tools */}
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-700 mb-2">Assigned</h3>
          <div className="flex flex-wrap gap-2">
            {assignedTools.map((tool) => (
              <button
                key={tool.name}
                onClick={() => toggleTool(tool.name, true)}
                disabled={toolsLoading}
                className="inline-flex items-center gap-1 px-3 py-1.5 bg-blue-50 text-blue-700 rounded-full text-sm hover:bg-blue-100 border border-blue-200 transition-colors"
                title={tool.description}
              >
                <span className="font-mono text-xs">{tool.name}</span>
                <span className="text-blue-400 hover:text-red-500 ml-1">×</span>
              </button>
            ))}
            {assignedTools.length === 0 && (
              <span className="text-gray-400 text-sm">All tools enabled (no filter)</span>
            )}
          </div>
        </div>

        {/* Available (unassigned) Tools */}
        {availableTools.length > 0 && (
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">Available</h3>
            <div className="flex flex-wrap gap-2">
              {availableTools.map((tool) => (
                <button
                  key={tool.name}
                  onClick={() => toggleTool(tool.name, false)}
                  disabled={toolsLoading}
                  className="inline-flex items-center gap-1 px-3 py-1.5 bg-gray-50 text-gray-500 rounded-full text-sm hover:bg-green-50 hover:text-green-700 border border-gray-200 transition-colors"
                  title={tool.description}
                >
                  <span className="text-green-400">+</span>
                  <span className="font-mono text-xs">{tool.name}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {agent.model && (
          <div className="mt-4 pt-4 border-t">
            <span className="text-sm text-gray-500">Model: </span>
            <span className="text-sm font-mono bg-gray-100 px-2 py-0.5 rounded">
              {agent.model}
            </span>
          </div>
        )}
      </div>

      {/* Workspace Editor */}
      <div className="grid grid-cols-4 gap-4">
        {/* File List */}
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-3">Workspace Files</h3>
          <div className="space-y-1">
            {files.map((file) => (
              <button
                key={file}
                onClick={() => fetchFileContent(file)}
                className={`w-full text-left px-2 py-1 rounded text-sm ${
                  selectedFile === file
                    ? "bg-blue-100 text-blue-800"
                    : "hover:bg-gray-100"
                }`}
              >
                📄 {file}
              </button>
            ))}
          </div>
        </div>

        {/* File Editor */}
        <div className="col-span-3 bg-white rounded-lg shadow p-4">
          {selectedFile ? (
            <>
              <div className="flex justify-between items-center mb-3">
                <h3 className="font-semibold">{selectedFile}</h3>
                <button
                  onClick={saveFile}
                  disabled={saving}
                  className="px-3 py-1 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50 text-sm"
                >
                  {saving ? "Saving..." : "Save"}
                </button>
              </div>
              <textarea
                value={fileContent}
                onChange={(e) => setFileContent(e.target.value)}
                className="w-full h-96 p-3 font-mono text-sm border rounded-lg focus:ring-2 focus:ring-blue-500"
              />
            </>
          ) : (
            <div className="flex items-center justify-center h-96 text-gray-400">
              Select a file to edit
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
