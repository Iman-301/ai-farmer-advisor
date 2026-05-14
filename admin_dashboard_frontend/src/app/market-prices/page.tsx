"use client";

import { useEffect, useState } from 'react';
import { fetchMarketPrices, addMarketPrice } from '@/lib/api';
import { isAdmin } from '@/lib/auth';
import type { MarketPrice } from '@/types';

const REGIONS = ['Addis Ababa', 'Oromia', 'Amhara', 'SNNPR', 'Tigray', 'Sidama', 'Afar'];

export default function MarketPrices() {
  const [prices, setPrices]     = useState<MarketPrice[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [toast, setToast]       = useState('');
  const [saving, setSaving]     = useState(false);
  const admin = typeof window !== 'undefined' ? isAdmin() : false;

  // Form state
  const [crop, setCrop]     = useState('');
  const [region, setRegion] = useState('');
  const [price, setPrice]   = useState('');
  const [unit, setUnit]     = useState('');

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 3000); };

  const load = () => {
    setLoading(true);
    fetchMarketPrices()
      .then(setPrices)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!crop || !region || !price || !unit) return;
    setSaving(true);
    try {
      await addMarketPrice({ crop_name: crop.trim(), region, price: parseFloat(price), unit: unit.trim() });
      setCrop(''); setRegion(''); setPrice(''); setUnit('');
      showToast(`Price added for ${crop} in ${region} ✓`);
      load();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to add price');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-8">
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-slate-900 text-white text-sm font-medium px-4 py-2.5 rounded-lg shadow-lg">
          {toast}
        </div>
      )}

      {/* Add price form — admin only */}
      {admin ? (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden mt-8">
          <div className="px-8 py-6 border-b border-slate-100">
            <h3 className="text-base font-medium text-slate-800">Add / Update Price</h3>
          </div>
          <form onSubmit={handleSubmit} className="p-8">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              <div className="space-y-1.5">
                <label htmlFor="mp-crop" className="text-sm font-medium text-slate-700">Crop Name</label>
                <input
                  id="mp-crop" type="text" required
                  placeholder="e.g. Teff"
                  value={crop} onChange={(e) => setCrop(e.target.value)}
                  className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="mp-region" className="text-sm font-medium text-slate-700">Region</label>
                <select
                  id="mp-region" required
                  value={region} onChange={(e) => setRegion(e.target.value)}
                  className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 bg-white"
                >
                  <option value="" disabled>Select region…</option>
                  {REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="mp-price" className="text-sm font-medium text-slate-700">Price (ETB)</label>
                <input
                  id="mp-price" type="number" min="0" step="0.01" required
                  placeholder="0.00"
                  value={price} onChange={(e) => setPrice(e.target.value)}
                  className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="mp-unit" className="text-sm font-medium text-slate-700">Unit</label>
                <input
                  id="mp-unit" type="text" required
                  placeholder="e.g. Kg, Quintal"
                  value={unit} onChange={(e) => setUnit(e.target.value)}
                  className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={saving}
              className="h-10 px-6 bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-sm font-medium rounded-md transition-colors"
            >
              {saving ? 'Adding…' : '➕ Add Price'}
            </button>
          </form>
        </div>
      ) : (
        <div className="mt-8 bg-blue-50 border border-blue-200 rounded-xl p-6">
          <p className="text-sm font-medium text-blue-700">👀 View only — only admins can add prices.</p>
        </div>
      )}

      {/* Price database table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="px-8 py-6 border-b border-slate-100">
          <h3 className="text-base font-medium text-slate-800">
            Current Price Database
            {!loading && <span className="ml-2 text-sm font-normal text-slate-400">({prices.length} entries)</span>}
          </h3>
        </div>

        {loading && (
          <div className="p-8 space-y-3 animate-pulse">
            {[1,2,3,4].map(i => <div key={i} className="h-10 bg-slate-100 rounded" />)}
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
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Crop</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Region</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Price (ETB)</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Unit</th>
                  <th className="py-4 px-8 text-xs font-semibold text-slate-500 uppercase tracking-wide">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {prices.length > 0 ? prices.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-50 transition-colors">
                    <td className="py-4 px-8 text-sm font-medium text-slate-900">{p.crop_name}</td>
                    <td className="py-4 px-8 text-sm text-slate-600">{p.region}</td>
                    <td className="py-4 px-8 text-sm font-semibold text-green-700">{p.price.toFixed(2)}</td>
                    <td className="py-4 px-8 text-sm text-slate-600">{p.unit}</td>
                    <td className="py-4 px-8 text-sm text-slate-400">
                      {p.updated_at ? new Date(p.updated_at).toLocaleString() : '—'}
                    </td>
                  </tr>
                )) : (
                  <tr>
                    <td colSpan={5} className="py-16 text-center text-sm text-slate-400">
                      No market prices yet. {admin ? 'Use the form above to add one.' : ''}
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
