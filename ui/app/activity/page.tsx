"use client";

import { useEffect, useState } from "react";

interface Activity {
  type: string;
  timestamp: string;
  agent_id: string | null;
  data: Record<string, unknown>;
}

export default function ActivityPage() {
  const [activity, setActivity] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("");

  async function fetchActivity() {
    const url = filter
      ? `/api/activity?limit=100&agent_id=${filter}`
      : "/api/activity?limit=100";
    const res = await fetch(url);
    if (res.ok) {
      setActivity(await res.json());
    }
    setLoading(false);
  }

  useEffect(() => {
    fetchActivity();
    const interval = setInterval(fetchActivity, 3000);
    return () => clearInterval(interval);
  }, [filter]);

  if (loading) {
    return <div className="animate-pulse">Loading...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold">Activity Feed</h1>
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by agent ID..."
          className="px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 w-64 dark:bg-gray-800 dark:border-gray-700 dark:text-gray-100"
        />
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900/20 divide-y dark:divide-gray-700">
        {activity.length === 0 ? (
          <div className="p-8 text-center text-gray-500 dark:text-gray-400">
            No activity yet. Events will appear here when agents run.
          </div>
        ) : (
          activity.map((item, i) => (
            <div key={i} className="p-4 hover:bg-gray-50 dark:hover:bg-gray-800">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <span className={`px-2 py-1 rounded text-xs font-medium ${getEventColor(item.type)}`}>
                    {item.type}
                  </span>
                  {item.agent_id && (
                    <span className="text-gray-600 dark:text-gray-400">{item.agent_id}</span>
                  )}
                </div>
                <span className="text-sm text-gray-400 dark:text-gray-500">
                  {new Date(item.timestamp).toLocaleString()}
                </span>
              </div>
              {Object.keys(item.data).length > 0 && (
                <div className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                  <pre className="bg-gray-50 dark:bg-gray-800 p-2 rounded text-xs overflow-x-auto">
                    {JSON.stringify(item.data, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function getEventColor(type: string): string {
  if (type.includes("started")) return "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200";
  if (type.includes("stopped")) return "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200";
  if (type.includes("message")) return "bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200";
  if (type.includes("error")) return "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200";
  if (type.includes("approval")) return "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200";
  return "bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200";
}
