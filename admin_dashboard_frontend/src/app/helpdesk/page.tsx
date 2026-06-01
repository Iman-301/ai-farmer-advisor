"use client";

import { useEffect, useState } from 'react';
import {
  assignEscalation,
  closeEscalation,
  fetchEscalations,
  fetchUsers,
  respondEscalation,
  uploadEscalationAudio,
} from '@/lib/api';
import { getRole, getUserId, hasRole, getToken } from '@/lib/auth';
import type { DashboardUser, EscalationCase } from '@/types';
import Badge from '@/components/ui/Badge';
import AudioPlayer from '@/components/ui/AudioPlayer';

function statusLabel(s: string) {
  if (s === 'pending') return 'Pending';
  if (s === 'assigned') return 'Assigned';
  if (s === 'answered') return 'Answered';
  if (s === 'closed' || s === 'resolved') return 'Closed';
  return s;
}
function statusVariant(s: string): 'warning' | 'success' | 'info' | 'neutral' {
  if (s === 'pending') return 'warning';
  if (s === 'assigned') return 'info';
  if (s === 'answered') return 'success';
  if (s === 'closed' || s === 'resolved') return 'neutral';
  return 'neutral';
}

function withToken(url?: string | null) {
  if (!url) return '';
  const token = typeof window !== 'undefined' ? getToken() : null;
  if (!token) return url;
  return `${url}${url.includes('?') ? '&' : '?'}token=${token}`;
}

export default function Helpdesk() {
  const [cases, setCases]         = useState<EscalationCase[]>([]);
  const [selected, setSelected]   = useState<EscalationCase | null>(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [experts, setExperts]     = useState<DashboardUser[]>([]);
  const [busy, setBusy]           = useState(false);
  const [toast, setToast]         = useState('');
  const [pendingAudio, setPendingAudio] = useState<Blob | null>(null);
  const role = typeof window !== 'undefined' ? getRole() : null;
  const myUserId = typeof window !== 'undefined' ? getUserId() : null;

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

  useEffect(() => {
    if (!hasRole('admin', 'da')) return;
    fetchUsers()
      .then((users) => setExperts(users.filter((u) => u.role === 'expert' && u.is_active)))
      .catch(() => setExperts([]));
  }, []);

  const openCount     = cases.filter(c => c.status === 'pending' || c.status === 'assigned').length;
  const resolvedCount = cases.filter(c => c.status === 'answered' || c.status === 'closed' || c.status === 'resolved').length;

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 3000); };

  const handleAssign = async (expertUserId: string) => {
    if (!selected || selected.id == null) return;
    setBusy(true);
    try {
      await assignEscalation(selected.id, expertUserId);
      showToast(`Ticket #${selected.id} assigned ✓`);
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to assign');
    } finally {
      setBusy(false);
    }
  };

  const handleRespond = async (answer: string) => {
    if (!selected || selected.id == null) return;
    setBusy(true);
    try {
      if (pendingAudio) {
        await uploadEscalationAudio(selected.id, pendingAudio);
        setPendingAudio(null);
      }
      await respondEscalation(selected.id, answer);
      showToast(`Ticket #${selected.id} answered ✓`);
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to respond');
    } finally {
      setBusy(false);
    }
  };

  const handleClose = async () => {
    if (!selected || selected.id == null) return;
    setBusy(true);
    try {
      await closeEscalation(selected.id);
      showToast(`Ticket #${selected.id} closed ✓`);
      load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Failed to close');
    } finally {
      setBusy(false);
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

                  {/* Session record + transcription evidence pair */}
                  <div className="pt-4 border-t border-slate-100 space-y-4">
                    <span className="block text-xs font-semibold text-slate-500 uppercase tracking-wide">
                      Escalation evidence pair
                    </span>

                    <div className="bg-slate-50 p-4 rounded-md border border-slate-200 space-y-3">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium text-slate-800">Session record</p>
                          <p className="text-xs text-slate-500">
                            {selected.session_record?.session_id ?? selected.session_id ?? 'No session id'}
                            {selected.session_record?.status ? ` · ${selected.session_record.status}` : ''}
                          </p>
                        </div>
                      </div>
                      {selected.session_recording_url || selected.session_record?.audio_url ? (
                        <AudioPlayer
                          src={withToken(selected.session_recording_url ?? selected.session_record?.audio_url)}
                          label="Session audio"
                          detail={selected.session_record?.duration_seconds != null ? `${selected.session_record.duration_seconds}s` : undefined}
                          compact
                        />
                      ) : (
                        <span className="text-xs text-slate-400">Recording appears after the call ends.</span>
                      )}
                      {selected.session_recording_path && (
                        <p className="text-[11px] text-slate-400 font-mono break-all">
                          {selected.session_recording_path}
                        </p>
                      )}
                    </div>

                    <div className="bg-slate-50 p-4 rounded-md border border-slate-200">
                      <p className="text-sm font-medium text-slate-800 mb-3">Transcribed conversation</p>
                      {selected.transcript_messages && selected.transcript_messages.length > 0 ? (
                        <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                          {selected.transcript_messages.map((m, idx) => (
                            <div key={`${m.timestamp ?? 'msg'}-${idx}`} className="text-sm leading-relaxed">
                              <span className="font-semibold text-slate-700 capitalize">{m.role}: </span>
                              <span className="text-slate-600">{m.message}</span>
                            </div>
                          ))}
                        </div>
                      ) : selected.transcript ? (
                        <pre className="whitespace-pre-wrap text-sm text-slate-600 max-h-64 overflow-y-auto">
                          {selected.transcript}
                        </pre>
                      ) : (
                        <p className="text-sm text-slate-400">No transcript available yet.</p>
                      )}
                    </div>
                  </div>

                  {/* Assignment (admin/da) */}
                  {hasRole('admin', 'da') && (
                    <div className="pt-4 border-t border-slate-100 space-y-3">
                      <span className="block text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        Assignment
                      </span>
                      <div className="flex gap-2">
                        <select
                          defaultValue={selected.assigned_to?.user_id ?? ''}
                          onChange={(e) => {
                            const v = e.target.value;
                            if (v) handleAssign(v);
                          }}
                          className="flex-1 h-10 px-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 bg-white"
                          disabled={busy}
                        >
                          <option value="">Assign to expert…</option>
                          {experts.map((u) => (
                            <option key={u.user_id} value={u.user_id}>
                              {u.full_name} ({u.email})
                            </option>
                          ))}
                        </select>
                        <button
                          onClick={handleClose}
                          disabled={busy}
                          className="h-10 px-4 rounded-md bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-sm font-medium transition-colors"
                        >
                          Close
                        </button>
                      </div>
                      <p className="text-xs text-slate-400">
                        Current: {selected.assigned_to ? `${selected.assigned_to.full_name}` : 'Unassigned'}
                      </p>
                    </div>
                  )}

                  {/* Expert response */}
                  {hasRole('expert', 'admin') && (
                    <ExpertResponsePanel
                      caseItem={selected}
                      canRespond={
                        role === 'admin' ||
                        (role === 'expert' &&
                          !!myUserId &&
                          selected.assigned_to?.user_id === myUserId)
                      }
                      busy={busy}
                      onRespond={handleRespond}
                      onAudioUpload={setPendingAudio}
                    />
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

function ExpertResponsePanel({
  caseItem,
  canRespond,
  busy,
  onRespond,
  onAudioUpload,
}: {
  caseItem: EscalationCase;
  canRespond: boolean;
  busy: boolean;
  onRespond: (answer: string) => void;
  onAudioUpload: (blob: Blob) => void;
}) {
  const [answer, setAnswer] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [recorder, setRecorder] = useState<MediaRecorder | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);

  useEffect(() => {
    setAnswer(caseItem.expert_response ?? '');
  }, [caseItem.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];

      mediaRecorder.ondataavailable = (e) => chunks.push(e.data);
      mediaRecorder.onstop = () => {
        const blob = new Blob(chunks, { type: 'audio/wav' });
        setAudioUrl(URL.createObjectURL(blob));
        onAudioUpload(blob);
        stream.getTracks().forEach(track => track.stop());
      };

      mediaRecorder.start();
      setRecorder(mediaRecorder);
      setIsRecording(true);
    } catch (err) {
      console.error('Recording failed:', err);
    }
  };

  const stopRecording = () => {
    recorder?.stop();
    setIsRecording(false);
  };

  return (
    <div className="pt-4 border-t border-slate-100 space-y-4">
      <div className="flex items-center justify-between">
        <span className="block text-xs font-semibold text-slate-500 uppercase tracking-wide">
          Expert response
        </span>
      </div>
      {caseItem.expert_audio_url && (
        <AudioPlayer
          src={withToken(caseItem.expert_audio_url)}
          label="Expert audio"
          compact
        />
      )}

      {!canRespond && (
        <div className="bg-amber-50 border border-amber-200 rounded-md p-3 text-sm text-amber-800">
          This case must be assigned to you before you can answer.
        </div>
      )}

      <div className="space-y-3">
        <div className="flex items-center gap-2">
          {!isRecording ? (
            <button
              onClick={startRecording}
              disabled={!canRespond || busy}
              className="flex-1 h-10 flex items-center justify-center gap-2 rounded-md border border-slate-300 text-slate-700 text-sm font-medium hover:bg-slate-50 disabled:opacity-50 transition-colors"
            >
              <div className="w-2 h-2 rounded-full bg-red-500" />
              Record Voice Response
            </button>
          ) : (
            <button
              onClick={stopRecording}
              className="flex-1 h-10 flex items-center justify-center gap-2 rounded-md bg-red-50 text-red-700 text-sm font-medium border border-red-200 animate-pulse"
            >
              <div className="w-2 h-2 rounded-full bg-red-600" />
              Stop Recording...
            </button>
          )}
          {audioUrl && (
            <button
              onClick={() => setAudioUrl(null)}
              className="h-10 px-3 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-50"
              title="Clear recording"
            >
              ✕
            </button>
          )}
        </div>

        {audioUrl && (
          <AudioPlayer src={audioUrl} label="Preview" compact />
        )}

        <textarea
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          rows={4}
          className="w-full p-3 rounded-md border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 resize-none"
          placeholder="Or write the expert answer here…"
          disabled={!canRespond || busy}
        />
        
        <button
          onClick={() => onRespond(answer.trim())}
          disabled={!canRespond || busy || (!answer.trim() && !audioUrl)}
          className="w-full h-11 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-sm font-medium rounded-md shadow-sm transition-all active:scale-[0.98]"
        >
          {audioUrl ? 'Submit Voice & Text Response' : 'Submit Response'}
        </button>
      </div>
    </div>
  );
}
