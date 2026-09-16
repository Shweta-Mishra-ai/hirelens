# API Reference

Base URL `https://<your-api>/api/v1` · interactive docs at `/docs` ·
OpenAPI schema at `/openapi.json`.

---

## Authentication

Everything except `/health`, `/auth/*` and `/docs` needs a bearer token:

```http
Authorization: Bearer <jwt>
```

Tokens come from `/auth/signup`, `/auth/login` or `/auth/oauth-verify` and are
valid for 7 days.

---

## Error envelope

Every failure has the same shape — including validation errors, 404s and the
catch-all 500:

```json
{
  "error": "file_too_large",
  "message": "That file is 14MB. The limit is 10MB per resume.",
  "request_id": "a1b2c3d4"
}
```

`message` is written to be shown to a person. `request_id` also comes back in
the `X-Request-ID` header and is what to quote in a bug report.

| Status | Codes |
|---|---|
| 400 | `validation_error` |
| 401 | `auth_error` |
| 403 | `forbidden` |
| 404 | `not_found` |
| 409 | `conflict` |
| 413 | `file_too_large` |
| 415 | `unsupported_file_type` |
| 422 | `empty_batch`, `resume_download_failed`, `all_resumes_unreachable`, `invalid_job_description` |
| 429 | `rate_limit_exceeded`, `too_many_batches` |
| 503 | `llm_unavailable`, `analysis_unavailable`, `account_store_unavailable`, `copilot_unavailable`, `db_required` |
| 500 | `internal_error` |

---

## Auth

| | Endpoint | Notes |
|---|---|---|
| `POST` | `/auth/signup` | `{ email, password, full_name, company? }`. 409 if taken, **503 if the account store is unreachable** — deliberately never a local shadow account |
| `POST` | `/auth/login` | 10 attempts per 15 minutes per IP |
| `POST` | `/auth/oauth-verify` | `{ access_token }` from the Supabase Google round trip. No fallback: an unverifiable token is refused, never exchanged |
| `GET` | `/auth/me` | The caller's id and email |
| `POST` | `/auth/forgot-password` | Always 200, whether or not the address exists |
| `POST` | `/auth/reset-password` | |
| `GET` | `/auth/stats` | Capacity headroom |

---

## Analysis

```http
POST /api/v1/analysis/upload
Content-Type: multipart/form-data
file=@resume.pdf
```

```json
{ "job_id": "8f3c…", "status": "queued" }
```

Then poll:

```http
GET /api/v1/analysis/{job_id}/status
```

```json
{
  "id": "8f3c…",
  "status": "complete",
  "stage": "complete",
  "progress": 100,
  "report_id": "d85a…",
  "error": null
}
```

`status` is `queued` · `running` · `complete` · `failed`. On `failed`, `error`
is a sentence to show the user.

**Accepted:** PDF and DOCX, 10 MB each. A DOCX that unpacks to more than 25 MB
is refused from its archive directory, before anything is decompressed.

---

## Bulk

| | Endpoint | Notes |
|---|---|---|
| `POST` | `/bulk/upload` | Up to 50 files, 150 MB total. The cap is enforced as bytes arrive |
| `GET` | `/bulk/{batch_id}/status` | Per-file progress plus a live ranking |
| `GET` | `/bulk/{batch_id}/export.csv` | The ranking as CSV |
| `GET` | `/bulk/{batch_id}/duplicates` | Cross-candidate template detection |
| `POST` | `/bulk/{batch_id}/notify-all` | `{ decision, overrides? }` — real email. Rate-limited per user |

Duplicate detection is the one check a single resume can never do: it compares
candidates in a batch against each other. High similarity is a signal to look
closer, not proof — people in the same field describe similar work.

---

## JD Match

| | Endpoint |
|---|---|
| `POST` | `/match/upload` — `files[]` + `job_description` |
| `GET` | `/match/{batch_id}/status` — ranked by `match_percent` |
| `GET` | `/match/{batch_id}/export.csv` |

Each row carries `match_percent`, `matching_skills`, `missing_skills`,
`verdict` and a `rationale`.

---

## ATS import

```http
POST /api/v1/ats/import
file=@greenhouse_export.csv
```

Every resume URL in the CSV is downloaded and fed into the same pipeline as a
bulk upload, so `/bulk/{batch_id}/*` all work on the result. Column names are
detected across the common ATS spellings. Each download re-validates the SSRF
guard **on every redirect hop** and aborts mid-stream past 10 MB.

Returns `detected_columns`, `queued`, `skipped_at_parse` and
`skipped_at_download` — one dead URL never sinks the import.

---

## Reports

| | Endpoint | Notes |
|---|---|---|
| `GET` | `/reports` | `page`, `limit` (≤100), `search`, `sort`, `recommendation` |
| `GET` | `/reports/{id}` | The full report. Visible to its owner or any member of the team it is shared with |
| `DELETE` | `/reports/{id}` | |
| `GET` | `/reports/analytics` | Pool distribution, average credibility, top skills |
| `GET` | `/reports/export.csv` | Everything matching the current filters, 1,000 rows |
| `POST` | `/reports/{id}/decision` | `advance` · `schedule_followup` · `reject` |
| `GET` | `/reports/{id}/notify/draft` | A pre-written email for that decision |
| `POST` | `/reports/{id}/notify` | Sends it |

`sort` is `newest` · `oldest` · `score_desc` · `score_asc` · `name_asc`.

A database failure here returns an **error**, never an empty list — an empty
page and "your candidates are gone" must not look the same.

---

## Verification

| | Endpoint |
|---|---|
| `POST` | `/verify/{report_id}/run` — optional `{ github_username }` to override the resume |
| `GET` | `/verify/{report_id}` — the last run, 404 until one exists |

```json
{
  "run_at": "2026-09-14T09:12:00Z",
  "github": { "status": "verified", "verified_skills": ["python", "go"] },
  "education": [{ "institution": "IIT Bombay", "status": "verified" }],
  "certifications": [{ "name": "AWS SAA", "status": "no_link_provided" }],
  "experience": [{ "company": "Razorpay", "status": "domain_found" }],
  "trust_assessment": {
    "verdict": "moderate_confidence",
    "score": 18,
    "evidence_available": true,
    "reasoning": ["GitHub account verified with 2 claimed skill(s) evidenced (+21)"]
  },
  "recommendation_update": null
}
```

`trust_assessment.score` is **signed, −100 to 100** — negative leans
concerning, positive leans trustworthy. It is not a percentage.

Re-running is safe: the downgrade is measured from the AI's original read, so
the same evidence always lands on the same verdict.

---

## Interview Co-Pilot

| | Endpoint |
|---|---|
| `GET` | `/reports/{id}/copilot` |
| `POST` | `/reports/{id}/copilot` |

```json
{
  "scorecard": [{ "category": "Systems design", "score": 4, "notes": "…" }],
  "custom_questions": [{ "question": "…", "is_asked": false }],
  "interview_notes": "…",
  "recommendation_override": null
}
```

`score` is 0–5 and optional — an unrated category is a valid state, not an
error. These notes carry compensation expectations and candid assessments, so
every route checks access first; a report you cannot see is a 404, not a 403.

---

## Collaboration

| | Endpoint | Notes |
|---|---|---|
| `POST` | `/reports/{id}/share` | `{ team_id }`, owner only. Needs Supabase |
| `POST` | `/reports/{id}/unshare` | Owner only. Actually revokes access |
| `GET`/`POST` | `/reports/{id}/comments` | |
| `DELETE` | `/reports/{id}/comments/{comment_id}` | Author only |
| `GET` | `/reports/{id}/votes` | Tally plus your own vote |
| `POST` | `/reports/{id}/vote` | `advance` · `reject` · `maybe`, one per person |

Comments and votes carry a `user_name`, resolved from Supabase `profiles` or
the local store — never a raw UUID.

---

## Teams

| | Endpoint | Notes |
|---|---|---|
| `POST` / `GET` | `/teams` | |
| `GET` | `/teams/{id}/members` | Members only |
| `POST` | `/teams/{id}/invite` | Owner or admin. Email-based, so the invitee needs no account yet |
| `DELETE` | `/teams/{id}/members/{user_id}` | Owner cannot be removed |
| `DELETE` | `/teams/{id}` | Owner only. Removes membership and pending invites too |

---

## Health

| | Endpoint | Auth |
|---|---|---|
| `GET` | `/health` | none |
| `GET` | `/health/diagnostics` | required |

The public one says *whether* each service is well, never *why* — a Postgres
error routinely names the host or the schema, and this is the only route
reachable without an account. It stays 200 even when degraded so a blip does
not get the instance restarted.

---

## Limits

| | Default | Setting |
|---|---|---|
| Requests per minute | 20 | `RATE_LIMIT_PER_MINUTE` |
| Candidate emails per minute | 10 | `NOTIFY_RATE_LIMIT_PER_MINUTE` |
| Login attempts | 10 per 15 min per IP | `LOGIN_LIMIT_PER_15_MIN` |
| Signups | 8 per hour per IP | `SIGNUP_LIMIT_PER_HOUR` |
| File size | 10 MB | `MAX_FILE_SIZE_MB` |
| DOCX uncompressed | 25 MB | `MAX_DOCX_UNCOMPRESSED_MB` |
| Bulk files | 50 | `BULK_MAX_FILES` |
| Bulk total | 150 MB | `BULK_MAX_TOTAL_MB` |
| Concurrent batches | 2 per user | `BULK_MAX_CONCURRENT_BATCHES_PER_USER` |
| Analysis timeout | 120 s | `ANALYSIS_TIMEOUT_SECONDS` |

Without `REDIS_URL` these are per-process, which is correct for a single
worker. With it they are shared across instances.
