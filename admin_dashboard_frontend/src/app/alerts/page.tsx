"use client";

import { useEffect, useState } from 'react';
import { fetchAlerts, createAlert } from '@/lib/api';
import { isAdmin } from '@/lib/auth';
import type { Alert } from '@/types';

const REGIONS = ['all', 'Addis Ababa', 'Oromia', 'Amhara', 'SNNPR', 'Tigray', 'Sidama', 'Afar'];
const SEVERITIES = ['info', 'warning', 'critical'] as const;

const severityStyles: Record<string, string> = {
  info:     'bg-blue-50 text-blue-700 border-blue-200',
  warning:  'bg-amber-50 text-amber-700 border-amber-200',
  critical: 'bg-red-50 text-red-700 border-red-200',
};

export default function AlertsPage() {
  const [alerts, setAlerts]       = useState<Alert[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [toast, setToast]         = useState('');
  const [broadcasting, setBroadcasting] = useState(false);
  const admin = typeof window !== 'undefined' ? isAdmin() : false;

  // Form state
  const [targetRegion, setTargetRegion]   = useState('all');
  const [alertMessage, setAlertMessage]   = useState('');
  const [severity, setSeverity]           = useState<'info' | 'warning' | 'critical'>('warning');

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 3000); };

  const load = () => {
    setLoading(true);
    fetchAlerts()
      .then(setAlerts)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleBroadcast = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!alertMessage.trim()) return;
    setBroadcasting(true);
    try {
      await createAlert({ target_region: targetRegion, alert_message: alertMessage.trim(), severity });
      setAlertMessage('');
      showToast(`Alert broadcast to ${targetRegion === 'all' ? 'all regions' : targetRegion} ✓`);
      load();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Broadcast failed');
    } finally {
      setBroadcasting(false);
    }
  };

  // Summarise counts by severity for chart
  const counts = SEVERITIES.map((s) => ({
    label: s,
    count: alerts.filter((a) => a.severity === s).length,
  }));
  const maxCount = Math.max(...counts.map(c => c.count), 1);

  return (
    <div className="space-y-8">
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-slate-900 text-white text-sm font-medium px-4 py-2.5 rounded-lg shadow-lg">
          {toast}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mt-8">
        {/* Broadcast form — admin only */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="px-8 py-6 border-b border-slate-100">
            <h3 className="text-base font-medium text-slate-800">📢 Broadcast New Alert</h3>
          </div>
          {admin ? (
            <form onSubmit={handleBroadcast} className="p-8 space-y-4">
              <div className="space-y-1.5">
                <label htmlFor="al-region" className="text-sm font-medium text-slate-700">Target Region</label>
                <select
                  id="al-region"
                  value={targetRegion} onChange={(e) => setTargetRegion(e.target.value)}
                  className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 bg-white"
                >
                  {REGIONS.map(r => <option key={r} value={r}>{r === 'all' ? 'All Regions' : r}</option>)}
                </select>
              </div>

              <div className="space-y-1.5">
                <label htmlFor="al-severity" className="text-sm font-medium text-slate-700">Severity</label>
                <div className="flex gap-2">
                  {SEVERITIES.map((s) => (
                    <button
                      key={s} type="button"
                      onClick={() => setSeverity(s)}
                      className={`flex-1 py-2 rounded-md text-sm font-medium border transition-colors capitalize ${
                        severity === s
                          ? severityStyles[s]
                          : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50'
                      }`}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-1.5">
                <label htmlFor="al-message" className="text-sm font-medium text-slate-700">
                  Alert Message
                  <span className="text-xs font-normal text-slate-400 ml-1">(Amharic)</span>
                </label>
                <textarea
                  id="al-message" rows={4} required
                  placeholder="ማስጠንቀቂያ: ..."
                  value={alertMessage} onChange={(e) => setAlertMessage(e.target.value)}
                  className="w-full p-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 resize-none"
                />
              </div>

              <button
                type="submit"
                disabled={broadcasting || !alertMessage.trim()}
                className="w-full h-10 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm font-medium rounded-md transition-colors"
              >
                {broadcasting ? 'Broadcasting…' : '📣 Broadcast Alert'}
              </button>
            </form>
          ) : (
            <div className="p-8 text-center py-12">
              <span className="text-3xl block mb-3">🔒</span>
              <p className="text-sm font-medium text-slate-700">Admin Only</p>
              <p className="text-sm text-slate-500 mt-1">Only administrators can broadcast alerts.</p>
            </div>
          )}
        </div>

        {/* Severity chart */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="px-8 py-6 border-b border-slate-100">
            <h3 className="text-base font-medium text-slate-800">📊 Alert Summary by Severity</h3>
          </div>
          <div className="p-8 space-y-4">
            {counts.map(({ label, count }) => (
              <div key={label} className="flex items-center gap-4">
                <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border capitalize w-20 text-center ${severityStyles[label]}`}>
                  {label}
                </span>
                <div className="flex-1 bg-slate-100 rounded-full h-2.5">
                  <div
                    className={`h-2.5 rounded-full transition-all duration-700 ${
                      label === 'critical' ? 'bg-red-500' :
                      label === 'warning'  ? 'bg-amber-400' : 'bg-blue-400'
                    }`}
                    style={{ width: `${(count / maxCount) * 100}%` }}
                  />
                </div>
                <span className="text-sm font-semibold text-slate-700 w-8 text-right">{count}</span>
              </div>
            ))}
            <p className="text-xs text-slate-400 pt-2">
              Estimated reach: ~45,000 farmers in active warning zones.
            </p>
          </div>
        </div>
      </div>

      {/* Recent broadcasts */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="px-8 py-6 border-b border-slate-100">
          <h3 className="text-base font-medium text-slate-800">
            Recent Broadcasts
            {!loading && <span className="ml-2 text-sm font-normal text-slate-400">({alerts.length})</span>}
          </h3>
        </div>

        {loading && (
          <div className="p-8 space-y-3 animate-pulse">
            {[1,2,3].map(i => <div key={i} className="h-12 bg-slate-100 rounded" />)}
          </div>
        )}
        {error && (
          <div className="m-8 bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}
        {!loading && !error && (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-100">
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Region</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Severity</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Message</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Sent At</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {alerts.length > 0 ? alerts.map((a) => (
                  <tr key={a.id} className="hover:bg-slate-50 transition-colors">
                    <td className="py-4 px-8 text-sm font-medium text-slate-900 capitalize">{a.target_region}</td>
                    <td className="py-4 px-8">
                      <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border capitalize ${severityStyles[a.severity]}`}>
                        {a.severity}
                      </span>
                    </td>
                    <td className="py-4 px-8 text-sm text-slate-600 max-w-sm truncate">{a.alert_message}</td>
                    <td className="py-4 px-8 text-sm text-slate-400">
                      {a.created_at ? new Date(a.created_at).toLocaleString() : '—'}
                    </td>
                  </tr>
                )) : (
                  <tr>
                    <td colSpan={4} className="py-16 text-center text-sm text-slate-400">
                      No alerts broadcast yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
