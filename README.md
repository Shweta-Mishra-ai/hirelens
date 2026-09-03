<div align="center">

# 🔎 HireLens

### AI-Powered Resume Credibility, Fraud Detection & Recruiter Intelligence Platform

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-14.2-000?style=flat-square&logo=next.js)](https://nextjs.org)
[![Tests](https://img.shields.io/badge/backend%20tests-336%20passing-10B981?style=flat-square)](backend/tests)
[![Capacity](https://img.shields.io/badge/Capacity-5%2C000%20Recruiters-6366F1?style=flat-square)](#capacity--scale-hardening-5000-active-users)


**Upload a resume → get a 6-dimension credibility score, AI-content detection, risk flags anchored to exact text, predictive talent velocity, and real-time public-data verification — built for production scale.**

</div>

---

## ⚠️ Read this first

HireLens is a decision-support platform, not an automated gatekeeper. Every score, flag, and "verified"/"not found" result is a **signal for a human recruiter to investigate further** — never treat any output here as proof of fraud or an automated reject/hire decision.

---

## What HireLens Does Today

HireLens ships with **six working analysis and intelligence modules** plus **real-time public verification** and **5,000 active user capacity hardening** — fully wired and verified end-to-end.

### 1. Single / Bulk Resume Credibility Analysis
Upload one resume, or up to 50 at once (`/bulk`). Each one gets:
- **Credibility Score** (0–100) across 6 dimensions — timeline, skills consistency, education, project authenticity, resume quality, and **content authenticity**.
- **AI-Generated-Content Detection** — dedicated check for whether the resume text itself was substantially AI-written vs. genuinely candidate-written, with quoted evidence.
- **Risk Flags** — every flag quotes the exact resume text that triggered it.
- **Skills Verification** — claimed vs. actually evidenced skills in work history.
- **Interview Questions** — generated specifically to probe this candidate's flags.

Bulk upload auto-ranks candidates by score with CSV export.

### 2. Live Interactive Candidate Interview Co-Pilot & Question Customizer (`/report/[id]` → Co-Pilot Tab) *(Feature A)*
- Customize probe questions and check them off during live candidate interviews.
- Record structured interviewer ratings across **Technical Depth**, **Problem Solving**, **Culture Fit**, and **Authenticity**.
- Store live evaluation notes and recommendation overrides via `POST /api/v1/reports/{report_id}/copilot`.

### 3. Predictive Talent Velocity & Career Growth Index *(Feature B)*
- Projects 5–10 year candidate career growth trajectory.
- Calculates **Promotion Cadence** (months/promotion), **Growth Velocity Index** (0–100), and **Retention Stability Score**.
- Embedded directly into the Candidate Intelligence Report (`report["talent_velocity"]`).

### 4. Enterprise Talent Analytics & Workforce Intelligence (`/dashboard` / `GET /api/v1/reports/analytics`) *(Feature C)*
- Aggregate metrics analyzing overall candidate pool health.
- Credibility distribution (Recommended vs High Risk vs Manual Review).
- Top identified skill clusters and risk flag category breakdown.

### 5. JD Match (`/match`)
Paste or upload a job description, upload multiple resumes, get each candidate's match %, missing skills, and a highlighted best-fit — reusing the same credibility pipeline.

### 6. Real-Time Public Data Verification (`/report/[id]` → Verify tab)
Real-time (not cached, not mocked) checks against:
- **GitHub** — live `api.github.com` calls cross-checking claimed skills against full repo language breakdowns.
- **Education** — university-domain registry lookup with automatic multi-variant retry logic.
- **Certifications** — live URL verification for embedded certificate links.
- **Employers** — company-website domain check.

Feed into a **Combined Trust Assessment** weighing real-world verification evidence far more heavily than writing-style signals.

### 7. ATS CSV Import & Cross-Candidate Fraud Detection
- **ATS Import**: Import candidate CSV exports from Greenhouse/Lever/Workday/BambooHR.
- **Duplicate Detection**: Cross-candidate shingling + Jaccard similarity detecting resume mills and template fraud rings.

### 8. Team Collaboration (`/teams`, report page → "Discuss" tab)
Create a team, invite teammates by email, share reports, comment, and vote (Advance / Maybe / Reject). Auto-accepts invites on user login/signup without third-party email service requirements.

---

## Capacity & Scale Hardening (5,000 Active Users)

HireLens is hardened for production launch supporting **5,000 active recruiters/users**:
1. **5,000 Recruiter Capacity Enforcement**:
   - Signup (`/api/v1/auth/signup`) checks active user capacity. When count reaches 5,000, signups return `429 Too Many Requests` (`CapacityLimitExceeded`).
2. **Database Connection Pooling**:
   - `get_db()` in `dependencies.py` reuses a thread-safe singleton Supabase client (`_supabase_client`), eliminating socket churn under high traffic.
3. **Dual-Layer Authentication Resilience**:
   - Uses Supabase Auth when configured, and falls back to a secure local in-memory store (`_mem_users`) for standalone/dev environments without throwing database errors.
4. **Auto-Redirection**:
   - Authenticated users on `/login` and `/signup` automatically redirect to `/dashboard`.

---

## Load Handling, Error Handling & Validation

### Load Handling
- **Redis Rate Limiting**: Per-IP limits on auth endpoints (login: 10/15min, signup: 8/hr) + per-user limits on analysis endpoints.
- **Concurrency Control**: Bulk & JD match uploads use `asyncio.Semaphore(BULK_CONCURRENCY)` to prevent event-loop starvation and stay within LLM rate limits.
- **File Size Ceiling**: Max file size capped at 10MB (`MAX_FILE_SIZE_MB`).

### Input & Security Validation
- **MIME & Magic Byte Verification**: `validate_upload()` checks PDF/DOCX magic bytes to reject executable/malicious uploads.
- **SSRF Protection**: `ssrf_guard.py` validates verification URLs against loopback, private, link-local, and cloud metadata IPs (169.254.169.254).
- **Injection Defense**: Multi-stage prompt fencing + heuristic injection scan.

### Error Handling
- All endpoints return structured JSON payloads with tracking `x-request-id` headers on every response:
```json
{
  "error": "capacity_limit_exceeded",
  "message": "Registration capacity limit of 5,000 active recruiters reached.",
  "request_id": "req_xyz123"
}
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| AI Engine | **Gemini 2.5 Flash** (primary) → **Groq `openai/gpt-oss-120b`** (fallback) → Claude Sonnet 5 (optional 3rd fallback) |
| Backend | **FastAPI** 0.110 · Python 3.12 / 3.14 · pdfminer.six · python-docx |
| Frontend | **Next.js 14.2** (App Router) · TypeScript · Tailwind CSS |
| Auth & DB | **Supabase** (PostgreSQL + Auth) + Local Fallback Auth Store |
| Cache & Queue | **Upstash Redis** — rate limiting + bulk-batch state |
| Deploy | **Vercel** (frontend) · **Render** (backend) |
| Testing & CI | **pytest** (336 passing tests) + **TypeScript type-check** + GitHub Actions CI |

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

Run the automated test suite (336 passing unit, integration, capacity limit, load handling, and E2E tests):

```bash
# Backend Test Suite
cd backend
python -m pytest tests/ -v

# Frontend Type Check
cd frontend
npm run type-check

# Frontend Production Build
npm run build
```

---

## Environment Variables

### Backend (`backend/.env`)
```env
APP_ENV=production
SECRET_KEY=<32+ char random string>

# Supabase (app falls back to local auth store if unconfigured)
SUPABASE_URL=https://xyz.supabase.co
SUPABASE_SERVICE_KEY=...
SUPABASE_ANON_KEY=...

# LLM Providers
GEMINI_API_KEY=...
GROQ_API_KEY=...
ANTHROPIC_API_KEY=...

# Public Verification (raises limit 60/hr → 5000/hr)
GITHUB_TOKEN=...

# Redis (rate limiting & batch state)
REDIS_URL=rediss://default:xxx@your-db.upstash.io:6379

ALLOWED_ORIGINS=http://localhost:3000,https://your-app.vercel.app
```

---

## API Summary

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/auth/signup` | POST | Signup recruiter account (Capacity: 5,000) |
| `/api/v1/auth/login` | POST | Login recruiter account |
| `/api/v1/analysis/upload` | POST | Single resume upload |
| `/api/v1/analysis/{job_id}/status` | GET | Poll analysis status |
| `/api/v1/reports` | GET | List reports (search, sort, pagination) |
| `/api/v1/reports/{id}/copilot` | POST/GET | Candidate Interview Co-Pilot & Scorecard |
| `/api/v1/reports/analytics` | GET | Enterprise Talent Analytics & Pool Intelligence |
| `/api/v1/bulk/upload` | POST | Bulk upload up to 50 resumes |
| `/api/v1/bulk/{id}/duplicates` | GET | Cross-candidate duplicate fraud detection |
| `/api/v1/match/upload` | POST | JD match upload |
| `/api/v1/verify/{id}/run` | POST | Real-time public data verification |
| `/api/v1/teams` | POST/GET | Team workspace creation and listing |
| `/api/v1/health` | GET | System health check |
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
- [x] 5,000 active user capacity enforcement
- [x] Supabase connection pooling & fallback auth resilience
- [x] Interactive Candidate Interview Co-Pilot & Custom Probe Generator
- [x] Predictive Talent Velocity & Career Growth Index
- [x] Enterprise Talent Analytics & Workforce Intelligence
- [x] Complete End-to-End Test Suite (`test_e2e_complete_flow.py`)
