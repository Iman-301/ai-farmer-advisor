"use client";

import { useEffect, useState } from 'react';
import { fetchFarmers } from '@/lib/api';
import type { FarmerProfile } from '@/types';
import { X } from 'lucide-react';

export default function FarmerProfiles() {
  const [farmers, setFarmers]             = useState<FarmerProfile[]>([]);
  const [loading, setLoading]             = useState(true);
  const [error, setError]                 = useState('');
  const [selected, setSelected]           = useState<FarmerProfile | null>(null);
  const [search, setSearch]               = useState('');

  useEffect(() => {
    fetchFarmers()
      .then(setFarmers)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = farmers.filter((f) => {
    const q = search.toLowerCase();
    return (
      (f.name ?? '').toLowerCase().includes(q) ||
      (f.phone_number ?? '').includes(q) ||
      (f.location ?? '').toLowerCase().includes(q)
    );
  });

  return (
    <div>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="px-10 py-6 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <h3 className="text-base font-medium text-slate-800">
            Active Profiles
            {!loading && <span className="ml-2 text-sm font-normal text-slate-400">({farmers.length})</span>}
          </h3>
          <input
            type="search"
            placeholder="Search by name, phone, location…"
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
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Name</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Phone</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Location</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Language</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Registered</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.length > 0 ? filtered.map((f) => (
                  <tr key={f.id ?? f.farmer_id} className="hover:bg-slate-50 transition-colors">
                    <td className="py-4 px-8 text-sm font-medium text-slate-900">#{f.id}</td>
                    <td className="py-4 px-8 text-sm text-slate-800">{f.name ?? '—'}</td>
                    <td className="py-4 px-8 text-sm text-slate-600 font-mono">{f.phone_number}</td>
                    <td className="py-4 px-8 text-sm text-slate-600">{f.location ?? '—'}</td>
                    <td className="py-4 px-8 text-sm text-slate-600 capitalize">{f.language ?? '—'}</td>
                    <td className="py-4 px-8 text-sm text-slate-600">
                      {f.registered_at ? new Date(f.registered_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="py-4 px-8 text-right">
                      <button
                        onClick={() => setSelected(f)}
                        className="text-sm font-medium text-blue-600 hover:text-blue-700"
                      >
                        View
                      </button>
                    </td>
                  </tr>
                )) : (
                  <tr>
                    <td colSpan={7} className="py-16 text-center text-sm text-slate-400">
                      {search ? 'No farmers match your search.' : 'No farmers registered yet.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Detail modal */}
      {selected && (
        <div className="fixed inset-0 bg-slate-900/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-lg w-full max-w-md border border-slate-200 overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <h3 className="text-base font-medium text-slate-800">Farmer Profile</h3>
              <button onClick={() => setSelected(null)} className="text-slate-400 hover:text-slate-600">
                <X size={20} />
              </button>
            </div>

            <div className="p-6 space-y-6">
              <div className="flex items-center gap-4">
                <div className="w-14 h-14 rounded-full bg-green-100 flex items-center justify-center text-green-700 font-semibold text-lg">
                  {(selected.name ?? selected.phone_number ?? '?').slice(0, 2).toUpperCase()}
                </div>
                <div>
                  <h4 className="text-base font-medium text-slate-900">{selected.name ?? 'Unknown'}</h4>
                  <p className="text-sm text-slate-500 font-mono">{selected.phone_number}</p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-x-6 gap-y-4">
                <Detail label="Farmer ID"  value={`#${selected.id}`} />
                <Detail label="Language"   value={selected.language ?? '—'} />
                <Detail label="Location"   value={selected.location ?? '—'} />
                <Detail label="Registered" value={selected.registered_at ? new Date(selected.registered_at).toLocaleDateString() : '—'} />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="block text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">{label}</span>
      <span className="text-sm text-slate-900">{value}</span>
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
