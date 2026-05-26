"use client";
// Tiny API client — auto-attaches Bearer token, raises typed errors.

export const API_BASE =
  (process.env.NEXT_PUBLIC_BACKEND_URL || '').replace(/\/$/, '') + '/api';

const TOKEN_KEY = 'posuhtik.access_token';
const REFRESH_KEY = 'posuhtik.refresh_token';
const USER_KEY = 'posuhtik.user';

export type AuthUser = {
  user_id: string;
  role: string;
  name: string | null;
  approved: boolean;
};

export const auth = {
  getAccessToken(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(TOKEN_KEY);
  },
  getRefreshToken(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(REFRESH_KEY);
  },
  getUser(): AuthUser | null {
    if (typeof window === 'undefined') return null;
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  },
  setTokens(access: string, refresh: string, user: AuthUser) {
    localStorage.setItem(TOKEN_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  logout() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
  },
};

export class ApiError extends Error {
  status: number;
  body: any;
  constructor(status: number, body: any, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

type Options = {
  method?: string;
  body?: any;
  query?: Record<string, string | number | undefined | null>;
  auth?: boolean;
  signal?: AbortSignal;
};

export async function apiFetch<T = any>(path: string, opts: Options = {}): Promise<T> {
  const { method = 'GET', body, query, auth: useAuth = true, signal } = opts;
  let url = `${API_BASE}${path}`;
  if (query) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null) q.append(k, String(v));
    }
    const qs = q.toString();
    if (qs) url += `?${qs}`;
  }
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (useAuth) {
    const t = auth.getAccessToken();
    if (t) headers['Authorization'] = `Bearer ${t}`;
  }
  const res = await fetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });
  const text = await res.text();
  const data = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) {
    const msg =
      (data && (data.detail?.message || data.detail || data.message)) ||
      res.statusText ||
      'request failed';
    throw new ApiError(res.status, data, typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data as T;
}
