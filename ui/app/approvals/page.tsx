"use client";

import { useEffect, useState } from "react";

interface Approval {
  approval_id: string;
  agent_id: string;
  action: string;
  description: string;
  data: Record<string, unknown>;
  created_at: number;
  status: string;
}

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("pending");

  async function fetchApprovals() {
    const res = await fetch(`/api/approvals?status=${filter}`);
    if (res.ok) {
      setApprovals(await res.json());
    }
    setLoading(false);
  }

  async function resolveApproval(approvalId: string, approved: boolean) {
    await fetch(`/api/approvals/${approvalId}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    });
    fetchApprovals();
  }

  useEffect(() => {
    fetchApprovals();
    const interval = setInterval(fetchApprovals, 5000);
    return () => clearInterval(interval);
  }, [filter]);

  if (loading) {
    return <div className="animate-pulse">Loading...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold">Approvals</h1>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
        >
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      {approvals.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center">
          <p className="text-gray-500">
            {filter === "pending"
              ? "No pending approvals. Actions requiring approval will appear here."
              : `No ${filter} approvals.`}
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {approvals.map((approval) => (
            <div key={approval.approval_id} className="bg-white rounded-lg shadow p-6">
              <div className="flex justify-between items-start">
                <div>
                  <div className="flex items-center space-x-2">
                    <span className="text-lg font-semibold">{approval.action}</span>
                    <span
                      className={`px-2 py-1 rounded-full text-xs ${
                        approval.status === "pending"
                          ? "bg-yellow-100 text-yellow-800"
                          : approval.status === "approved"
                          ? "bg-green-100 text-green-800"
                          : "bg-red-100 text-red-800"
                      }`}
                    >
                      {approval.status}
                    </span>
                  </div>
                  <p className="text-gray-500 mt-1">{approval.description}</p>
                  <p className="text-sm text-gray-400 mt-2">
                    Agent: {approval.agent_id} • {new Date(approval.created_at * 1000).toLocaleString()}
                  </p>
                </div>
                {approval.status === "pending" && (
                  <div className="flex space-x-2">
                    <button
                      onClick={() => resolveApproval(approval.approval_id, true)}
                      className="px-4 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => resolveApproval(approval.approval_id, false)}
                      className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600"
                    >
                      Reject
                    </button>
                  </div>
                )}
              </div>
              
              {Object.keys(approval.data).length > 0 && (
                <div className="mt-4">
                  <details className="text-sm">
                    <summary className="text-gray-500 cursor-pointer hover:text-gray-700">
                      View Details
                    </summary>
                    <pre className="mt-2 bg-gray-50 p-3 rounded text-xs overflow-x-auto">
                      {JSON.stringify(approval.data, null, 2)}
                    </pre>
                  </details>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
