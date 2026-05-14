"use client";

import { useEffect, useState } from 'react';
import { fetchEscalations, resolveEscalation } from '@/lib/api';
import { getRole } from '@/lib/auth';
import type { EscalationCase } from '@/types';
import Badge from '@/components/ui/Badge';

function statusLabel(s: string) { return s === 'pending' ? 'Open' : 'Resolved'; }
function statusVariant(s: string): 'warning' | 'success' { return s === 'pending' ? 'warning' : 'success'; }

export default function Helpdesk() {
  const [cases, setCases]         = useState<EscalationCase[]>([]);
  const [selected, setSelected]   = useState<EscalationCase | null>(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [resolving, setResolving] = useState(false);
  const [toast, setToast]         = useState('');
  const role = typeof window !== 'undefined' ? getRole() : null;

  const load = () => {
    setLoading(true);
    fetchEscalations()
      .then((data) => {
        setCases(data);
        // keep selected in sync
        if (selected) {
          const updated = data.find(c => c.id === selected.id);
          setSelected(updated ?? null);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []); // eslint-disable-line

  const openCount     = cases.filter(c => c.status === 'pending').length;
  const resolvedCount = cases.filter(c => c.status === 'resolved').length;

  const handleResolve = async () => {
    if (!selected || selected.id == null) return;
    setResolving(true);
    try {
      await resolveEscalation(selected.id);
      setToast(`Ticket #${selected.id} resolved ✓`);
      setTimeout(() => setToast(''), 3000);
      load();
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Failed to resolve');
    } finally {
      setResolving(false);
    }
  };

  return (
    <div>
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-slate-900 text-white text-sm font-medium px-4 py-2.5 rounded-lg shadow-lg">
          {toast}
        </div>
      )}

      {/* Overview cards */}
      <div className="grid grid-cols-2 gap-6 mb-8 mt-8">
        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Open Cases</p>
          <p className="text-3xl font-semibold text-amber-600">{openCount}</p>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Resolved Cases</p>
          <p className="text-3xl font-semibold text-green-600">{resolvedCount}</p>
        </div>
      </div>

      {error && <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">{error}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Case list */}
        <div className="lg:col-span-6 xl:col-span-7">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-8 py-6 border-b border-slate-100">
              <h3 className="text-base font-medium text-slate-800">Escalation Queue</h3>
            </div>
            {loading ? (
              <div className="p-8 space-y-3 animate-pulse">
                {[1,2,3].map(i => <div key={i} className="h-8 bg-slate-100 rounded" />)}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-slate-100">
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">ID</th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Query</th>
                      <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {cases.length > 0 ? cases.map((c) => (
                      <tr
                        key={c.id}
                        onClick={() => setSelected(c)}
                        className={`cursor-pointer transition-colors ${
                          selected?.id === c.id ? 'bg-slate-50' : 'hover:bg-slate-50'
                        }`}
                      >
                        <td className="py-4 px-8 text-sm font-medium text-slate-900">#{c.id}</td>
                        <td className="py-4 px-8 text-sm text-slate-600 max-w-[220px] truncate">{c.query ?? '—'}</td>
                        <td className="py-4 px-8">
                          <Badge label={statusLabel(c.status)} variant={statusVariant(c.status)} />
                        </td>
                      </tr>
                    )) : (
                      <tr>
                        <td colSpan={3} className="py-12 text-center text-sm text-slate-400">No escalations found.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Detail panel */}
        <div className="lg:col-span-6 xl:col-span-5">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden sticky top-8">
            {selected ? (
              <div>
                <div className="px-8 py-6 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
                  <div>
                    <h3 className="text-base font-medium text-slate-900">Ticket #{selected.id}</h3>
                    <p className="text-sm text-slate-500 mt-0.5">
                      {selected.timestamp ? new Date(selected.timestamp).toLocaleString() : ''}
                    </p>
                  </div>
                  <Badge label={statusLabel(selected.status)} variant={statusVariant(selected.status)} />
                </div>

                <div className="p-8 space-y-6">
                  {/* Query / Transcript */}
                  <div>
                    <span className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Query</span>
                    <div className="bg-slate-50 p-4 rounded-md border border-slate-200 text-sm text-slate-700 leading-relaxed">
                      {selected.query ?? '—'}
                    </div>
                  </div>

                  {/* Context */}
                  {selected.context && (
                    <div>
                      <span className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Context</span>
                      <div className="bg-slate-50 p-4 rounded-md border border-slate-200 text-xs text-slate-600 font-mono leading-relaxed break-all">
                        {selected.context}
                      </div>
                    </div>
                  )}

                  {/* Resolve action (any authenticated user) */}
                  {selected.status === 'pending' && (
                    <div className="pt-4 border-t border-slate-100">
                      <button
                        onClick={handleResolve}
                        disabled={resolving}
                        className="w-full h-10 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-sm font-medium rounded-md transition-colors"
                      >
                        {resolving ? 'Resolving…' : '✅ Mark as Resolved'}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="p-16 text-center">
                <p className="text-sm font-medium text-slate-900 mb-1">No ticket selected</p>
                <p className="text-sm text-slate-500">Click a row in the queue to view details.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
