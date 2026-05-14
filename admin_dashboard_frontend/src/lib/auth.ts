import type { SessionData } from '@/types';

/** 1 hour — matches backend SESSION_TIMEOUT_SECONDS = 3600 */
export const SESSION_TIMEOUT_MS = 60 * 60 * 1000;

export function saveSession(data: Omit<SessionData, 'loginTime'>): void {
  if (typeof window === 'undefined') return;
  const session: SessionData = { ...data, loginTime: Date.now() };
  localStorage.setItem('session', JSON.stringify(session));
}

export function getSession(): SessionData | null {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem('session');
  if (!raw) return null;
  try {
    const session: SessionData = JSON.parse(raw);
    if (Date.now() - session.loginTime > SESSION_TIMEOUT_MS) {
      clearSession();
      return null;
    }
    return session;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  if (typeof window !== 'undefined') {
    localStorage.removeItem('session');
  }
}

export function getToken(): string | null {
  return getSession()?.token ?? null;
}

export function getRole(): 'admin' | 'expert' | null {
  return getSession()?.role ?? null;
}

export function getUsername(): string | null {
  return getSession()?.username ?? null;
}

export function isAdmin(): boolean {
  return getRole() === 'admin';
}

/** Returns milliseconds remaining in the current session (0 if expired / not logged in). */
export function getSessionTimeRemaining(): number {
  const session = getSession();
  if (!session) return 0;
  return Math.max(0, SESSION_TIMEOUT_MS - (Date.now() - session.loginTime));
}
