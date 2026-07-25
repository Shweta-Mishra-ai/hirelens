<div align="center">

# 🔎 HireLens

### AI-Powered Resume Credibility & Fake-CV Detection for Recruiters

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-14.2-000?style=flat-square&logo=next.js)](https://nextjs.org)
[![Tests](https://img.shields.io/badge/backend%20tests-254%20passing-10B981?style=flat-square)](backend/tests)
[![License](https://img.shields.io/badge/License-MIT-6366F1?style=flat-square)](LICENSE)

**Upload a resume → get a credibility score, AI-generated-content detection, risk flags anchored to exact text, and real-time public-data verification — in under 30 seconds.**

</div>

---

## ⚠️ Read this first

HireLens is a decision-support tool, not a lie detector. Every score, flag, and
"verified"/"not found" result is a **signal for a human recruiter to
investigate further** — never treat any output here as proof of fraud or an
automated reject/hire decision. This matters most for the AI-content-detection
and public-data-verification features: a "not found" result usually means
*the data isn't public*, not that something is false.

---

## What it actually does today

HireLens ships with **three working analysis modes** plus **real-time public
verification** — not a mockup, all of it is wired end-to-end and tested.

### 1. Single / Bulk Resume Analysis
Upload one resume, or up to 50 at once (`/bulk`). Each one gets:
- **Credibility Score** (0–100) across 6 dimensions — timeline, skills
  consistency, education, project authenticity, resume quality, and
  **content authenticity**
- **AI-Generated-Content Detection** — a dedicated check for whether the
  resume text itself was substantially AI-written (buzzword-heavy generic
  bullets, suspiciously uniform structure, round numbers with zero context)
  vs. genuinely written by the candidate, with quoted evidence either way
- **Risk Flags** — every flag quotes the exact resume text that triggered it
- **Skills Verification** — claimed vs. actually evidenced in work history
- **Interview Questions** — generated specifically to probe this candidate's flags
- Non-resume files (invoices, cover letters, blank templates, random PDFs)
  are rejected **before** an AI call is wasted on them — see
  `resume_heuristic.py`

Bulk upload auto-ranks candidates by score with CSV export.

### 2. JD Match (`/match`)
Paste or upload a job description, upload multiple resumes, get each
candidate's match %, missing skills, and a highlighted best-fit — reusing the
same credibility pipeline, not a separate re-analysis.

### 3. Public Data Verification (`/report/[id]` → Verify tab)
Real-time (not cached, not mocked) checks against:
- **GitHub** — live `api.github.com` calls cross-checking claimed skills
  against the FULL language breakdown of each public repo (not just each
  repo's single "primary language", which silently hides secondary skills
  like Docker/SQL) plus repo topics and descriptions
- **Education** — free university-domain registry lookup, with automatic
  retry against progressively broader/cleaned name variants (so "IIT Delhi"
  correctly retries as "Indian Institute of Technology Delhi" instead of
  giving up after one miss)
- **Certifications** — if a public verify link is embedded in the resume text,
  it's live-fetched and checked for the candidate's name
- **Employers** — best-effort company-website domain check

All four run in parallel and are individually fault-isolated — one failing
check never breaks the others. Results feed into a **Combined Trust
Assessment**: a rule-based (not another LLM call — deterministic and fully
auditable) verdict that weighs real-world verification evidence far more
heavily than the AI-content writing-style signal, since text is cheap to
fake but a real GitHub account with matching commit history isn't.

### 4. ATS CSV Import (`/bulk` → "Import from ATS")
Recruiters already track candidates in Greenhouse/Lever/Workday/BambooHR —
re-uploading resumes one at a time defeats the point. Every ATS supports
exporting the candidate list as CSV with zero setup (unlike live API
integrations, which mostly need a paid plan + vendor approval). Upload that
CSV; HireLens auto-detects the name/email/resume-URL columns (handles
different vendors' naming — "Attachment URL" vs "Resume" vs "CV Link"),
downloads each resume (SSRF-guarded), and feeds them through the exact same
pipeline as a direct bulk upload — so status, ranking, CSV export, and
duplicate detection all work identically, zero extra code needed.

### 5. Cross-Candidate Duplicate Detection (bulk batches)
Compares every candidate in a batch against every other candidate's resume
content (experience bullets, project descriptions) using k-word shingling +
Jaccard similarity — no external API, no cost. Catches "resume mill" fraud
rings where multiple supposedly-different candidates submit near-identical
resumes, which no single-resume analysis could ever notice on its own.

### 6. Team Collaboration (`/teams`, report page → "Discuss" tab)
Screening candidates solo misses things a second opinion would catch. Create
a team, invite teammates by email, and share any report with the team —
teammates can then comment and cast a vote (Advance / Maybe / Reject) on it.
No email-sending service required: an invite is just a pending record that
auto-activates the next time the invited person logs in or signs up with
that email — $0 cost, no third-party dependency. Report ownership never
transfers on sharing; only visibility does.

---

## Honest limitations (please read before demoing this)

| Feature | Limitation |
|---|---|
| AI-content detection | An LLM judging LLM-generated text is inherently imperfect — treat "high likelihood" as "worth asking about in interview," not proof |
| GitHub verification | Only sees **public** repos; strong private-repo work won't show up. 60 req/hr without `GITHUB_TOKEN`, 5000/hr with it (free) |
| Education verification | Open registry, not an official degree-verification service — small/new institutions are often just missing from the dataset |
| Certification verification | Only works if the resume text contains an actual verify URL — HireLens doesn't currently extract cert URLs as a separate structured field |
| Employer verification | Guesses a `.com` domain from the company name — false negatives are common (unregistered businesses, non-.com TLDs, rebrands) |
| Credibility scoring generally | LLM-based and probabilistic — use it to prioritize where to dig, not as a pass/fail gate |

---

## Stack

| Layer | Technology |
|---|---|
| AI | **Gemini 2.5 Flash** (primary) → **Groq `openai/gpt-oss-120b`** (fallback) → Claude Sonnet 5 (optional 3rd fallback) |
| Backend | **FastAPI** 0.110 · Python 3.12 · pdfminer.six · python-docx |
| Frontend | **Next.js 14.2** (App Router) · TypeScript · Tailwind CSS |
| Auth + DB | **Supabase** (PostgreSQL + Auth), JWT (HS256) |
| Cache/Queue | **Upstash Redis** — rate limiting + bulk-batch state (in-memory fallback if unset) |
| Deploy | **Vercel** (frontend) · **Render** (backend) |
| CI | **GitHub Actions** — pytest + `pip-audit` + frontend typecheck/build on every push |

### Why Gemini → Groq → Anthropic, in that order
Gemini's free tier is generous on daily volume but has a low per-minute rate
limit, so bulk uploads hit it fast. When that happens the app automatically
retries on Groq, then Anthropic if configured. **This fallback previously had
a real bug**: Groq's model was pinned to `llama-3.1-70b-versatile`, which was
fully deprecated in Jan 2025 — meaning the "fallback" silently failed on every
single request. It's now pinned to `openai/gpt-oss-120b` (Groq's current
supported model) with a regression test (`test_llm_fallback.py`) that fails
CI if a deprecated model string ever creeps back in. Model names on all three
providers do drift over time — if analysis starts failing, check
`GET /api/v1/health` first, then the Render logs for the actual provider error.

---

## Design System

The UI intentionally avoids the generic "dark navy dashboard with blue/cyan
gradients" look most AI-SaaS tools default to — HireLens is a *document
credibility examination* tool, so the identity is built around a **case-file
/ evidence** metaphor instead:

- **Palette**: warm ink background (not blue-tinted navy), muted ledger-style
  verdict colors (brick red / forest green / brass gold — not neon SaaS
  accents), parchment used sparingly for quoted evidence
- **Type**: Fraunces (editorial serif, for scores/headings) + IBM Plex Sans
  (body) + IBM Plex Mono (data/technical) — set in `app/layout.tsx`, tokens
  in `app/globals.css`
- **Signature element — the Verdict Stamp** (`components/VerdictStamp.tsx`):
  every recommendation is shown as a rotated, ink-stamped badge instead of a
  generic circular score-ring or soft pill — used consistently across the
  report header, dashboard rows, and ranking tables
- **Evidence quotes**: flagged resume text is rendered in a highlighted-
  document-excerpt style (`.evidence-quote` in `globals.css`), reinforcing
  that every flag cites exact text, not a vibe

Currently fully applied to the **Report page** (flagship surface) and
**Dashboard**; Analyze/Bulk/Match/Auth pages have the new color tokens and
fonts applied but haven't had the same structural pass (stamp motif, docket
header) yet — a natural next step, same components are ready to reuse.

---

## Quick Start

```bash
git clone https://github.com/Shweta-Mishra-ai/hirelens.git
cd hirelens

# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env         # fill in your keys — see table below
uvicorn app.main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
cp .env.local.example .env.local  # fill in your keys
npm run dev

# App:  http://localhost:3000
# API:  http://localhost:8000/docs
```

### Run the test suite
```bash
cd backend
python -m pytest tests/ -v      # 254 tests — unit + integration + security
```

---

## Environment Variables

### Backend (`backend/.env`)
```env
APP_ENV=production
SECRET_KEY=<32+ char random string>   # generate: python -c "import secrets; print(secrets.token_urlsafe(48))"
                                       # ⚠️ if this is left at the repo default in production, JWTs can be forged —
                                       # the app logs a CRITICAL warning at startup if you forget this

# Supabase (required for persistence — app degrades to in-memory without it)
SUPABASE_URL=https://xyz.supabase.co
SUPABASE_SERVICE_KEY=...
SUPABASE_ANON_KEY=...

# LLM — at least one required
GEMINI_API_KEY=...        # aistudio.google.com (free)
GROQ_API_KEY=...          # console.groq.com (free, fallback — strongly recommended)
ANTHROPIC_API_KEY=...     # optional 3rd fallback (no free tier)

# Feature 3 — recommended, not required
GITHUB_TOKEN=...          # github.com/settings/tokens, no scopes needed — raises GitHub API limit 60/hr → 5000/hr

# Recommended for production reliability (Redis-backed rate limiting, bulk batch persistence)
REDIS_URL=rediss://default:xxx@your-db.upstash.io:6379

ALLOWED_ORIGINS=https://your-app.vercel.app
```

### Frontend (`frontend/.env.local`)
```env
NEXT_PUBLIC_API_URL=https://your-api.onrender.com
NEXT_PUBLIC_SUPABASE_URL=https://xyz.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
```

---

## Database Setup

Run once in the Supabase SQL Editor. Note: `report_data` is a single jsonb
column holding the full analysis (including `jd_match` and `verification`
sub-objects when those features are used) — no migration is needed when new
analysis fields are added, they just live inside this column.

```sql
CREATE TABLE IF NOT EXISTS public.reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  job_id UUID,
  file_name TEXT NOT NULL,
  candidate_name TEXT,
  overall_score INTEGER CHECK (overall_score BETWEEN 0 AND 100),
  recommendation TEXT CHECK (recommendation IN ('recommended','manual_review','high_risk')),
  report_data JSONB NOT NULL DEFAULT '{}',
  recruiter_decision TEXT CHECK (recruiter_decision IN ('advance','schedule_followup','reject')),
  decision_notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users own their reports" ON public.reports FOR ALL USING (auth.uid() = user_id);
CREATE INDEX IF NOT EXISTS idx_reports_user_id ON public.reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_created_at ON public.reports(created_at DESC);
```

**Team collaboration** (teams, invites, comments, votes, and the `team_id`
column on `reports`) is a second migration — run
[`backend/sql/002_team_collaboration.sql`](backend/sql/002_team_collaboration.sql)
after the schema above. Optional: skip it if you don't need team features —
everything else works fine without it, and team endpoints return a clear
503 rather than breaking anything.

---

## API Reference

Full Swagger UI at `/docs`. Every endpoint below except `/health` requires
`Authorization: Bearer <token>`.

```http
# Auth
POST   /api/v1/auth/signup                 Create recruiter account   (rate-limited: 8/hr per IP)
POST   /api/v1/auth/login                  Get JWT token              (rate-limited: 10/15min per IP)
GET    /api/v1/auth/me                     Current user

# Single-resume analysis
POST   /api/v1/analysis/upload             Upload one resume → job_id
GET    /api/v1/analysis/{job_id}/status    Poll progress

# Bulk upload + ranking  (Feature 1)
POST   /api/v1/bulk/upload                 Up to 50 resumes at once → batch_id
GET    /api/v1/bulk/{batch_id}/status      Live progress + score ranking
GET    /api/v1/bulk/{batch_id}/export.csv  Ranked candidates as CSV
GET    /api/v1/bulk/{batch_id}/duplicates  Cross-candidate similarity clusters (fraud-ring detection)

# ATS CSV import — same downstream pipeline as bulk upload
POST   /api/v1/ats/import                  ATS-exported CSV → batch_id (use /bulk/{id}/* endpoints above to track it)

# JD Match  (Feature 2)
POST   /api/v1/match/upload                JD (text or file) + resumes → batch_id
GET    /api/v1/match/{batch_id}/status     Live progress + match-% ranking
GET    /api/v1/match/{batch_id}/export.csv Ranked matches as CSV

# Public data verification  (Feature 3)
POST   /api/v1/verify/{report_id}/run      Run GitHub/education/cert/employer checks
GET    /api/v1/verify/{report_id}          Fetch last verification result

# Reports
GET    /api/v1/reports                     List (search, sort, pagination)
GET    /api/v1/reports/export.csv          Export all matching reports
GET    /api/v1/reports/{report_id}         Full report JSON
POST   /api/v1/reports/{report_id}/decision  Record recruiter decision
DELETE /api/v1/reports/{report_id}

# Teams  (requires the team_collaboration SQL migration)
POST   /api/v1/teams                       Create a team
GET    /api/v1/teams                       List teams you belong to
GET    /api/v1/teams/{team_id}/members     List members
POST   /api/v1/teams/{team_id}/invite      Invite by email (auto-accepts on their next login)
DELETE /api/v1/teams/{team_id}/members/{user_id}
DELETE /api/v1/teams/{team_id}

# Report Collaboration
POST   /api/v1/reports/{report_id}/share   Share a report with a team you belong to
POST   /api/v1/reports/{report_id}/unshare
GET    /api/v1/reports/{report_id}/comments
POST   /api/v1/reports/{report_id}/comments
DELETE /api/v1/reports/{report_id}/comments/{comment_id}
GET    /api/v1/reports/{report_id}/votes   Returns votes + tally + your own vote
POST   /api/v1/reports/{report_id}/vote    advance | reject | maybe — one per person, re-voting updates it

GET    /api/v1/health                      Health check — shows which services are configured
```

---

## How Analysis Works

```
Upload PDF/DOCX
      ↓
Text extraction (pdfminer.six / python-docx)
      ↓
Resume-likeness gate — rejects non-resumes BEFORE spending an AI call
(needs 2 of 3: contact info, resume section headers, work-history dates)
      ↓
Stage 1 — Extract  (temp=0.05, deterministic)
  → candidate info, skills, experience/project bullets EXACTLY as written
      ↓
Stage 2 — Analyze  (temp=0.1)
  → 6-dimension credibility score, AI-content-detection, risk flags,
    interview questions, recruiter summary
      ↓
[optional] JD match — one extra lightweight call against already-extracted data
[optional] Public verification — 4 parallel real-time API checks
      ↓
Store in Supabase (report_data jsonb) → Return report
```

Total time: **8–30 seconds** for one resume; bulk batches process up to 3
resumes concurrently (`BULK_CONCURRENCY`) to stay within free-tier LLM rate limits.

---

## Security

- JWT auth (HS256) on every data-touching endpoint; startup check refuses to
  silently run with the repo's default `SECRET_KEY` in production
- Per-IP rate limiting on login/signup (brute-force protection) + per-user
  rate limiting on analysis endpoints
- SSRF guard on every verification check that fetches a URL derived from
  resume text (blocks private/loopback/link-local/metadata-endpoint IPs,
  re-validated on every redirect hop)
- Strict allowlist sanitization on the reports search filter (prevents
  PostgREST filter-injection)
- Standard security headers (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, HSTS in production)
- Dependencies audited with `pip-audit` / `npm audit` in CI; known CVEs in
  `python-jose`, `python-multipart`, `pdfminer.six`, and Next.js have been patched

**Known open item:** FastAPI 0.110 (and its transitive Starlette version)
has a handful of lower-severity CVEs only fixed in much newer major versions.
Bumping this needs a dedicated regression-testing pass across the whole
endpoint surface before it ships — tracked, not yet done.

---

## Testing

```bash
cd backend
python -m pytest tests/ -v
```

254 tests across:
- **Unit** — resume heuristic, AI-content-detection merge logic, LLM fallback
  chain (mocked providers — proves Gemini→Groq→Anthropic actually falls
  through), SSRF guard (real DNS resolution), rate limiter, search sanitization,
  bulk/match ranking logic, verification response shapes
- **Integration** — real HTTP requests via `TestClient`: auth guards on every
  protected route, validation errors, 404 handling, security headers,
  consistent error-response shape

CI (`.github/workflows/ci.yml`) runs all of this plus a dependency audit and
frontend typecheck/build on every push and PR.

---

## Project Structure

```
hirelens/
├── .github/workflows/ci.yml       # pytest + pip-audit + frontend build, on every push
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI app, middleware, startup security checks
│   │   ├── core/                  # config, security, dependencies, exceptions, rate_limit
│   │   ├── services/
│   │   │   ├── ai/engine.py       # 2-stage analysis pipeline + provider fallback
│   │   │   ├── parser/            # PDF/DOCX/CSV extraction + resume-likeness heuristic
│   │   │   ├── queue/             # Redis-backed job/batch store (restart-proof)
│   │   │   ├── verify/            # GitHub/education/cert/employer checks + SSRF guard + trust assessment
│   │   │   ├── fraud/             # cross-candidate duplicate/template detection
│   │   │   └── teams/             # team access-control helpers (shared by reports + collaboration)
│   │   └── api/v1/endpoints/      # analysis, bulk, match, verify, ats, teams, collaboration, reports, auth, health
│   ├── sql/                       # Supabase schema migrations (run in order)
│   ├── tests/{unit,integration}/
│   └── requirements.txt / requirements-dev.txt
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── dashboard/         # search + sort + export-all
│       │   ├── analyze/           # single upload
│       │   ├── bulk/              # up to 50 at once + ATS import + duplicate check + live ranking
│       │   ├── match/             # JD paste/upload + resumes
│       │   ├── teams/             # create/invite/manage teams
│       │   └── report/[id]/       # full report incl. Verify + Discuss tabs
│       ├── hooks/                 # useAnalysis, useBulkAnalysis, useJdMatch
│       ├── components/            # VerdictStamp (shared design-system component)
│       ├── store/auth.ts          # Zustand auth store (hydration-safe)
│       └── lib/api.ts             # typed API client
├── render.yaml
└── vercel.json
```

---

## Cost (all free tiers, $0/mo)

| Service | Free Tier |
|---|---|
| Vercel | 100GB bandwidth |
| Render | 750 hrs/mo (free web service) |
| Supabase | 500MB DB, 50K MAU |
| Upstash Redis | 10K req/day |
| Gemini 2.5 Flash | Free tier, rate-limited — see fallback note above |
| Groq | Free tier fallback |
| GitHub API | 60 req/hr unauthenticated, 5000/hr with a free token |

---

## Roadmap

- [x] Single resume analysis (credibility, flags, skills, interview questions)
- [x] Non-resume rejection (invoices/cover letters/templates no longer get scored)
- [x] AI-generated-content detection (dedicated dimension + evidence)
- [x] Bulk upload (50 files) with ranking + CSV export
- [x] JD match (1 JD → many candidates) with missing-skills + best-fit
- [x] Real-time public verification — GitHub (full language breakdown, not
      just primary language), education (retry-based matching), certifications, employer
- [x] Combined Trust Assessment — rule-based (not another LLM call), weighs
      real-world verification evidence far more heavily than AI-writing-style signals
- [x] Verification feeds back into the headline recommendation — strong
      contradicting evidence (e.g. a claimed GitHub account that doesn't
      exist) downgrades "Recommended" → "Manual Review" → "High Risk" on the
      dashboard/rankings, not just buried in the Verify tab. Never auto-upgrades.
- [x] Cross-candidate duplicate/template detection — catches "resume mill" fraud rings
- [x] Redis-backed job/report store — survives process restarts, foundation for horizontal scaling
- [x] Dashboard search + sort + export-all
- [x] Working Gemini → Groq → Anthropic fallback (with regression test)
- [x] Security hardening (SSRF, rate limiting, injection sanitization, CVE patching)
- [x] CI/CD (GitHub Actions)
- [ ] Real task queue (Celery/RQ) — needed past ~2000 concurrent users; current
      BackgroundTasks approach is fine below that, see Architecture section
- [x] ATS CSV import (Greenhouse/Lever/Workday/etc — column auto-detection, reuses the bulk pipeline entirely)
- [x] Team collaboration (share reports with a team, comment, vote — invite-by-email with auto-accept on login, no email service required)
- [ ] Post-interview scorecard tie-back to resume claims
- [ ] FastAPI/Starlette major-version upgrade (needs dedicated regression pass)
- [ ] Next.js 15 upgrade
- [ ] Structural redesign of Analyze/Bulk/Match/Auth pages (colors/fonts already
      migrated to the new design system; Dashboard + Report page have the full treatment)
- [ ] Chrome extension (LinkedIn profile analysis) — deferred, lower priority for now
- [ ] Slack/Telegram/WhatsApp notifications — deferred, decide later
- [ ] PDF report download

---

## Architecture — Scaling Beyond Today

Current setup comfortably handles the free tier's realistic ceiling (a few
hundred concurrent users). Honest bottlenecks and what unlocks the next tier:

| Users | Bottleneck | Fix | Cost |
|---|---|---|---|
| 0–500 | None significant | — | $0 |
| 500–2000 | None significant now that job/report state is Redis-backed (survives restarts) | — | $0 (Upstash free tier) |
| 2000–5000 | `BackgroundTasks` runs in-process — fine for now, but a burst of large bulk batches can starve the event loop | Real task queue (Celery/RQ) on a Render Background Worker | ~$7–25/mo |
| 5000–10k+ | Single Render instance, no connection pooling tuning, no CDN, no error tracking | Horizontal scaling behind a load balancer, Supabase connection pooler, Sentry (free tier), CDN for static assets | ~$50–150/mo |

The job/report store (`app/services/queue/job_store.py`) is a Redis-backed,
dict-compatible drop-in — it was a real in-memory-dict-only reliability gap
before (any Render restart wiped every in-progress job), fixed without
touching the 5 endpoint files' logic beyond 3 one-line mutation-pattern fixes.

---

## License

MIT — see [LICENSE](LICENSE)
