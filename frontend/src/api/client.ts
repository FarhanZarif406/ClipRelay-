import { PODCASTS } from "@/lib/mode";

const TOKEN_KEY = "cliprelay.token";
const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string, public detail?: unknown) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

export function apiUrl(path: string, query?: Query) {
  const params = new URLSearchParams();
  if (PODCASTS) params.set("mode", "podcasts");  // every request from the Podcasts window is about that workspace
  Object.entries(query ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  });
  const qs = params.toString();
  return `${BASE}/api${path}${qs ? `?${qs}` : ""}`;
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
    if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? String(d)).join("; ");
  }
  return fallback;
}

export async function api<T>(path: string, options: { method?: string; body?: unknown; query?: Query } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(apiUrl(path, options.query), {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  if (response.status === 401 && token) {
    setToken(null);
    window.dispatchEvent(new Event("cliprelay:unauthorized"));
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : undefined;
    const code = detail && typeof detail === "object" && "code" in detail ? String((detail as { code: unknown }).code) : undefined;
    throw new ApiError(errorMessage(body, `Request failed (${response.status})`), response.status, code, detail);
  }
  return body as T;
}

/** Download an authenticated file (CSV exports). */
export async function download(path: string, filename: string, query?: Query) {
  const response = await fetch(apiUrl(path, query), { headers: { Authorization: `Bearer ${getToken() ?? ""}` } });
  if (!response.ok) throw new ApiError(`Export failed (${response.status})`, response.status);
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
