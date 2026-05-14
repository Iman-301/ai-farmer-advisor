"use client";

import { useEffect, useState } from 'react';
import { fetchKB, addKBEntry, deleteKBEntry } from '@/lib/api';
import { isAdmin } from '@/lib/auth';
import type { KBEntry } from '@/types';
import Badge from '@/components/ui/Badge';

export default function KnowledgeBase() {
  const [entries, setEntries]   = useState<KBEntry[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [toast, setToast]       = useState('');
  const [intent, setIntent]     = useState('');
  const [response, setResponse] = useState('');
  const [saving, setSaving]     = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const admin = typeof window !== 'undefined' ? isAdmin() : false;

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 3000); };

  const load = () => {
    setLoading(true);
    fetchKB()
      .then(setEntries)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleSave = async () => {
    if (!intent.trim() || !response.trim()) return;
    setSaving(true);
    try {
      await addKBEntry({ intent: intent.trim(), response: response.trim() });
      setIntent(''); setResponse('');
      showToast('Entry added to ChromaDB ✓');
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    setDeleting(id);
    try {
      await deleteKBEntry(id);
      showToast('Entry deleted ✓');
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Delete failed');
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-slate-900 text-white text-sm font-medium px-4 py-2.5 rounded-lg shadow-lg">
          {toast}
        </div>
      )}

      {/* Editor — admin only */}
      <div className="lg:col-span-4">
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-8 mt-8 sticky top-8">
          {admin ? (
            <>
              <h3 className="text-base font-medium text-slate-800 mb-6">Add KB Entry</h3>
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label htmlFor="kb-intent" className="text-sm font-medium text-slate-700">
                    Intent Tag
                    <span className="text-xs font-normal text-slate-400 ml-1">(e.g. fertilizer_wheat)</span>
                  </label>
                  <input
                    id="kb-intent"
                    type="text"
                    value={intent}
                    onChange={(e) => setIntent(e.target.value)}
                    placeholder="crop_disease"
                    className="w-full h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"
                  />
                </div>
                <div className="space-y-1.5">
                  <label htmlFor="kb-response" className="text-sm font-medium text-slate-700">
                    Amharic Response
                  </label>
                  <textarea
                    id="kb-response"
                    rows={5}
                    value={response}
                    onChange={(e) => setResponse(e.target.value)}
                    placeholder="ወርቅ ላይ ፈንጂ ለማስቀረት..."
                    className="w-full p-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 resize-none"
                  />
                </div>
                <button
                  onClick={handleSave}
                  disabled={saving || !intent.trim() || !response.trim()}
                  className="w-full h-10 bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-sm font-medium rounded-md transition-colors"
                >
                  {saving ? 'Saving…' : 'Save to ChromaDB'}
                </button>
              </div>
            </>
          ) : (
            <div className="text-center py-6">
              <span className="text-3xl block mb-3">🔒</span>
              <p className="text-sm font-medium text-slate-700">Admin Only</p>
              <p className="text-sm text-slate-500 mt-1">Contact an administrator to add entries.</p>
            </div>
          )}
        </div>
      </div>

      {/* Entries list */}
      <div className="lg:col-span-8">
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden mt-8">
          <div className="px-8 py-6 border-b border-slate-100 flex items-center justify-between">
            <h3 className="text-base font-medium text-slate-800">ChromaDB Entries</h3>
            <Badge label={`${entries.length} Total`} variant="neutral" />
          </div>

          {loading && (
            <div className="p-8 space-y-3 animate-pulse">
              {[1,2,3].map(i => <div key={i} className="h-16 bg-slate-100 rounded-md" />)}
            </div>
          )}
          {error && (
            <div className="m-8 bg-red-50 border border-red-200 rounded-lg p-4">
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}

          {!loading && !error && (
            <div className="divide-y divide-slate-100">
              {entries.length > 0 ? entries.map((e) => (
                <div key={e.id} className="p-8 hover:bg-slate-50 transition-colors">
                  <div className="flex items-start justify-between gap-4 mb-3">
                    <div>
                      <code className="text-xs bg-green-50 text-green-700 border border-green-100 px-2 py-0.5 rounded font-mono">
                        {e.intent ?? e.id}
                      </code>
                    </div>
                    {admin && (
                      <button
                        onClick={() => handleDelete(e.id)}
                        disabled={deleting === e.id}
                        className="text-xs font-medium text-red-500 hover:text-red-700 disabled:opacity-50 shrink-0"
                      >
                        {deleting === e.id ? 'Deleting…' : 'Delete'}
                      </button>
                    )}
                  </div>
                  <p className="text-sm text-slate-600 leading-relaxed">
                    {(e.response ?? e.content ?? '').slice(0, 200)}
                    {((e.response ?? e.content ?? '').length > 200) ? '…' : ''}
                  </p>
                  <p className="text-xs text-slate-300 mt-2 font-mono">{e.id}</p>
                </div>
              )) : (
                <div className="py-16 text-center text-sm text-slate-400">
                  Knowledge base is empty. {admin ? 'Add an entry using the form.' : ''}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
