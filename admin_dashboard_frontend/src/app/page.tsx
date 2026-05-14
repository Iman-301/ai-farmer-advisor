"use client";

import { useEffect, useState } from 'react';
import { fetchStats } from '@/lib/api';
import type { AdminStats } from '@/types';
import { Users, Phone, AlertCircle, BookOpen } from 'lucide-react';
import StatCard from '@/components/ui/StatCard';

export default function Dashboard() {
  const [stats, setStats]     = useState<AdminStats | null>(null);
  const [error, setError]     = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingState />;
  if (error)   return <ErrorState message={error} />;
  if (!stats)  return null;

  const cards = [
    { label: 'Registered Farmers',   value: stats.total_farmers,        icon: <Users size={20} />,       bg: 'bg-blue-50',   text: 'text-blue-500' },
    { label: 'Calls Today',           value: stats.calls_today,          icon: <Phone size={20} />,       bg: 'bg-green-50',  text: 'text-green-500' },
    { label: 'Pending Escalations',   value: stats.pending_escalations,  icon: <AlertCircle size={20} />, bg: 'bg-orange-50', text: 'text-orange-500' },
    { label: 'Knowledge Base Entries',value: stats.kb_count,             icon: <BookOpen size={20} />,    bg: 'bg-purple-50', text: 'text-purple-500' },
  ];

  const resolved = stats.escalation_breakdown['resolved'] ?? 0;
  const pending  = stats.escalation_breakdown['pending']  ?? 0;
  const total    = resolved + pending || 1; // avoid divide by zero

  return (
    <div className="space-y-8">
      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        {cards.map((card) => (
          <StatCard
            key={card.label}
            label={card.label}
            value={card.value}
            icon={card.icon}
            iconBgColorClass={card.bg}
            iconTextColorClass={card.text}
          />
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* System overview */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="px-8 py-6 border-b border-slate-100">
            <h3 className="text-base font-medium text-slate-800">System Overview</h3>
          </div>
          <div className="px-8 pb-8 pt-2 divide-y divide-slate-100">
            <Row label="Total Calls (all time)" value={String(stats.total_calls)} />
            <Row label="Total Alerts Broadcast"  value={String(stats.total_alerts)} />
            <Row label="Escalations Resolved"    value={`${resolved} / ${resolved + pending}`} />
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

      {/* Escalation breakdown */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="px-8 py-6 border-b border-slate-100">
          <h3 className="text-base font-medium text-slate-800">Escalation Resolution Rate</h3>
        </div>
        <div className="px-8 py-6">
          <div className="flex items-center gap-4 mb-2">
            <span className="text-sm text-slate-500 w-20">Resolved</span>
            <div className="flex-1 bg-slate-100 rounded-full h-2.5">
              <div
                className="bg-green-500 h-2.5 rounded-full transition-all duration-700"
                style={{ width: `${(resolved / total) * 100}%` }}
              />
            </div>
            <span className="text-sm font-medium text-slate-700 w-8">{resolved}</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-slate-500 w-20">Pending</span>
            <div className="flex-1 bg-slate-100 rounded-full h-2.5">
              <div
                className="bg-amber-400 h-2.5 rounded-full transition-all duration-700"
                style={{ width: `${(pending / total) * 100}%` }}
              />
            </div>
            <span className="text-sm font-medium text-slate-700 w-8">{pending}</span>
          </div>
        </div>
      </div>
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
