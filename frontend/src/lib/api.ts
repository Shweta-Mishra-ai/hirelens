/**
 * HireLens — Typed API Client
 *
 * One place where every request is made and every failure is turned into an
 * APIError the UI can render.
 *
 * fetch rejects with a TypeError when the network is down, which is not an
 * HTTP error and has no status; the content type is checked before parsing,
 * because an error page is not JSON; requests time out rather than hanging;
 * and a 204 is not fed to .json().
 */
import type {
  TeamInvite,
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

/**
 * A build that was given no API URL, served from somewhere that is not a
 * developer's laptop.
 *
 * NEXT_PUBLIC_* values are inlined at build time, so a missing
 * NEXT_PUBLIC_API_URL leaves every request pointed at http://localhost:8000 —
 * the visitor's own machine. The pages still load, because they are static,
 * and nothing else works at all. next.config.js refuses to produce such a
 * build for a real deployment; this is the second line, for a build made
 * before that guard existed or outside Vercel.
 *
 * Worth naming precisely, because the symptom otherwise reads as "the server
 * is down" and sends someone to check a server that is perfectly healthy.
 */
function buildIsMissingItsApiUrl(): boolean {
  if (typeof window === "undefined") return false;
  const apiIsLocal = /^https?:\/\/(localhost|127\.0\.0\.1)(:|$)/.test(BASE);
  const pageIsLocal = /^(localhost|127\.0\.0\.1)$/.test(window.location.hostname);
  return apiIsLocal && !pageIsLocal;
}

/**
 * The code carried by the APIError thrown when the build has no API address.
 * Exported so the auth screens can branch on it BEFORE their generic
 * `status === 0` branch, which would otherwise bury it under "check your
 * connection" — advice that sends the user to look at a working network.
 */
export const API_URL_NOT_CONFIGURED = "api_url_not_configured";

export const MISCONFIGURED_MESSAGE =
  "This site was built without its API address, so it is trying to reach a " +
  "server on your own computer. Nothing is wrong with your connection or " +
  "your details. Whoever deployed it needs to set NEXT_PUBLIC_API_URL to the " +
  "API's public URL and redeploy.";

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

  // Checked before the request rather than after it fails, so the answer is
  // the actual cause instead of a network error.
  if (buildIsMissingItsApiUrl()) {
    throw new APIError(0, API_URL_NOT_CONFIGURED, MISCONFIGURED_MESSAGE);
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

/**
 * Shape guards for responses.
 *
 * A render throws if the server sends a shape the page doesn't expect — and
 * React unmounts the whole tree when it does, so one wrong field replaces the
 * entire app with a generic crash page. Verified: `reports` arriving as an
 * object instead of an array wiped the dashboard, navigation included.
 *
 * These coerce at the boundary instead. A contract drift, a partial deploy or
 * a proxy returning something odd then degrades to "no rows" rather than
 * taking the page down.
 */
function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function asCount(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/**
 * Coerce a stored report into the shape every panel on the report page
 * assumes before any of them touches it.
 *
 * The panels reach straight into the blob — `report.flags.map(...)`,
 * `report.candidate.name` — which is fine for a report this build wrote and
 * not fine for one written by an older build, saved partially, or holding a
 * field whose type changed. A `flags` that arrived as a string threw
 * "flags.map is not a function" during render, which the route boundary
 * caught by replacing the entire page, navigation included. One odd field
 * should cost you that panel, not the app.
 */
function asReport(value: unknown): Report {
  const raw = asRecord(value);
  const credibility = asRecord(raw.credibility);
  return {
    ...(raw as object),
    candidate: asRecord(raw.candidate),
    skills: asRecord(raw.skills),
    credibility: {
      ...credibility,
      overall: asCount(credibility.overall),
    },
    ai_content_analysis: raw.ai_content_analysis === undefined
      ? undefined
      : asRecord(raw.ai_content_analysis),
    career_trajectory: raw.career_trajectory === undefined
      ? undefined
      : asRecord(raw.career_trajectory),
    experience: asArray(raw.experience),
    education: asArray(raw.education),
    projects: asArray(raw.projects),
    certifications: asArray(raw.certifications),
    timeline_gaps: asArray(raw.timeline_gaps),
    flags: asArray(raw.flags),
    positive_signals: asArray(raw.positive_signals),
    interview_questions: asArray(raw.interview_questions),
    summary: typeof raw.summary === "string" ? raw.summary : "",
  } as unknown as Report;
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
  /** Id of a description saved earlier; takes precedence over text and file. */
  savedId?: string;
}

export interface SavedJd {
  id: string;
  name: string;
  char_count: number;
  created_at?: string | null;
  updated_at?: string | null;
  last_used_at?: string | null;
}

export const jdsAPI = {
  list: (token: string) =>
    req<{ job_descriptions: SavedJd[] }>("/api/v1/job-descriptions", { token }),

  get: (id: string, token: string) =>
    req<{ job_description: SavedJd & { jd_text: string } }>(
      `/api/v1/job-descriptions/${encodeURIComponent(id)}`,
      { token },
    ),

  save: (name: string, jdText: string, token: string) =>
    req<{ job_description: SavedJd; status: string }>("/api/v1/job-descriptions", {
      method: "POST",
      body: JSON.stringify({ name, jd_text: jdText }),
      token,
    }),

  remove: (id: string, token: string) =>
    req<{ status: string }>(`/api/v1/job-descriptions/${encodeURIComponent(id)}`, {
      method: "DELETE",
      token,
    }),
};

export const matchAPI = {
  upload: (files: File[], jd: JdInput, token: string) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    // A saved description is sent by id and read server-side, so the text a
    // batch was ranked against is the text that was actually stored.
    if (jd.savedId) form.append("saved_jd_id", jd.savedId);
    else if (jd.text && jd.text.trim()) form.append("jd_text", jd.text.trim());
    if (!jd.savedId && jd.file) form.append("jd_file", jd.file);
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

  // No GET here on purpose. `GET /api/v1/verify/{id}` does exist and works —
  // it answers 404 with "No verification has been run for this report yet"
  // until one has — but the last run is also stored on the report and comes
  // back with it, so the extra round trip on every report open bought
  // nothing. The page reads report.verification instead.
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

  invites: (teamId: string, token: string) =>
    req<{ invites: TeamInvite[] }>(`/api/v1/teams/${teamId}/invites`, { token }).then(
      (res): { invites: TeamInvite[] } => ({ invites: asArray(res?.invites) }),
    ),

  revokeInvite: (teamId: string, inviteId: string, token: string) =>
    req<{ status: string }>(`/api/v1/teams/${teamId}/invites/${inviteId}`, {
      method: "DELETE", token,
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
    params?: {
      page?: number;
      limit?: number;
      recommendation?: string;
      search?: string;
      sort?: string;
    },
  ) => {
    const qs = new URLSearchParams();
    if (params?.page) qs.set("page", String(params.page));
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.recommendation) qs.set("recommendation", params.recommendation);
    if (params?.search) qs.set("search", params.search);
    if (params?.sort) qs.set("sort", params.sort);
    // ReportSummary, not Report: the list endpoint returns a flat row, not
    // the full nested report. Typing it as Report[] here is what let the
    // dashboard bind to the DOM `Report` global and cast everything away.
    return req<ReportListResponse>(`/api/v1/reports?${qs.toString()}`, { token }).then(
      (res): ReportListResponse => ({
        reports: asArray(res?.reports),
        total: asCount(res?.total, asArray(res?.reports).length),
        page: asCount(res?.page, 1),
        pages: asCount(res?.pages, 1),
      }),
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
    req<unknown>(`/api/v1/reports/${id}`, { token }).then(asReport),

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
    req<PoolAnalytics>("/api/v1/reports/analytics", { token }).then(
      (res): PoolAnalytics => {
        const dist = asRecord(res?.distribution);
        return {
          total_candidates: asCount(res?.total_candidates),
          avg_credibility_score: asCount(res?.avg_credibility_score),
          distribution: {
            recommended: asCount(dist.recommended),
            manual_review: asCount(dist.manual_review),
            high_risk: asCount(dist.high_risk),
          },
          top_skills: asArray(res?.top_skills),
          risk_categories: asRecord(res?.risk_categories) as Record<string, number>,
        };
      },
    ),
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
    req<{
      status: string;
      version: string;
      llm_ready: boolean;
      /** Older backends omit this; treat `undefined` as "unknown", not "off". */
      google_auth_ready?: boolean;
    }>("/api/v1/health"),
  diagnostics: () =>
    req<{
      health: { status: string; version: string; env: string; llm_ready: boolean };
      capacity: { max_supported_users: number; bulk_concurrency: number; rate_limit_per_minute: number; max_file_size_mb: number };
      metrics: { active_in_memory_jobs: number; in_memory_rate_limit_keys: number; process_memory_mb: number; timestamp: number };
    }>("/api/v1/health/diagnostics"),
};

