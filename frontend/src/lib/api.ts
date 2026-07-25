/**
 * HireLens — Typed API Client
 * Fixed:
 * - Network error handling (fetch can throw TypeError)
 * - Response content-type check before .json()
 * - Timeout handling
 * - 204 No Content handled correctly
 */
import type { Report, AnalysisJob, User, BulkUploadResponse, BatchStatus, MatchBatchStatus, VerificationResult, DuplicateCheckResult, Team, TeamMember, ReportComment, VotesResult } from "@/types";

const BASE =
  (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export const API_BASE = BASE;

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

// ── Bulk Upload (Feature 1) ─────────────────────────────────────────────────
export const bulkAPI = {
  upload: (files: File[], token: string) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return req<BulkUploadResponse>("/api/v1/bulk/upload", {
      method: "POST",
      body: form,
      token,
    });
  },

  status: (batchId: string, token: string) =>
    req<BatchStatus>(`/api/v1/bulk/${batchId}/status`, { token }),

  checkDuplicates: (batchId: string, token: string) =>
    req<DuplicateCheckResult>(`/api/v1/bulk/${batchId}/duplicates`, { token }),

  importFromAts: (csvFile: File, token: string) => {
    const form = new FormData();
    form.append("file", csvFile);
    return req<{
      batch_id: string;
      detected_columns: { name: string | null; email: string | null; resume_url: string | null };
      total_rows: number;
      queued: number;
      skipped_at_parse: { row_num: number; reason: string }[];
      skipped_at_download: { row_num: number; status: string }[];
      message: string;
    }>("/api/v1/ats/import", { method: "POST", body: form, token });
  },

  // Downloads the ranked-candidate CSV as a Blob (fetched with the auth
  // header, since a plain <a href> link can't attach Authorization).
  downloadCsv: async (batchId: string, token: string): Promise<Blob> => {
    const res = await fetch(`${BASE}/api/v1/bulk/${batchId}/export.csv`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      throw new APIError(res.status, "export_failed", "Could not export CSV. Please try again.");
    }
    return res.blob();
  },
};

// ── JD Match (Feature 2) ────────────────────────────────────────────────────
export interface JdInput {
  text?: string;
  file?: File;
}

export const matchAPI = {
  upload: (files: File[], jd: JdInput, token: string) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    if (jd.text && jd.text.trim()) form.append("jd_text", jd.text.trim());
    if (jd.file) form.append("jd_file", jd.file);
    return req<BulkUploadResponse>("/api/v1/match/upload", {
      method: "POST",
      body: form,
      token,
    });
  },

  status: (batchId: string, token: string) =>
    req<MatchBatchStatus>(`/api/v1/match/${batchId}/status`, { token }),

  downloadCsv: async (batchId: string, token: string): Promise<Blob> => {
    const res = await fetch(`${BASE}/api/v1/match/${batchId}/export.csv`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      throw new APIError(res.status, "export_failed", "Could not export CSV. Please try again.");
    }
    return res.blob();
  },
};

// ── Public Data Verification (Feature 3) ────────────────────────────────────
export const verifyAPI = {
  run: (reportId: string, githubUsername: string | undefined, token: string) =>
    req<VerificationResult>(`/api/v1/verify/${reportId}/run`, {
      method: "POST",
      body: JSON.stringify({ github_username: githubUsername || null }),
      token,
    }),

  get: (reportId: string, token: string) =>
    req<VerificationResult>(`/api/v1/verify/${reportId}`, { token }),
};

// ── Teams (Team Collaboration) ──────────────────────────────────────────────
export const teamsAPI = {
  list: (token: string) => req<{ teams: Team[] }>("/api/v1/teams", { token }),

  create: (name: string, token: string) =>
    req<Team>("/api/v1/teams", { method: "POST", body: JSON.stringify({ name }), token }),

  members: (teamId: string, token: string) =>
    req<{ members: TeamMember[] }>(`/api/v1/teams/${teamId}/members`, { token }),

  invite: (teamId: string, email: string, token: string) =>
    req<{ status: string; email?: string }>(`/api/v1/teams/${teamId}/invite`, {
      method: "POST", body: JSON.stringify({ email }), token,
    }),

  removeMember: (teamId: string, userId: string, token: string) =>
    req<{ status: string }>(`/api/v1/teams/${teamId}/members/${userId}`, { method: "DELETE", token }),

  delete: (teamId: string, token: string) =>
    req<{ status: string }>(`/api/v1/teams/${teamId}`, { method: "DELETE", token }),
};

// ── Report Collaboration (share, comments, votes) ───────────────────────────
export const collaborationAPI = {
  share: (reportId: string, teamId: string, token: string) =>
    req<{ status: string; team_id: string }>(`/api/v1/reports/${reportId}/share`, {
      method: "POST", body: JSON.stringify({ team_id: teamId }), token,
    }),

  unshare: (reportId: string, token: string) =>
    req<{ status: string }>(`/api/v1/reports/${reportId}/unshare`, { method: "POST", token }),

  listComments: (reportId: string, token: string) =>
    req<{ comments: ReportComment[] }>(`/api/v1/reports/${reportId}/comments`, { token }),

  addComment: (reportId: string, comment: string, token: string) =>
    req<ReportComment>(`/api/v1/reports/${reportId}/comments`, {
      method: "POST", body: JSON.stringify({ comment }), token,
    }),

  deleteComment: (reportId: string, commentId: string, token: string) =>
    req<{ status: string }>(`/api/v1/reports/${reportId}/comments/${commentId}`, { method: "DELETE", token }),

  listVotes: (reportId: string, token: string) =>
    req<VotesResult>(`/api/v1/reports/${reportId}/votes`, { token }),

  vote: (reportId: string, vote: "advance" | "reject" | "maybe", token: string) =>
    req<{ status: string; vote: string }>(`/api/v1/reports/${reportId}/vote`, {
      method: "POST", body: JSON.stringify({ vote }), token,
    }),
};

// ── Reports ───────────────────────────────────────────────────────────────────
export const reportsAPI = {
  list: (
    token: string,
    params?: { page?: number; recommendation?: string; search?: string; sort?: string },
  ) => {
    const qs = new URLSearchParams();
    if (params?.page) qs.set("page", String(params.page));
    if (params?.recommendation) qs.set("recommendation", params.recommendation);
    if (params?.search) qs.set("search", params.search);
    if (params?.sort) qs.set("sort", params.sort);
    return req<{ reports: Report[]; total: number; pages: number }>(
      `/api/v1/reports?${qs.toString()}`,
      { token },
    );
  },

  downloadAllCsv: async (
    token: string,
    params?: { recommendation?: string; search?: string; sort?: string },
  ): Promise<Blob> => {
    const qs = new URLSearchParams();
    if (params?.recommendation) qs.set("recommendation", params.recommendation);
    if (params?.search) qs.set("search", params.search);
    if (params?.sort) qs.set("sort", params.sort);
    const res = await fetch(`${BASE}/api/v1/reports/export.csv?${qs.toString()}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      throw new APIError(res.status, "export_failed", "Could not export CSV. Please try again.");
    }
    return res.blob();
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
  diagnostics: () =>
    req<{
      health: { status: string; version: string; env: string; llm_ready: boolean };
      capacity: { max_supported_users: number; bulk_concurrency: number; rate_limit_per_minute: number; max_file_size_mb: number };
      metrics: { active_in_memory_jobs: number; in_memory_rate_limit_keys: number; process_memory_mb: number; timestamp: number };
    }>("/api/v1/health/diagnostics"),
};
