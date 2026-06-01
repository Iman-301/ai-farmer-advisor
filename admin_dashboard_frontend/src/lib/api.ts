import { getToken } from './auth';
import type {
  AdminStats,
  Alert,
  AnalyticsSummary,
  CallDetail,
  CallLog,
  DashboardUser,
  DAPerformance,
  EscalationCase,
  ExpertPerformance,
  FarmerProfile,
  InteractionRecord,
  KBDocument,
  KBEntry,
  MarketPrice,
  SystemStatus,
} from '@/types';

const BASE = '/api/admin';

/** Generic authenticated fetch helper. Throws with a user-friendly message on error. */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string>),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? 'Request failed');
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ── Auth ──────────────────────────────────────────────────────────────────────
export async function apiLogin(email: string, password: string) {
  const res = await fetch(`${BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Login failed' }));
    throw new Error(err.detail ?? 'Invalid credentials');
  }
  return res.json();
}

export async function apiLogout(): Promise<void> {
  await request('/logout', { method: 'POST' }).catch(() => {/* ignore */});
}

export async function fetchMe(): Promise<DashboardUser> {
  return request('/me');
}

// ── Stats ─────────────────────────────────────────────────────────────────────
export async function fetchStats(): Promise<AdminStats> {
  return request('/stats');
}

// ── Users (admin only) ───────────────────────────────────────────────────────
export async function fetchUsers(): Promise<DashboardUser[]> {
  return request('/users');
}

export async function createUser(data: {
  full_name: string;
  email: string;
  password: string;
  role: 'admin' | 'da' | 'expert';
  is_active?: boolean;
}): Promise<DashboardUser> {
  return request('/users', { method: 'POST', body: JSON.stringify(data) });
}

export async function updateUser(
  user_id: string,
  data: Partial<{
    full_name: string;
    role: 'admin' | 'da' | 'expert';
    is_active: boolean;
    password: string;
  }>,
): Promise<DashboardUser> {
  return request(`/users/${encodeURIComponent(user_id)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deactivateUser(user_id: string): Promise<void> {
  await request(`/users/${encodeURIComponent(user_id)}`, { method: 'DELETE' });
}

// ── Farmers ───────────────────────────────────────────────────────────────────
export async function fetchFarmers(): Promise<FarmerProfile[]> {
  return request('/farmers');
}

export async function fetchFarmer(phone: string): Promise<FarmerProfile> {
  return request(`/farmers/${encodeURIComponent(phone)}`);
}

export async function fetchFarmerCalls(phone: string): Promise<CallLog[]> {
  return request(`/farmers/${encodeURIComponent(phone)}/calls`);
}

// ── Calls ─────────────────────────────────────────────────────────────────────
export async function fetchCalls(): Promise<CallLog[]> {
  return request('/calls');
}

export async function fetchCallDetail(session_id: string): Promise<CallDetail> {
  return request(`/calls/${encodeURIComponent(session_id)}`);
}

// ── Interaction Records ───────────────────────────────────────────────────────
export async function fetchInteractionRecords(params?: {
  phone_number?: string;
  session_id?: string;
  limit?: number;
}): Promise<InteractionRecord[]> {
  const qs = new URLSearchParams();
  if (params?.phone_number) qs.set('phone_number', params.phone_number);
  if (params?.session_id) qs.set('session_id', params.session_id);
  if (params?.limit != null) qs.set('limit', String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return request(`/interaction-records${suffix}`);
}

// ── Escalations ───────────────────────────────────────────────────────────────
export async function fetchEscalations(status?: string): Promise<EscalationCase[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : '';
  return request(`/escalations${qs}`);
}

export async function fetchMyEscalations(): Promise<EscalationCase[]> {
  return request('/escalations/mine');
}

export async function assignEscalation(id: number, user_id: string): Promise<EscalationCase> {
  return request(`/escalations/${id}/assign`, {
    method: 'POST',
    body: JSON.stringify({ user_id }),
  });
}

export async function respondEscalation(id: number, answer: string): Promise<EscalationCase> {
  return request(`/escalations/${id}/response`, {
    method: 'POST',
    body: JSON.stringify({ answer }),
  });
}

export async function closeEscalation(id: number): Promise<EscalationCase> {
  return request(`/escalations/${id}/close`, { method: 'POST' });
}

export async function uploadEscalationAudio(id: number, audioBlob: Blob): Promise<EscalationCase> {
  const token = getToken();
  const form = new FormData();
  form.append('audio_file', audioBlob, 'response.wav');
  
  const res = await fetch(`${BASE}/escalations/${id}/audio-response`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? 'Audio upload failed');
  }
  return res.json();
}

export async function resolveEscalation(id: number): Promise<void> {
  await request(`/escalations/${id}/resolve`, { method: 'PUT' });
}

// ── Market Prices ─────────────────────────────────────────────────────────────
export async function fetchMarketPrices(): Promise<MarketPrice[]> {
  return request('/market-prices');
}

export async function addMarketPrice(
  data: { crop_name: string; region: string; price: number; unit: string },
): Promise<void> {
  await request('/market-prices', { method: 'POST', body: JSON.stringify(data) });
}

export async function deleteMarketPrice(id: number): Promise<void> {
  await request(`/market-prices/${id}`, { method: 'DELETE' });
}

// ── Alerts ────────────────────────────────────────────────────────────────────
export async function fetchAlerts(): Promise<Alert[]> {
  return request('/alerts');
}

export async function createAlert(
  data: {
    target_region: string;
    alert_message: string;
    severity: string;
    category?: string;
    scheduled_at?: string | null;
    notify_by_call?: boolean;
  },
): Promise<void> {
  await request('/alerts', { method: 'POST', body: JSON.stringify(data) });
}

export async function deleteAlert(id: number): Promise<void> {
  await request(`/alerts/${id}`, { method: 'DELETE' });
}

// ── Knowledge Base (raw intents) ──────────────────────────────────────────────
export async function fetchKB(): Promise<KBEntry[]> {
  return request('/kb');
}

export async function addKBEntry(data: { intent: string; response: string }): Promise<{ id: string }> {
  return request('/kb', { method: 'POST', body: JSON.stringify(data) });
}

export async function deleteKBEntry(id: string): Promise<void> {
  await request(`/kb/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

// ── Knowledge Base Documents ─────────────────────────────────────────────────
export async function fetchKBDocuments(): Promise<KBDocument[]> {
  return request('/kb/documents');
}

export async function uploadKBDocument(
  file: File,
  meta: { title?: string; description?: string; topic?: string; crop?: string; region?: string; category?: string } = {},
): Promise<KBDocument> {
  const token = getToken();
  const form = new FormData();
  form.append('file', file);
  Object.entries(meta).forEach(([k, v]) => {
    if (v) form.append(k, v);
  });
  const res = await fetch(`${BASE}/kb/documents`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? 'Upload failed');
  }
  return res.json();
}

export async function updateKBDocument(
  id: string,
  data: Partial<{ title: string; description: string; topic: string; crop: string; region: string; category: string }>,
): Promise<KBDocument> {
  return request(`/kb/documents/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function approveKBDocument(id: string): Promise<KBDocument> {
  return request(`/kb/documents/${encodeURIComponent(id)}/approve`, { method: 'POST' });
}

export async function rejectKBDocument(id: string): Promise<KBDocument> {
  return request(`/kb/documents/${encodeURIComponent(id)}/reject`, { method: 'POST' });
}

export async function reindexKBDocument(id: string): Promise<KBDocument> {
  return request(`/kb/documents/${encodeURIComponent(id)}/reindex`, { method: 'POST' });
}

export async function deleteKBDocument(id: string): Promise<void> {
  await request(`/kb/documents/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

// ── Monitoring ───────────────────────────────────────────────────────────────
export async function fetchSystemStatus(): Promise<SystemStatus> {
  return request('/system-status');
}

// ── Analytics ────────────────────────────────────────────────────────────────
export async function fetchAnalyticsSummary(): Promise<AnalyticsSummary> {
  return request('/analytics/summary');
}

export async function fetchCommonQuestions(limit = 10): Promise<{ question: string; count: number }[]> {
  return request(`/analytics/common-questions?limit=${limit}`);
}

export async function fetchCallsBreakdown(by: 'date' | 'region' | 'language' = 'date'): Promise<{ key: string; count: number }[]> {
  return request(`/analytics/calls-breakdown?by=${by}`);
}

export async function fetchExpertPerformance(): Promise<ExpertPerformance[]> {
  return request('/analytics/expert-performance');
}

export async function fetchDAPerformance(): Promise<DAPerformance[]> {
  return request('/analytics/da-performance');
}

// ── Exports ──────────────────────────────────────────────────────────────────
export function exportCsvUrl(resource: 'calls' | 'farmers' | 'escalations' | 'market-prices' | 'alerts'): string {
  return `${BASE}/export/${resource}.csv`;
}

export async function downloadCsv(resource: 'calls' | 'farmers' | 'escalations' | 'market-prices' | 'alerts'): Promise<void> {
  const token = getToken();
  const res = await fetch(exportCsvUrl(resource), {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? 'Export failed');
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${resource}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
