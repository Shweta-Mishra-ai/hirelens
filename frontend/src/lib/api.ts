/**
 * HireLens — Typed API Client
 * Fixed:
 * - Network error handling (fetch can throw TypeError)
 * - Response content-type check before .json()
 * - Timeout handling
 * - 204 No Content handled correctly
 */
import type {
  Report,
  ReportListResponse,
  PoolAnalytics,
  AnalysisJob,
  User,
  BulkUploadResponse,
  BatchStatus,
  MatchBatchStatus,
  VerificationResult,
  DuplicateCheckResult,
  Team,
  TeamMember,
  ReportComment,
  VotesResult,
} from "@/types";

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
    throw toAPIError(res.status, body);
  }

  return body as T;
}

/**
 * FastAPI request-validation failures (422) do not use the app's
 * `{error, message}` envelope. They return `{detail: [{loc, msg, type}, …]}`,
 * which the previous implementation had no branch for — so `b["message"]`
 * was undefined and every validation failure surfaced to the user as the
 * literal string "Server error 422". Signing up with an address the server
 * rejected produced that instead of "Enter a valid email address", with no
 * indication of which field was at fault.
 */
export function toAPIError(status: number, body: unknown): APIError {
  const b = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};

  // The app's own error envelope, raised by HireLensException handlers.
  if (typeof b["message"] === "string") {
    return new APIError(
      status,
      typeof b["error"] === "string" ? b["error"] : "http_error",
      b["message"],
      typeof b["request_id"] === "string" ? b["request_id"] : undefined,
    );
  }

  const detail = b["detail"];

  // FastAPI/Pydantic validation error list.
  if (Array.isArray(detail) && detail.length > 0) {
    const messages = detail
      .map((d) => {
        if (typeof d === "string") return d;
        if (typeof d !== "object" || d === null) return null;
        const item = d as { loc?: unknown[]; msg?: unknown };
        const msg = typeof item.msg === "string" ? item.msg : null;
        if (!msg) return null;
        // `loc` is like ["body", "email"] — the last segment is the field.
        const field = Array.isArray(item.loc)
          ? item.loc.filter((x) => typeof x === "string" && x !== "body").pop()
          : undefined;
        const clean = msg.replace(/^Value error,\s*/i, "");
        return field ? `${humanizeField(String(field))}: ${clean}` : clean;
      })
      .filter((m): m is string => Boolean(m));

    if (messages.length > 0) {
      return new APIError(status, "validation_error", messages.join(" "), undefined);
    }
  }

  // A plain string detail (FastAPI's HTTPException default).
  if (typeof detail === "string" && detail.trim()) {
    return new APIError(status, "http_error", detail, undefined);
  }

  return new APIError(status, "http_error", genericMessage(status), undefined);
}

function humanizeField(field: string): string {
  const words = field.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Last-resort copy. "Server error 500" tells a recruiter nothing they can
 * act on, so each status maps to a sentence that says what to do next.
 */
function genericMessage(status: number): string {
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (status === 403) return "You do not have access to this.";
  if (status === 404) return "That could not be found. It may have been deleted.";
  if (status === 409) return "That already exists.";
  if (status === 413) return "That file is too large.";
  if (status === 415) return "That file type is not supported. Upload a PDF or DOCX.";
  if (status === 429) return "Too many requests. Wait a moment and try again.";
  if (status === 503) return "The service is temporarily unavailable. Try again shortly.";
  if (status >= 500) return "Something went wrong on our end. Please try again.";
  return "That request could not be completed.";
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

  forgotPassword: (email: string) =>
    req<{ status: string; message: string }>("/api/v1/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  resetPassword: (accessToken: string, newPassword: string) =>
    req<{ status: string; message: string }>("/api/v1/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ access_token: accessToken, new_password: newPassword }),
    }),
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

  // One-click: emails every completed candidate in the batch the default
  // template for `decision`. Pass `overrides` (keyed by report_id) to
  // customize a specific candidate's message without a separate call.
  notifyAll: (
    batchId: string,
    decision: string,
    overrides: Record<string, { subject: string; body: string }>,
    token: string,
  ) =>
    req<{
      batch_id: string;
      decision: string;
      total_candidates: number;
      emails_sent: number;
      results: { report_id: string; candidate_name: string; email_sent: boolean; reason: string | null }[];
    }>(`/api/v1/bulk/${batchId}/notify-all`, {
      method: "POST",
      body: JSON.stringify({ decision, overrides }),
      token,
    }),
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
    req<{ status: string; email?: string; email_sent?: boolean; invite_url?: string }>(`/api/v1/teams/${teamId}/invite`, {
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
    // ReportSummary, not Report: the list endpoint returns a flat row, not
    // the full nested report. Typing it as Report[] here is what let the
    // dashboard bind to the DOM `Report` global and cast everything away.
    return req<ReportListResponse>(`/api/v1/reports?${qs.toString()}`, { token });
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

  // Fetches the default subject/body draft for a decision — used to
  // pre-fill the "edit before sending" panel. Never sends anything.
  notifyDraft: (id: string, decision: string, token: string) =>
    req<{
      candidate_email: string | null;
      candidate_name: string;
      subject: string;
      body: string;
      has_email: boolean;
    }>(`/api/v1/reports/${id}/notify/draft?decision=${encodeURIComponent(decision)}`, { token }),

  // Sends the (default or edited) email to the candidate. Separate from
  // `decision()` above — recording a decision never auto-emails anyone.
  notify: (
    id: string,
    decision: string,
    subject: string,
    body: string,
    token: string,
  ) =>
    req<{ status: string; email_sent: boolean; candidate_email: string | null; message: string }>(
      `/api/v1/reports/${id}/notify`,
      { method: "POST", body: JSON.stringify({ decision, subject, body }), token },
    ),

  analytics: (token: string) =>
    req<PoolAnalytics>("/api/v1/reports/analytics", { token }),
};

// ── Interview Co-Pilot (Feature A) ──────────────────────────────────────────
export const copilotAPI = {
  get: (reportId: string, token: string) =>
    req<{ report_id: string; copilot: any }>(`/api/v1/reports/${reportId}/copilot`, { token }),

  save: (reportId: string, payload: any, token: string) =>
    req<{ status: string; report_id: string; copilot: any }>(
      `/api/v1/reports/${reportId}/copilot`,
      { method: "POST", body: JSON.stringify(payload), token },
    ),
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

