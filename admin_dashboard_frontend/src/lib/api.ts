import { getToken } from './auth';
import type {
  AdminStats, FarmerProfile, CallLog,
  EscalationCase, KBEntry, MarketPrice, Alert,
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
  return res.json() as Promise<T>;
}

// ── Auth ──────────────────────────────────────────────────────────────────────
export async function apiLogin(username: string, password: string) {
  const res = await fetch(`${BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Login failed' }));
    throw new Error(err.detail ?? 'Invalid credentials');
  }
  return res.json() as Promise<{ token: string; role: 'admin' | 'expert'; username: string }>;
}

export async function apiLogout(): Promise<void> {
  await request('/logout', { method: 'POST' }).catch(() => {/* ignore */});
}

// ── Stats ─────────────────────────────────────────────────────────────────────
export async function fetchStats(): Promise<AdminStats> {
  return request('/stats');
}

// ── Farmers ───────────────────────────────────────────────────────────────────
export async function fetchFarmers(): Promise<FarmerProfile[]> {
  return request('/farmers');
}

// ── Calls ─────────────────────────────────────────────────────────────────────
export async function fetchCalls(): Promise<CallLog[]> {
  return request('/calls');
}

// ── Escalations ───────────────────────────────────────────────────────────────
export async function fetchEscalations(): Promise<EscalationCase[]> {
  return request('/escalations');
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

// ── Alerts ────────────────────────────────────────────────────────────────────
export async function fetchAlerts(): Promise<Alert[]> {
  return request('/alerts');
}

export async function createAlert(
  data: { target_region: string; alert_message: string; severity: string },
): Promise<void> {
  await request('/alerts', { method: 'POST', body: JSON.stringify(data) });
}

// ── Knowledge Base ────────────────────────────────────────────────────────────
export async function fetchKB(): Promise<KBEntry[]> {
  return request('/kb');
}

export async function addKBEntry(data: { intent: string; response: string }): Promise<{ id: string }> {
  return request('/kb', { method: 'POST', body: JSON.stringify(data) });
}

export async function deleteKBEntry(id: string): Promise<void> {
  await request(`/kb/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
