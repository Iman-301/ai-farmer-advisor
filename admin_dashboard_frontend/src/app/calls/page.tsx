"use client";

import { useEffect, useState } from 'react';
import { fetchCalls } from '@/lib/api';
import type { CallLog } from '@/types';

export default function CallLogs() {
  const [calls, setCalls]         = useState<CallLog[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [playingId, setPlayingId] = useState<string | number | null>(null);
  const [search, setSearch]       = useState('');

  useEffect(() => {
    fetchCalls()
      .then(setCalls)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = calls.filter((c) => {
    const q = search.toLowerCase();
    return (
      String(c.id).includes(q) ||
      (c.farmer_name ?? '').toLowerCase().includes(q) ||
      (c.phone_number ?? '').includes(q) ||
      (c.session_id ?? '').toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden mt-8">
        <div className="px-10 py-6 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <h3 className="text-base font-medium text-slate-800">
            Recent Call Records
            {!loading && <span className="ml-2 text-sm font-normal text-slate-400">({calls.length})</span>}
          </h3>
          <input
            type="search"
            placeholder="Search by farmer, phone, session…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="px-3 py-1.5 rounded-md border border-slate-200 text-sm text-slate-700 w-full sm:w-64 focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"
          />
        </div>

        {loading && <Skeleton />}
        {error   && <InlineError message={error} />}

        {!loading && !error && (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-100">
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">ID</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Farmer</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Phone</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Duration</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Timestamp</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Audio</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.length > 0 ? filtered.map((c) => (
                  <>
                    <tr
                      key={c.id}
                      className="hover:bg-slate-50 transition-colors"
                    >
                      <td className="py-4 px-8 text-sm font-medium text-slate-900">#{c.id}</td>
                      <td className="py-4 px-8 text-sm text-slate-700">{c.farmer_name ?? '—'}</td>
                      <td className="py-4 px-8 text-sm text-slate-600 font-mono">{c.phone_number ?? '—'}</td>
                      <td className="py-4 px-8 text-sm text-slate-600">
                        {c.duration != null ? `${c.duration}s` : '—'}
                      </td>
                      <td className="py-4 px-8 text-sm text-slate-600">
                        {c.timestamp ? new Date(c.timestamp).toLocaleString() : '—'}
                      </td>
                      <td className="py-4 px-8">
                        {c.recording_path ? (
                          <button
                            onClick={() => setPlayingId(playingId === c.id ? null : c.id)}
                            className={`text-xs font-medium px-3 py-1.5 rounded-md transition-colors ${
                              playingId === c.id
                                ? 'bg-green-100 text-green-700'
                                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                            }`}
                          >
                            {playingId === c.id ? '▼ Hide' : '▶ Play'}
                          </button>
                        ) : (
                          <span className="text-xs text-slate-300">No recording</span>
                        )}
                      </td>
                    </tr>
                    {playingId === c.id && c.recording_path && (
                      <tr key={`audio-${c.id}`}>
                        <td colSpan={6} className="px-8 py-4 bg-slate-50 border-b border-slate-100">
                          <div className="flex items-center gap-4">
                            <span className="text-xs text-slate-500 font-medium">Recording:</span>
                            <audio
                              controls
                              autoPlay
                              src={`/api/audio?path=${encodeURIComponent(c.recording_path)}`}
                              className="flex-1 h-9"
                            />
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                )) : (
                  <tr>
                    <td colSpan={6} className="py-16 text-center text-sm text-slate-400">
                      {search ? 'No calls match your search.' : 'No call records found.'}
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

function Skeleton() {
  return (
    <div className="p-8 space-y-3 animate-pulse">
      {[1,2,3,4].map(i => <div key={i} className="h-10 bg-slate-100 rounded-md" />)}
    </div>
  );
}
function InlineError({ message }: { message: string }) {
  return (
    <div className="m-8 bg-red-50 border border-red-200 rounded-lg p-4">
      <p className="text-sm text-red-700">{message}</p>
    </div>
  );
}
