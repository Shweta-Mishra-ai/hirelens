/**
 * HireLens — Typed API Client
 * Fixed:
 * - Network error handling (fetch can throw TypeError)
 * - Response content-type check before .json()
 * - Timeout handling
 * - 204 No Content handled correctly
 */
import type { Report, AnalysisJob, User } from "@/types";

const BASE =
  (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

// ── Error type ────────────────────────────────────────────────────────────────
export class APIError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly requestId?: string,
  ) {
    super(message);
    this.name = "APIError";
  }
}

// ── Core request function ─────────────────────────────────────────────────────
async function req<T>(
  path: string,
  init: RequestInit & { token?: string } = {},
): Promise<T> {
  const { token, ...rest } = init;

  const headers: Record<string, string> = {
    ...(rest.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  // Only set Content-Type for non-FormData bodies
  if (rest.body && !(rest.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...rest,
      headers,
      // 60 second timeout via AbortController
      signal: rest.signal ?? AbortSignal.timeout(60_000),
    });
  } catch (e) {
    if (e instanceof Error) {
      if (e.name === "TimeoutError" || e.name === "AbortError") {
        throw new APIError(0, "timeout", "Request timed out. Please try again.");
      }
      if (e.name === "TypeError") {
        throw new APIError(
          0,
          "network_error",
          "Cannot reach the server. Check your internet connection.",
        );
      }
    }
    throw new APIError(0, "unknown", "An unexpected error occurred.");
  }

  // 204 No Content
  if (res.status === 204) return undefined as T;

  // Parse response body
  const contentType = res.headers.get("content-type") || "";
  let body: unknown;

  if (contentType.includes("application/json")) {
    body = await res.json().catch(() => ({}));
  } else {
    body = await res.text().catch(() => "");
  }

  if (!res.ok) {
    const b = typeof body === "object" && body !== null ? (body as Record<string, string>) : {};
    throw new APIError(
      res.status,
      b["error"] ?? "http_error",
      b["message"] ?? `Server error ${res.status}`,
      b["request_id"],
    );
  }

  return body as T;
}

// ── Auth ──────────────────────────────────────────────────────────────────────
export const authAPI = {
  login: (email: string, password: string) =>
    req<{ access_token: string; user: User }>(
      "/api/v1/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) },
    ),

  signup: (data: {
    email: string;
    password: string;
    full_name: string;
    company?: string;
  }) =>
    req<{
      access_token: string | null;
      user: User;
      requires_email_confirmation?: boolean;
    }>("/api/v1/auth/signup", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  me: (token: string) =>
    req<{ id: string; email: string }>("/api/v1/auth/me", { token }),

  oauthVerify: (accessToken: string) =>
    req<{ access_token: string; user: User }>(
      "/api/v1/auth/oauth-verify",
      { method: "POST", body: JSON.stringify({ access_token: accessToken }) },
    ),
};

// ── Analysis ──────────────────────────────────────────────────────────────────
export const analysisAPI = {
  upload: (file: File, token: string) => {
    const form = new FormData();
    form.append("file", file);
    return req<{ job_id: string; status: string }>(
      "/api/v1/analysis/upload",
      { method: "POST", body: form, token },
    );
  },

  status: (jobId: string, token: string) =>
    req<AnalysisJob>(`/api/v1/analysis/${jobId}/status`, { token }),
};

// ── Reports ───────────────────────────────────────────────────────────────────
export const reportsAPI = {
  list: (
    token: string,
    params?: { page?: number; recommendation?: string },
  ) => {
    const qs = new URLSearchParams();
    if (params?.page) qs.set("page", String(params.page));
    if (params?.recommendation) qs.set("recommendation", params.recommendation);
    return req<{ reports: Report[]; total: number; pages: number }>(
      `/api/v1/reports?${qs.toString()}`,
      { token },
    );
  },

  get: (id: string, token: string) =>
    req<Report>(`/api/v1/reports/${id}`, { token }),

  decision: (
    id: string,
    decision: string,
    notes: string | undefined,
    token: string,
  ) =>
    req<{ status: string }>(`/api/v1/reports/${id}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, notes }),
      token,
    }),

  delete: (id: string, token: string) =>
    req<void>(`/api/v1/reports/${id}`, { method: "DELETE", token }),
};

// ── Health ────────────────────────────────────────────────────────────────────
export const healthAPI = {
  check: () =>
    req<{ status: string; version: string; llm_ready: boolean }>(
      "/api/v1/health",
    ),
};
