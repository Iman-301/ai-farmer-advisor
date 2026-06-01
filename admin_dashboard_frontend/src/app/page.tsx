"use client";

import { useEffect, useState } from 'react';
import { fetchAnalyticsSummary, fetchStats } from '@/lib/api';
import type { AdminStats, AnalyticsSummary } from '@/types';
import { Phone, ClipboardList, HeadphonesIcon, BarChart2 } from 'lucide-react';
import StatCard from '@/components/ui/StatCard';

export default function Dashboard() {
  const [stats, setStats]     = useState<AdminStats | null>(null);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [error, setError]     = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([fetchStats(), fetchAnalyticsSummary().catch(() => null)])
      .then(([s, a]) => { setStats(s); setSummary(a); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingState />;
  if (error)   return <ErrorState message={error} />;
  if (!stats)  return null;

  const openCases =
    (stats.escalation_breakdown['pending'] ?? 0) +
    (stats.escalation_breakdown['assigned'] ?? 0);
  const closedCases =
    (stats.escalation_breakdown['answered'] ?? 0) +
    (stats.escalation_breakdown['closed'] ?? 0) +
    (stats.escalation_breakdown['resolved'] ?? 0);

  return (
    <div className="space-y-8">
      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          label="Calls Today"
          value={stats.calls_today}
          icon={<Phone size={20} />}
          iconBgColorClass="bg-green-50"
          iconTextColorClass="text-green-600"
        />
        <StatCard
          label="Call Logs (all time)"
          value={stats.total_calls}
          icon={<ClipboardList size={20} />}
          iconBgColorClass="bg-blue-50"
          iconTextColorClass="text-blue-600"
        />
        <StatCard
          label="Helpdesk Open Cases"
          value={openCases}
          icon={<HeadphonesIcon size={20} />}
          iconBgColorClass="bg-amber-50"
          iconTextColorClass="text-amber-600"
        />
        <StatCard
          label="Helpdesk Closed Cases"
          value={closedCases}
          icon={<HeadphonesIcon size={20} />}
          iconBgColorClass="bg-slate-100"
          iconTextColorClass="text-slate-600"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Analytics summary */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="px-8 py-6 border-b border-slate-100">
            <h3 className="text-base font-medium text-slate-800 flex items-center gap-2">
              <BarChart2 size={16} />
              Analytics Summary
            </h3>
          </div>
          <div className="px-8 pb-8 pt-2 divide-y divide-slate-100">
            <Row label="Total Farmers" value={summary ? String(summary.total_farmers) : String(stats.total_farmers)} />
            <Row label="Calls (last 30 days)" value={summary ? String(summary.calls_30d) : '—'} />
            <Row label="New Farmers (last 30 days)" value={summary ? String(summary.new_farmers_30d) : '—'} />
            <Row label="Open Escalations" value={summary ? String(summary.open_escalations) : String(openCases)} />
          </div>
        </div>

        {/* Calls per day — last 7 days */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="px-8 py-6 border-b border-slate-100">
            <h3 className="text-base font-medium text-slate-800">Calls — Last 7 Days</h3>
          </div>
          <div className="px-8 py-6">
            {stats.calls_per_day.length === 0 ? (
              <p className="text-sm text-slate-400">No call data yet.</p>
            ) : (
              <MiniBarChart data={stats.calls_per_day} />
            )}
          </div>
        </div>
      </div>

      {/* Keep the rest of the dashboard lightweight; detailed escalation stats live in /helpdesk and /analytics */}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-4">
      <span className="text-sm font-medium text-slate-600">{label}</span>
      <span className="text-sm font-semibold text-slate-900">{value}</span>
    </div>
  );
}

function MiniBarChart({ data }: { data: { date: string; count: number }[] }) {
  const max = Math.max(...data.map(d => d.count), 1);
  return (
    <div className="flex items-end gap-2 h-24">
      {data.map(d => (
        <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
          <div className="w-full flex items-end justify-center" style={{ height: 72 }}>
            <div
              className="w-full bg-green-400 rounded-t-sm"
              style={{ height: `${(d.count / max) * 72}px` }}
            />
          </div>
          <span className="text-[10px] text-slate-400 truncate w-full text-center">
            {d.date.slice(5)}
          </span>
        </div>
      ))}
    </div>
  );
}

function LoadingState() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mt-8">
      {[1,2,3,4].map(i => (
        <div key={i} className="bg-white rounded-xl border border-slate-200 p-6 h-28 animate-pulse" />
      ))}
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="mt-8 bg-red-50 border border-red-200 rounded-xl p-6">
      <p className="text-sm font-medium text-red-700">Failed to load dashboard: {message}</p>
      <p className="text-sm text-red-500 mt-1">Is the logic_service running?</p>
    </div>
  );
}
