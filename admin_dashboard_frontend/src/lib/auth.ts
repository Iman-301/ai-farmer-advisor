import type { SessionData, UserRole } from "@/types";

export type DashboardRole = UserRole;

/** Default 1 hour session timeout */
export const SESSION_TIMEOUT_MS = 60 * 60 * 1000;

/**
 * Browser-side admin API base.
 *
 * This is relative because the browser talks to Next.js:
 *   /api/admin/login
 *
 * Next.js then proxies to logic-service:
 *   http://logic-service:8000/admin/login
 */
const ADMIN_API_BASE = "/api/admin";

type LoginPayload = {
  email: string;
  password: string;
};

/**
 * Expected logic-service login response.
 *
 * Supports both possible shapes:
 *
 * Shape 1:
 * {
 *   "token": "...",
 *   "role": "admin",
 *   "username": "System Admin",
 *   "email": "admin@example.com",
 *   "user_id": "...",
 *   "full_name": "System Admin",
 *   "expires_in": 3600
 * }
 *
 * Shape 2:
 * {
 *   "access_token": "...",
 *   "user": {
 *     "user_id": "...",
 *     "full_name": "System Admin",
 *     "email": "admin@example.com",
 *     "role": "admin"
 *   }
 * }
 */
type LoginResponse = {
  token?: string;
  access_token?: string;
  expires_in?: number;

  role?: DashboardRole;
  username?: string;
  email?: string;
  user_id?: string;
  full_name?: string;

  user?: {
    user_id?: string;
    full_name?: string;
    email?: string;
    role?: DashboardRole;
  };
};

export async function loginUser(payload: LoginPayload): Promise<SessionData> {
  const response = await fetch(`${ADMIN_API_BASE}/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let message = "Login failed";

    try {
      const errorData = await response.json();
      message = errorData.detail || errorData.message || message;
    } catch {
      // ignore non-JSON error
    }

    throw new Error(message);
  }

  const data: LoginResponse = await response.json();

  const token = data.token || data.access_token || "";

  const role = data.user?.role || data.role;
  const email = data.user?.email || data.email || payload.email;
  const fullName =
    data.user?.full_name ||
    data.full_name ||
    data.username ||
    email;

  const userId = data.user?.user_id || data.user_id || "";

  if (!token) {
    throw new Error("Login response did not include token");
  }

  if (!role) {
    throw new Error("Login response did not include role");
  }

  const expiresInMs =
    typeof data.expires_in === "number"
      ? data.expires_in * 1000
      : SESSION_TIMEOUT_MS;

  const session: SessionData = {
    token,
    userId,
    username: fullName,
    email,
    fullName,
    role,
    loginTime: Date.now(),
    expiresAt: Date.now() + expiresInMs,
  };

  if (typeof window !== "undefined") {
    localStorage.setItem("session", JSON.stringify(session));
  }

  return session;
}

export function saveSession(data: Omit<SessionData, "loginTime">): void {
  if (typeof window === "undefined") return;

  const session: SessionData = {
    ...data,
    loginTime: Date.now(),
    expiresAt: data.expiresAt ?? Date.now() + SESSION_TIMEOUT_MS,
  };

  localStorage.setItem("session", JSON.stringify(session));
}

export function getSession(): SessionData | null {
  if (typeof window === "undefined") return null;

  const raw = localStorage.getItem("session");

  if (!raw) return null;

  try {
    const session: SessionData = JSON.parse(raw);

    const expiresAt =
      session.expiresAt ?? session.loginTime + SESSION_TIMEOUT_MS;

    if (Date.now() >= expiresAt) {
      clearSession();
      return null;
    }

    return session;
  } catch {
    clearSession();
    return null;
  }
}

export function clearSession(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem("session");
  }
}

export function getToken(): string | null {
  return getSession()?.token ?? null;
}

export function getRole(): DashboardRole | null {
  return getSession()?.role ?? null;
}

export function getUsername(): string | null {
  return getSession()?.username ?? null;
}

export function getUserId(): string | null {
  return getSession()?.userId ?? null;
}

export function getEmail(): string | null {
  return getSession()?.email ?? null;
}

export function getFullName(): string | null {
  return getSession()?.fullName ?? null;
}

export function isAdmin(): boolean {
  return getRole() === "admin";
}

export function isDA(): boolean {
  return getRole() === "da";
}

export function isExpert(): boolean {
  return getRole() === "expert";
}

export function hasRole(...roles: DashboardRole[]): boolean {
  const role = getRole();
  return role ? roles.includes(role) : false;
}

export function getSessionTimeRemaining(): number {
  const session = getSession();

  if (!session) return 0;

  const expiresAt =
    session.expiresAt ?? session.loginTime + SESSION_TIMEOUT_MS;

  return Math.max(0, expiresAt - Date.now());
}

/**
 * Authenticated fetch through the Next.js proxy.
 *
 * Example:
 *   authFetch("/api/admin/stats")
 */
export async function authFetch(
  input: string,
  init: RequestInit = {}
): Promise<Response> {
  const token = getToken();

  if (!token) {
    throw new Error("Not authenticated");
  }

  return fetch(input, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init.headers || {}),
    },
  });
}

export async function fetchCurrentUser() {
  const response = await authFetch(`${ADMIN_API_BASE}/me`);

  if (!response.ok) {
    clearSession();
    throw new Error("Session expired or invalid");
  }

  return response.json();
}