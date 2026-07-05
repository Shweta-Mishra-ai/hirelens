<div align="center">

# 🔎 HireLens

### AI-Powered Recruiter Decision Intelligence

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Vercel-000?style=flat-square&logo=vercel)](https://hirelens.vercel.app)
[![API](https://img.shields.io/badge/API%20Docs-FastAPI-009688?style=flat-square&logo=fastapi)](https://hirelens-api.onrender.com/docs)
[![License](https://img.shields.io/badge/License-MIT-6366F1?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-14-000?style=flat-square&logo=next.js)](https://nextjs.org)
[![Gemini](https://img.shields.io/badge/Gemini-2.5%20Flash-4285F4?style=flat-square&logo=google)](https://aistudio.google.com)

**Analyze resumes for credibility signals, skills gaps, and risk — in under 30 seconds.**  
Built for recruiters who make better decisions with evidence, not guesswork.

</div>

---

## What it does

Upload a PDF or DOCX resume → Gemini 2.5 Flash reads the actual file → returns:

- **Credibility Score** (0–100) with 5-dimension breakdown
- **Risk Flags** — every flag anchored to exact resume text
- **Skills Verification** — claimed vs evidenced in work history
- **Timeline Analysis** — employment gaps, promotion velocity
- **Interview Questions** — targeted to this candidate's specific signals
- **Recruiter Summary** — 4-sentence evidence-based briefing

> HireLens assists recruiters. Final hiring decisions always rest with humans.

---

## Stack

| Layer | Technology |
|---|---|
| AI | **Gemini 2.5 Flash** (primary) · Groq Llama 3.1 (fallback) |
| Backend | **FastAPI** · Python 3.11 · pdfminer.six · python-docx |
| Frontend | **Next.js 14** (App Router) · TypeScript · Tailwind CSS |
| Auth + DB | **Supabase** (PostgreSQL + Auth + Storage) |
| Cache | **Upstash Redis** (rate limiting) |
| Deploy | **Vercel** (frontend) · **Render** (backend) |

---

## Quick Start

```bash
# Clone
git clone https://github.com/Shweta-Mishra-ai/hirelens.git
cd hirelens

# One-command setup (interactive — collects your keys)
chmod +x deploy.sh && ./deploy.sh
```

The script will:
1. Install all dependencies
2. Collect your API keys
3. Push to GitHub
4. Walk you through Render + Vercel deployment

### Manual setup

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env         # Fill in your keys
uvicorn app.main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
cp .env.local.example .env.local  # Fill in your keys
npm run dev

# App: http://localhost:3000
# API: http://localhost:8000/docs
```

---

## Environment Variables

### Backend (`backend/.env`)
```env
APP_ENV=production
SECRET_KEY=<32-char random string>

# Supabase (required)
DATABASE_URL=postgresql://...
SUPABASE_URL=https://xyz.supabase.co
SUPABASE_SERVICE_KEY=...
SUPABASE_ANON_KEY=...

# LLM — at least one required
GEMINI_API_KEY=...        # aistudio.google.com (free)
GROQ_API_KEY=...          # console.groq.com (free, fallback)

# Optional
REDIS_URL=...             # upstash.com (free tier)
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

Run once in Supabase SQL Editor:

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

---

## API Reference

Full Swagger UI at `/docs` when running locally or deployed.

```http
POST /api/v1/auth/signup         Create recruiter account
POST /api/v1/auth/login          Get JWT token
POST /api/v1/analysis/upload     Upload resume → returns job_id
GET  /api/v1/analysis/{id}/status  Poll analysis progress
GET  /api/v1/reports             List all reports (paginated)
GET  /api/v1/reports/{id}        Full report JSON
POST /api/v1/reports/{id}/decision  Submit hiring decision
GET  /api/v1/health              Health check
```

---

## How Analysis Works

```
Upload PDF/DOCX
      ↓
Text Extraction (pdfminer / python-docx)
      ↓
Stage 1 — Extract (Gemini 2.5 Flash, temp=0.05)
  → candidate info, skills, experience, education, projects
      ↓
Stage 2 — Analyze (Gemini 2.5 Flash, temp=0.1)
  → credibility scores, risk flags, interview questions, summary
      ↓
Store in Supabase → Return report
```

Total time: **8–25 seconds** depending on resume length.

---

## Project Structure

```
hirelens/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + middleware
│   │   ├── core/                # config, security, dependencies, exceptions
│   │   ├── services/
│   │   │   ├── ai/engine.py     # Gemini 2.5 Flash pipeline + fallback
│   │   │   └── parser/          # PDF + DOCX extraction
│   │   └── api/v1/endpoints/    # analysis, reports, auth, health
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── app/                 # Next.js App Router pages
│       │   ├── dashboard/       # Reports list + stats
│       │   ├── analyze/         # Upload + real-time progress
│       │   └── report/[id]/     # Full report view
│       ├── hooks/useAnalysis.ts # Upload + polling logic
│       ├── store/auth.ts        # Zustand auth store
│       └── lib/api.ts           # Typed API client
├── deploy.sh                    # One-command setup script
├── render.yaml                  # Render deployment config
└── vercel.json                  # Vercel deployment config
```

---

## Cost (MVP Phase)

| Service | Free Tier | Sufficient for |
|---|---|---|
| Vercel | 100GB bandwidth | ~50K page views/mo |
| Render | 750 hrs/mo | Demo + early users |
| Supabase | 500MB DB, 50K MAU | First 500 users |
| Upstash | 10K req/day | Rate limiting |
| Gemini 2.5 Flash | 1M tokens/day | ~500 analyses/day |
| **Total** | **$0/mo** | **Investor demo** |

---

## Roadmap

- [x] PDF + DOCX parsing
- [x] Gemini 2.5 Flash analysis
- [x] Evidence-anchored risk flags
- [x] Skills verification matrix
- [x] Recruiter decision feedback loop
- [x] Supabase auth + Row Level Security
- [ ] LinkedIn comparison (with consent)
- [ ] GitHub profile analysis
- [ ] ATS plugin (Greenhouse, Ashby)
- [ ] Bulk upload
- [ ] Team workspaces
- [ ] Candidate explanation report (GDPR)
- [ ] Fine-tuned scoring model from recruiter feedback

---

## License

MIT — see [LICENSE](LICENSE)

---

<div align="center">

Built with precision · Questions? [Open an issue](https://github.com/Shweta-Mishra-ai/hirelens/issues)

</div>
