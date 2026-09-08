<div align="center">

<img src="assets/banner.svg" alt="HireLens" width="100%" />

### AI-Powered Resume Credibility, Fraud Detection & Recruiter Intelligence Platform

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-14.2-000?style=flat-square&logo=next.js)](https://nextjs.org)
[![Backend Tests](https://img.shields.io/badge/backend%20tests-passing-10B981?style=flat-square)](backend/tests)
[![Frontend Tests](https://img.shields.io/badge/frontend%20tests-vitest-6E9F18?style=flat-square&logo=vitest&logoColor=white)](frontend/src/__tests__)
[![License](https://img.shields.io/badge/license-MIT-64748B?style=flat-square)](#)

**Upload a resume → get a 6-dimension credibility score, AI-content detection, risk flags anchored to exact text, predictive talent velocity, and real-time public-data verification.**

</div>

---

## ⚠️ Read this first

HireLens is a decision-support platform, not an automated gatekeeper. Every score, flag, and "verified"/"not found" result is a **signal for a human recruiter to investigate further** — never treat any output here as proof of fraud or an automated reject/hire decision.

---

## Launch checklist

Do these in order. Everything on this list is something that leaves the API
reporting itself perfectly healthy while the product is broken for real users
— which is exactly the class of failure that only shows up after launch.

**1. Run the SQL migrations, in order, against your Supabase project.**
`backend/sql/001_initial_schema.sql` → `002_team_collaboration.sql` →
`003_candidate_notifications.sql`. 002 and 003 `ALTER TABLE public.reports`,
so running them without 001 fails.

**2. Set the required environment variables** in your hosting provider's
dashboard (not just in `render.yaml` — `sync: false` there means "a human
must type this in"). See `render.yaml` for what each one breaks when missing.
The two most commonly forgotten:

| Variable | What happens if you skip it |
|---|---|
| `ALLOWED_ORIGINS` | Defaults to `http://localhost:3000`. The browser blocks **every** request from your deployed frontend as a CORS violation. The API looks completely healthy. |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | Accounts and reports go to container-local SQLite, wiped on every restart, redeploy and idle spin-down. |

**3. After the deploy, check the health endpoint:**

```bash
curl https://<your-api>.onrender.com/api/v1/health
```

You are looking for exactly this:

```json
{ "status": "ok", "storage_mode": "supabase", "config_warnings": [] }
```

`config_warnings` is the authoritative list of misconfigurations — each entry
names what is wrong and what it breaks (see `backend/app/core/readiness.py`).
`storage_mode` is checked by running a real `select` against the `reports`
table, not by looking at an env var, so `"supabase"` means the database is
genuinely reachable and migrated.

**4. Log in on the deployed frontend, then hard-refresh the page.** You should
stay logged in. If you get bounced to `/login`, read the cross-site cookie
note under [Sessions](#sessions-and-the-cross-site-cookie-caveat) below.

**5. Upload one real resume end to end** and open the report. This is the only
check that exercises the LLM key, the parser, and the report view together.

---

## Sessions and the cross-site cookie caveat

The session token is restored on page load from an **httpOnly cookie**, so the
raw JWT is never persisted to `localStorage`.

That cookie is a **third-party cookie** in the default deployment, because
`*.vercel.app` and `*.onrender.com` are separate registrable sites. Safari
(ITP), Firefox in strict mode, and Chrome in Incognito block third-party
cookies by default and drop it. Two mitigations ship:

- The cookie is marked `Partitioned` (CHIPS), which keeps it working in Chrome
  under third-party cookie blocking, and in Safari 18.4+.
- The frontend keeps a **per-tab `sessionStorage` fallback**, re-validated
  against `/auth/me` before it is trusted, so a refresh keeps you logged in
  even when the cookie is dropped entirely. It is cleared when the tab closes.

**The real fix is to stop being cross-site**: serve both halves from one
registrable domain (`app.example.com` for the frontend, `api.example.com` for
this API). Then the cookie is first-party, `SameSite=Lax` works everywhere,
and the `sessionStorage` fallback becomes dead code. That is a DNS/hosting
change, not a code change — worth doing before this carries real traffic.

---

## What HireLens Does

Six analysis/intelligence modules, wired end-to-end, plus real-time public verification:

### 1. Single / Bulk Resume Credibility Analysis
Upload one resume, or up to 50 at once (`/bulk`). Each one gets:
- **Credibility Score** (0–100) across 6 dimensions — timeline, skills consistency, education, project authenticity, resume quality, and **content authenticity**.
- **AI-Generated-Content Detection** — dedicated check for whether the resume text itself was substantially AI-written vs. genuinely candidate-written, with quoted evidence.
- **Risk Flags** — every flag quotes the exact resume text that triggered it.
- **Skills Verification** — claimed vs. actually evidenced skills in work history.
- **Interview Questions** — generated specifically to probe this candidate's flags.

Bulk upload auto-ranks candidates by score with CSV export.

### 2. Live Interactive Candidate Interview Co-Pilot & Question Customizer (`/report/[id]` → Co-Pilot Tab)
- Customize probe questions and check them off during live candidate interviews.
- Record structured interviewer ratings across **Technical Depth**, **Problem Solving**, **Culture Fit**, and **Authenticity**.
- Store live evaluation notes and recommendation overrides via `POST /api/v1/reports/{report_id}/copilot`.

### 3. Predictive Talent Velocity & Career Growth Index
- Projects 5–10 year candidate career growth trajectory.
- Calculates **Promotion Cadence** (months/promotion), **Growth Velocity Index** (0–100), and **Retention Stability Score**.
- Embedded directly into the Candidate Intelligence Report (`report["talent_velocity"]`).

### 4. Enterprise Talent Analytics & Workforce Intelligence (`/dashboard` · `GET /api/v1/reports/analytics`)
- Aggregate metrics analyzing overall candidate pool health.
- Credibility distribution (Recommended vs High Risk vs Manual Review).
- Top identified skill clusters and risk flag category breakdown.
- Cached per-recruiter for 60s (Redis) and invalidated the moment a new report finishes, so it stays cheap without ever feeling stale.

### 5. JD Match (`/match`)
Paste or upload a job description, upload multiple resumes, get each candidate's match %, missing skills, and a highlighted best-fit — reusing the same credibility pipeline.

### 6. Real-Time Public Data Verification (`/report/[id]` → Verify tab)
Checks against:
- **GitHub** — live `api.github.com` calls cross-checking claimed skills against full repo language breakdowns. Results are cached per username+skillset for 1 hour so re-verifying the same candidate doesn't burn API rate-limit budget for an answer that hasn't changed.
- **Education** — university-domain registry lookup with automatic multi-variant retry logic.
- **Certifications** — live URL verification for embedded certificate links.
- **Employers** — company-website domain check.

Feeds into a **Combined Trust Assessment** weighing real-world verification evidence far more heavily than writing-style signals.

### 7. ATS CSV Import & Cross-Candidate Fraud Detection
- **ATS Import**: Import candidate CSV exports from Greenhouse/Lever/Workday/BambooHR.
- **Duplicate Detection**: Cross-candidate shingling + Jaccard similarity detecting resume mills and template fraud rings.

### 8. Team Collaboration (`/teams`, report page → "Discuss" tab)
Create a team, invite teammates by email, share reports, comment, and vote (Advance / Maybe / Reject). Auto-accepts invites on user login/signup without third-party email service requirements.

---

## Architecture

<img src="assets/architecture.svg" alt="HireLens architecture" width="100%" />

Supabase (Postgres + Auth) is the durable system of record. Local SQLite and an in-memory job store exist **only** as zero-config fallbacks for local development when Supabase env vars aren't set — see [Storage & Durability](#storage--durability-read-this-before-deploying) below before deploying anywhere real users will sign up.

---

## Storage & Durability (read this before deploying)

If `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` are missing or unreachable, HireLens degrades gracefully to a local SQLite file and an in-process dict instead of crashing — that's deliberate, so you can run the whole app with zero cloud setup while developing. It is **not** durable in production: on platforms with ephemeral disks or idle spin-down (e.g. a free-tier host), that fallback storage is wiped on every restart, and accounts/reports quietly disappear.

Two things make this impossible to miss instead of a silent trap:
- **Startup log**: a `CRITICAL` line fires at boot if the app is running in `APP_ENV=production` without Supabase configured.
- **`GET /api/v1/health`**: returns `"storage_mode": "supabase" | "local_fallback"` and a human-readable `storage_warning` — check this after every deploy. `storage_mode` is determined by running a real `select` against the `reports` table, so it also catches "Supabase is configured but the migrations were never run".
- **`config_warnings` in the same response**: the full list of production misconfigurations that leave the process healthy and the product broken — CORS still on localhost, no LLM key, invite links pointing at a domain the API will reject. See `backend/app/core/readiness.py`.

**Run the migrations first.** `backend/sql/001_initial_schema.sql` creates `public.reports`; `002` and `003` `ALTER` it, so they fail if 001 hasn't run. Order: `001` → `002` → `003`.

**Before deploying anywhere real users will use it:** set `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` directly in your hosting provider's environment settings (not just in `render.yaml`, which declares them as `sync: false` — placeholders you fill in yourself, not values it sets for you).

---

## Load Handling, Caching & Error Handling

### Load Handling
- **Redis Rate Limiting**: Per-IP limits on auth endpoints (login: 10/15min, signup: 8/hr) + per-user limits on analysis endpoints. The client IP is taken from the **rightmost** routable `X-Forwarded-For` entry, not the leftmost — a proxy appends to that header, so the leftmost value is whatever the caller sent and using it lets an attacker land every login attempt in a fresh bucket. Set `TRUST_PROXY_HEADERS=false` if the app is ever exposed without a proxy in front.
- **Concurrency Control**: Bulk & JD match uploads use `asyncio.Semaphore(BULK_CONCURRENCY)` to prevent event-loop starvation and stay within LLM rate limits.
- **File Size Ceiling**: Max file size capped at 10MB (`MAX_FILE_SIZE_MB`).
- **Registration capacity gate**: signups are capped and checked against a count of distinct Supabase Auth users (via the admin API) — not a proxy metric — so one recruiter uploading many reports can never block everyone else from signing up.

### Caching (`app/core/cache.py`)
A small Redis-backed JSON cache, used in two places so far:
- GitHub verification results — 1 hour TTL, keyed by username + claimed-skills fingerprint.
- Talent analytics — 60s TTL per recruiter, invalidated immediately when a new report finishes analysis.

Both degrade to "always miss, recompute" if Redis isn't configured — caching is a performance layer, never a hard dependency.

### Input & Security Validation
- **MIME & Magic Byte Verification**: `validate_upload()` checks PDF/DOCX magic bytes to reject executable/malicious uploads.
- **SSRF Protection**: `ssrf_guard.py` validates verification URLs against loopback, private, link-local, and cloud metadata IPs (169.254.169.254).
- **Injection Defense**: Multi-stage prompt fencing + heuristic injection scan.

### Error Handling
All endpoints return structured JSON payloads with tracking `x-request-id` headers on every response:
```json
{
  "error": "capacity_limit_exceeded",
  "message": "Registration capacity limit reached.",
  "request_id": "req_xyz123"
}
```

Request-validation failures use the same shape rather than FastAPI's default `{"detail": [...]}`, plus a per-field breakdown — otherwise the frontend has no `message` to render and every rejected form field surfaces as a bare "Server error 422":
```json
{
  "error": "validation_error",
  "message": "full_name: Full name must be at least 2 characters.",
  "details": [{ "field": "full_name", "message": "Full name must be at least 2 characters." }],
  "request_id": "req_xyz123"
}
```

Uncaught render errors on the frontend are caught by `app/error.tsx` (and `app/global-error.tsx` for the root layout), which show a real message and a retry rather than Next.js's blank "Application error: a client-side exception has occurred" page.

---

## Tech Stack

| Layer | Technology |
|---|---|
| AI Engine | **Gemini 2.5 Flash** (primary) → **Groq `openai/gpt-oss-120b`** (fallback) → Claude Sonnet (optional 3rd fallback) |
| Backend | **FastAPI** 0.110 · Python 3.12 / 3.14 · pdfminer.six · python-docx |
| Frontend | **Next.js 14.2** (App Router) · TypeScript · Tailwind CSS |
| Auth & DB | **Supabase** (PostgreSQL + Auth) — durable primary store, with a local fallback for zero-config dev only |
| Cache & Queue | **Upstash Redis** — rate limiting, GitHub/analytics caching, bulk-batch state |
| Deploy | **Vercel** (frontend) · **Render** (backend) |
| Testing & CI | **pytest** (backend) + **Vitest + React Testing Library** (frontend) + TypeScript type-check + GitHub Actions CI |

---

## Quick Start

```bash
git clone https://github.com/Shweta-Mishra-ai/hirelens.git
cd hirelens

# Backend Setup
cd backend
python -m venv venv
# On Windows: venv\Scripts\activate
# On Linux/Mac: source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000

# Frontend Setup (new terminal)
cd frontend
npm install
cp .env.local.example .env.local
npm run dev

# Frontend App: http://localhost:3000
# API Documentation: http://localhost:8000/docs
```

---

## Testing

```bash
# Backend test suite (unit, integration, capacity, load-handling, E2E)
cd backend
python -m pytest tests/ -v

# Frontend unit/component tests (Vitest + React Testing Library)
cd frontend
npm test

# Frontend type check
npm run type-check

# Frontend lint (Next 16 removed `next lint` AND the lint pass inside
# `next build`, so this calls eslint directly — see .github/workflows/ci.yml)
npm run lint

# Frontend production build
npm run build
```

The frontend suite covers the API client's error/timeout/auth-header handling, the auth store's login/logout/session-restore flows (including the `sessionStorage` fallback for browsers that drop the cross-site cookie), and the shared UI primitives — the foundation to build page-level coverage on top of.

The backend suite is hermetic: `tests/conftest.py` points the local SQLite database at a per-run temp file. Without that, tests wrote to the same `backend/data/local.db` the dev server uses, so a second `pytest` run on the same machine failed on "email already registered" while a fresh CI runner passed — a failure mode that only ever appears locally and gets written off as a stale file.

Every job runs in CI on each push and PR: backend pytest, `pip-audit`, frontend vitest, `npm audit`, typecheck, lint, and a real production build.

---

## UI Component Kit

Pages were previously built with hand-rolled inline styles duplicated across files. `src/components/ui/primitives.tsx` now centralizes the repeated patterns — `Card`, `Button`, `Badge`, `TextInput`, `StatCard`, `PageShell`, `AlertBanner` — all driven by `src/lib/design-tokens.ts`, so a spacing or color change happens in one place instead of a dozen. Every top-level page (`/`, `/login`, `/signup`, `/dashboard`, `/analyze`, `/bulk`, `/match`, `/teams`) is migrated onto it, sharing one `AppNavbar` instead of ~50 hand-copied lines per page. `/report/[id]` uses the same design tokens and palette but has not been restructured onto the shared components — it is a detail view with its own header rather than the tab-navbar pattern, and at ~1,650 lines the rewrite risk outweighs the consistency gain without visual QA.

---

## Environment Variables

### Backend (`backend/.env`)
```env
APP_ENV=production
SECRET_KEY=<32+ char random string>

# Supabase — required for durable storage in production; see "Storage & Durability" above
SUPABASE_URL=https://xyz.supabase.co
SUPABASE_SERVICE_KEY=...
SUPABASE_ANON_KEY=...

# LLM Providers
GEMINI_API_KEY=...
GROQ_API_KEY=...
ANTHROPIC_API_KEY=...

# Public Verification (raises GitHub rate limit 60/hr → 5000/hr)
GITHUB_TOKEN=...

# Redis (rate limiting, caching, batch state)
REDIS_URL=rediss://default:xxx@your-db.upstash.io:6379

ALLOWED_ORIGINS=http://localhost:3000,https://your-app.vercel.app
```

**First-time Supabase setup:** run the SQL migrations in `backend/sql/` **in order** in the Supabase SQL Editor before connecting the app — `001_initial_schema.sql` (base `reports` table), then `002_team_collaboration.sql`, then `003_candidate_notifications.sql`. Skipping 001 is the most likely reason `/api/v1/health` shows `storage_mode: "local_fallback"` even with correct env vars — the app can authenticate to Supabase fine but has nowhere to write reports until that table exists.

> **Deploying to Render:** the vars above marked in `render.yaml` as `sync: false` are placeholders — you still need to fill in the actual values in Render's dashboard under the service's Environment tab. Skipping this is the single most common cause of "it worked locally but logins/reports don't persist in production" — see [Storage & Durability](#storage--durability-read-this-before-deploying).

---

## API Summary

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/auth/signup` | POST | Signup recruiter account |
| `/api/v1/auth/login` | POST | Login recruiter account |
| `/api/v1/analysis/upload` | POST | Single resume upload |
| `/api/v1/analysis/{job_id}/status` | GET | Poll analysis status |
| `/api/v1/reports` | GET | List reports (search, sort, pagination) |
| `/api/v1/reports/{id}/copilot` | POST/GET | Candidate Interview Co-Pilot & Scorecard |
| `/api/v1/reports/analytics` | GET | Enterprise Talent Analytics & Pool Intelligence (Redis-cached) |
| `/api/v1/bulk/upload` | POST | Bulk upload up to 50 resumes |
| `/api/v1/bulk/{id}/duplicates` | GET | Cross-candidate duplicate fraud detection |
| `/api/v1/match/upload` | POST | JD match upload |
| `/api/v1/verify/{id}/run` | POST | Real-time public data verification (GitHub result Redis-cached) |
| `/api/v1/teams` | POST/GET | Team workspace creation and listing |
| `/api/v1/auth/session` | GET | Restore a session from the httpOnly cookie (read-only; never authorizes writes) |
| `/api/v1/auth/logout` | POST | Clear the session cookie |
| `/api/v1/health` | GET | System health check — includes `storage_mode` and `config_warnings` |
| `/api/v1/health/diagnostics` | GET | Capacity & system diagnostics |

---

## Roadmap

- [x] Single resume credibility analysis
- [x] AI-content detection dimension with quoted evidence
- [x] Bulk upload (50 files) with ranking + CSV export
- [x] JD match (1 JD → many candidates) with missing skills + best-fit
- [x] Real-time public verification (GitHub, education, certs, company)
- [x] Combined Trust Assessment rule engine
- [x] Cross-candidate duplicate/template fraud detection
- [x] ATS CSV import auto-column detection
- [x] Team workspace collaboration (comments, voting, share)
- [x] Registration capacity enforcement (accurate distinct-user counting)
- [x] Supabase connection pooling & fallback auth resilience, with explicit storage-mode visibility
- [x] Redis caching for GitHub verification + talent analytics
- [x] Interactive Candidate Interview Co-Pilot & Custom Probe Generator
- [x] Predictive Talent Velocity & Career Growth Index
- [x] Enterprise Talent Analytics & Workforce Intelligence
- [x] Frontend unit/component test suite (Vitest + RTL)
- [x] Shared UI component kit (`components/ui/primitives.tsx`) — every top-level page migrated
- [x] Production configuration readiness checks surfaced in `/api/v1/health`
- [x] Session restore that survives third-party cookie blocking (Safari/Firefox/Incognito)
- [ ] Restructure `/report/[id]` onto the shared UI kit (already on the shared palette/tokens)
- [ ] Serve frontend + API from one registrable domain, making the session cookie first-party
- [ ] Page-level integration tests (dashboard load, login flow) on top of the current unit-test foundation
