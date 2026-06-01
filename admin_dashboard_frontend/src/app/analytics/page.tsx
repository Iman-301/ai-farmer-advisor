"use client";

import { useEffect, useState } from "react";
import {
  downloadCsv,
  fetchAnalyticsSummary,
  fetchCallsBreakdown,
  fetchCommonQuestions,
  fetchDAPerformance,
  fetchExpertPerformance,
} from "@/lib/api";
import type {
  AnalyticsSummary,
  DAPerformance,
  ExpertPerformance,
} from "@/types";
import StatCard from "@/components/ui/StatCard";
import { BarChart2, Download, HelpCircle, Phone, Users } from "lucide-react";

export default function AnalyticsPage() {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [questions, setQuestions] = useState<{ question: string; count: number }[]>([]);
  const [breakdown, setBreakdown] = useState<{ key: string; count: number }[]>([]);
  const [breakdownBy, setBreakdownBy] = useState<"date" | "region" | "language">("date");
  const [experts, setExperts] = useState<ExpertPerformance[]>([]);
  const [das, setDas] = useState<DAPerformance[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 3000);
  };

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [s, q, b, e, d] = await Promise.all([
        fetchAnalyticsSummary(),
        fetchCommonQuestions(10),
        fetchCallsBreakdown(breakdownBy),
        fetchExpertPerformance().catch(() => []),
        fetchDAPerformance().catch(() => []),
      ]);
      setSummary(s);
      setQuestions(q);
      setBreakdown(b);
      setExperts(e);
      setDas(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [breakdownBy]);

  const handleExport = async (
    resource: "calls" | "farmers" | "escalations" | "market-prices" | "alerts",
  ) => {
    try {
      await downloadCsv(resource);
      showToast(`Exported ${resource}.csv ✓`);
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Export failed");
    }
  };

  return (
    <div className="space-y-8">
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-slate-900 text-white text-sm font-medium px-4 py-2.5 rounded-lg shadow-lg">
          {toast}
        </div>
      )}

      <div className="flex items-center justify-between mt-8">
        <div>
          <h3 className="text-base font-medium text-slate-800">Analytics</h3>
          <p className="text-sm text-slate-500 mt-1">
            Usage and operational reporting.
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
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mt-8">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="bg-white rounded-xl border border-slate-200 p-6 h-28 animate-pulse"
            />
          ))}
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6">
          <p className="text-sm font-medium text-red-700">{error}</p>
        </div>
      )}

      {!loading && !error && summary && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            <StatCard
              label="Total Calls"
              value={summary.total_calls}
              icon={<Phone size={20} />}
              iconBgColorClass="bg-green-50"
              iconTextColorClass="text-green-600"
            />
            <StatCard
              label="Calls (30d)"
              value={summary.calls_30d}
              icon={<BarChart2 size={20} />}
              iconBgColorClass="bg-blue-50"
              iconTextColorClass="text-blue-600"
            />
            <StatCard
              label="Total Farmers"
              value={summary.total_farmers}
              icon={<Users size={20} />}
              iconBgColorClass="bg-purple-50"
              iconTextColorClass="text-purple-600"
            />
            <StatCard
              label="New Farmers (30d)"
              value={summary.new_farmers_30d}
              icon={<Users size={20} />}
              iconBgColorClass="bg-orange-50"
              iconTextColorClass="text-orange-600"
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {/* Breakdown */}
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="px-8 py-6 border-b border-slate-100 flex items-center justify-between gap-4">
                <h4 className="text-base font-medium text-slate-800">
                  Calls breakdown
                </h4>
                <select
                  value={breakdownBy}
                  onChange={(e) =>
                    setBreakdownBy(e.target.value as typeof breakdownBy)
                  }
                  className="h-10 px-3 rounded-md border border-slate-300 text-sm bg-white"
                >
                  <option value="date">By date</option>
                  <option value="region">By region</option>
                  <option value="language">By language</option>
                </select>
              </div>
              <div className="p-8">
                {breakdown.length === 0 ? (
                  <p className="text-sm text-slate-400">No data yet.</p>
                ) : (
                  <ul className="space-y-3">
                    {breakdown.slice(0, 12).map((b) => (
                      <li key={b.key} className="flex items-center justify-between">
                        <span className="text-sm text-slate-600">
                          {b.key || "unknown"}
                        </span>
                        <span className="text-sm font-semibold text-slate-900">
                          {b.count}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            {/* Common questions */}
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="px-8 py-6 border-b border-slate-100">
                <h4 className="text-base font-medium text-slate-800">
                  Most common questions
                </h4>
              </div>
              <div className="p-8">
                {questions.length === 0 ? (
                  <p className="text-sm text-slate-400">No data yet.</p>
                ) : (
                  <ol className="space-y-4">
                    {questions.map((q, idx) => (
                      <li key={idx} className="flex gap-4">
                        <div className="w-8 h-8 rounded-lg bg-slate-100 flex items-center justify-center text-slate-600 text-sm font-semibold shrink-0">
                          {idx + 1}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm text-slate-700 truncate">
                            {q.question}
                          </p>
                          <p className="text-xs text-slate-400">
                            {q.count} occurrences
                          </p>
                        </div>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            </div>
          </div>

          {/* Performance */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="px-8 py-6 border-b border-slate-100">
                <h4 className="text-base font-medium text-slate-800">
                  Expert performance
                </h4>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-slate-100">
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Expert
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Assigned
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Resolved
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {experts.length === 0 ? (
                      <tr>
                        <td colSpan={3} className="py-12 text-center text-sm text-slate-400">
                          No expert data yet.
                        </td>
                      </tr>
                    ) : (
                      experts.map((e) => (
                        <tr key={e.user_id} className="hover:bg-slate-50">
                          <td className="py-4 px-8 text-sm font-medium text-slate-900">
                            {e.full_name}
                            <div className="text-xs text-slate-400 font-mono">{e.email}</div>
                          </td>
                          <td className="py-4 px-8 text-sm text-slate-600">{e.assigned}</td>
                          <td className="py-4 px-8 text-sm font-semibold text-green-700">{e.resolved}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="px-8 py-6 border-b border-slate-100">
                <h4 className="text-base font-medium text-slate-800">
                  DA activity
                </h4>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-slate-100">
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        DA
                      </th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Alerts created
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {das.length === 0 ? (
                      <tr>
                        <td colSpan={2} className="py-12 text-center text-sm text-slate-400">
                          No DA data yet.
                        </td>
                      </tr>
                    ) : (
                      das.map((d) => (
                        <tr key={d.user_id} className="hover:bg-slate-50">
                          <td className="py-4 px-8 text-sm font-medium text-slate-900">
                            {d.full_name}
                            <div className="text-xs text-slate-400 font-mono">{d.email}</div>
                          </td>
                          <td className="py-4 px-8 text-sm font-semibold text-slate-900">
                            {d.alerts_created}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Exports */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-8 py-6 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h4 className="text-base font-medium text-slate-800">Exports</h4>
                <p className="text-sm text-slate-500 mt-1">
                  Download reports as CSV.
                </p>
              </div>
            </div>
            <div className="p-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
              <ExportButton label="Calls" onClick={() => handleExport("calls")} />
              <ExportButton label="Farmers" onClick={() => handleExport("farmers")} />
              <ExportButton label="Escalations" onClick={() => handleExport("escalations")} />
              <ExportButton label="Market prices" onClick={() => handleExport("market-prices")} />
              <ExportButton label="Alerts" onClick={() => handleExport("alerts")} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function ExportButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="h-10 px-4 rounded-md border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-sm font-medium flex items-center justify-center gap-2"
    >
      <Download size={16} />
      {label}
    </button>
  );
}

