"use client";

import { useEffect, useState } from "react";
import { fetchSystemStatus } from "@/lib/api";
import type { SystemStatus } from "@/types";
import Badge from "@/components/ui/Badge";

function probeVariant(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "online") return "success";
  if (status === "degraded") return "warning";
  if (status === "down") return "danger";
  return "neutral";
}

export default function MonitoringPage() {
  const [data, setData] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = () => {
    setLoading(true);
    setError("");
    fetchSystemStatus()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between mt-8">
        <div>
          <h3 className="text-base font-medium text-slate-800">System Monitoring</h3>
          <p className="text-sm text-slate-500 mt-1">
            Service health + recent backend errors.
          </p>
        </div>
        <button
          onClick={load}
          className="h-10 px-4 rounded-md bg-slate-900 hover:bg-slate-800 text-white text-sm font-medium"
        >
          Refresh
        </button>
      </div>

      {loading && (
        <div className="bg-white rounded-xl border border-slate-200 p-8 animate-pulse">
          <div className="h-6 w-48 bg-slate-100 rounded mb-4" />
          <div className="h-4 w-64 bg-slate-100 rounded" />
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {data && (
        <>
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-8 py-6 border-b border-slate-100">
              <h4 className="text-base font-medium text-slate-800">
                Service status
              </h4>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                      Service
                    </th>
                    <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                      Status
                    </th>
                    <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                      URL
                    </th>
                    <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                      Details
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {Object.entries(data.services).map(([name, probe]) => (
                    <tr key={name} className="hover:bg-slate-50">
                      <td className="py-4 px-8 text-sm font-medium text-slate-900 capitalize">
                        {name.replace("_", " ")}
                      </td>
                      <td className="py-4 px-8">
                        <Badge
                          label={String(probe.status)}
                          variant={probeVariant(String(probe.status))}
                        />
                      </td>
                      <td className="py-4 px-8 text-sm text-slate-500 font-mono">
                        {probe.url ?? "—"}
                      </td>
                      <td className="py-4 px-8 text-sm text-slate-600">
                        {"http_status" in probe && probe.http_status
                          ? `HTTP ${probe.http_status}`
                          : probe.error
                          ? probe.error
                          : probe.chroma_docs != null
                          ? `Chroma docs: ${probe.chroma_docs}`
                          : probe.chroma_status
                          ? probe.chroma_status
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-8 py-6 border-b border-slate-100 flex items-center justify-between">
              <h4 className="text-base font-medium text-slate-800">Recent errors</h4>
              <Badge
                label={`${data.recent_errors.length} events`}
                variant="neutral"
              />
            </div>
            {data.recent_errors.length === 0 ? (
              <div className="p-12 text-center text-sm text-slate-400">
                No recent errors recorded.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-slate-100">
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Time
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Service
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Endpoint
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Error
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.recent_errors.map((e) => (
                      <tr key={e.id} className="hover:bg-slate-50">
                        <td className="py-4 px-8 text-sm text-slate-500">
                          {e.created_at
                            ? new Date(e.created_at).toLocaleString()
                            : "—"}
                        </td>
                        <td className="py-4 px-8 text-sm font-medium text-slate-900">
                          {e.service}
                        </td>
                        <td className="py-4 px-8 text-sm text-slate-500 font-mono">
                          {e.method ? `${e.method} ` : ""}
                          {e.endpoint ?? "—"}
                        </td>
                        <td className="py-4 px-8 text-sm text-slate-600">
                          {e.error}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

