<div align="center">

<img src="docs/images/dashboard.png" alt="HireLens dashboard" width="860">

# HireLens

**Resume credibility analysis that shows its working.**

Every score cites the sentence that produced it. Every claim is checked against
public record. Nothing is decided for you.

[![CI](https://img.shields.io/github/actions/workflow/status/Shweta-Mishra-ai/hirelens/ci.yml?branch=main&style=flat-square&label=CI)](../../actions)
[![Tests](https://img.shields.io/badge/tests-1%2C307%20backend%20·%20151%20frontend-10B981?style=flat-square)](#testing)
[![Coverage](https://img.shields.io/badge/backend%20coverage-87%25-10B981?style=flat-square)](#testing)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-14.2-000?style=flat-square&logo=next.js)](https://nextjs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Supabase](https://img.shields.io/badge/Supabase-Postgres-3ECF8E?style=flat-square&logo=supabase&logoColor=white)](https://supabase.com)
[![Licence](https://img.shields.io/badge/licence-proprietary-6366F1?style=flat-square)](LICENSE)

[Architecture](docs/ARCHITECTURE.md) ·
[Deployment](docs/DEPLOYMENT.md) ·
[API](docs/API.md) ·
[Security](docs/SECURITY.md) ·
[Contributing](CONTRIBUTING.md)

</div>

---

## Read this first

HireLens is **decision support, not a gatekeeper**. Every score, flag and
"verified"/"not found" result is a signal for a human recruiter to investigate
— never proof of misconduct, and never grounds for an automated reject.

Where the product cannot know something, it says so instead of guessing. That
constraint is the reason it exists.

---

## The problem

A recruiter reading forty resumes for one role has no way to tell which claims
are load-bearing. "Improved performance by 40%" reads the same whether it is
measured or invented. Screening tools answer this with a number and no
argument — which moves the guessing rather than removing it.

HireLens takes the opposite position: **show the evidence, and let the person
decide.**

<div align="center">
<img src="docs/images/report-flags.png" alt="Every flag quotes the resume text that raised it" width="820">
<br><em>Every concern quotes the sentence that raised it. They are prompts to ask a question, not conclusions.</em>
</div>

---

## What it does

<table>
<tr>
<td width="50%" valign="top">

### Credibility analysis
Six scored dimensions, a written summary, and risk flags that **quote the
resume text** that triggered them. One file or fifty at once.

</td>
<td width="50%" valign="top">

### Public-data verification
GitHub skills evidenced in real repositories, institutions checked against an
open registry, certificate links live-fetched, employer domains probed. Four
checks, run concurrently, each isolated.

</td>
</tr>
<tr>
<td valign="top">

### Career trajectory
Total experience, median tenure, advancement cadence and gaps — computed from
the **actual dates on the page** by a union-of-intervals pass. No model
involved, so no invented metric.

</td>
<td valign="top">

### Interview co-pilot
Questions generated from that candidate's specific flags, a scorecard, and
private notes that stay private. Tested for cross-tenant access on both
storage paths.

</td>
</tr>
<tr>
<td valign="top">

### JD match
Rank a shortlist against one job description — pasted, uploaded, or saved under
a name and reused. Matching skills, missing skills, a verdict and a rationale
per candidate.

</td>
<td valign="top">

### ATS import + team review
Import a Greenhouse/Lever/Workday CSV; resumes download and analyse through the
same pipeline. Share a candidate with a team, comment, and vote.

</td>
</tr>
</table>

### The metric that is honest about itself

An earlier build shipped a "Talent Velocity" score computed as
`60 + roles×5 + skills×2` — a number that looked analytical, saturated near 98
for anyone with a long resume, and measured nothing. It was replaced with
metrics derived from real employment dates, and when the dates are too sparse
to support a conclusion the panel says `insufficient_data` and explains why.

---

## How it works

```mermaid
flowchart LR
    A["PDF / DOCX"] --> B["Parse<br/>3 PDF strategies"]
    B --> C["Injection scan<br/>full text"]
    C --> D["Extract<br/>structured JSON"]
    D --> E["Analyse<br/>scores · flags · questions"]
    E --> F["Trajectory<br/>from real dates"]
    F --> G["Report"]
    G -.->|"on demand"| H["Verify against<br/>public record"]
    H --> I["Trust assessment<br/>can downgrade, never upgrade"]
```

The LLM falls through **Gemini → Groq → Anthropic**, and a rate limit hands off
immediately rather than spending a backoff first. If every provider is
unconfigured, uploads are refused up front with a clear message instead of
producing a half-written report.

Full detail in [**docs/ARCHITECTURE.md**](docs/ARCHITECTURE.md).

---

## Screenshots

<table>
<tr>
<td width="50%"><img src="docs/images/report-overview.png" alt="Report overview"><br><sub><b>Report</b> — score, summary, and the evidence behind it</sub></td>
<td width="50%"><img src="docs/images/report-verify.png" alt="Verification"><br><sub><b>Verify</b> — public-record checks with a signed trust score</sub></td>
</tr>
<tr>
<td><img src="docs/images/report-copilot.png" alt="Interview co-pilot"><br><sub><b>Co-Pilot</b> — scorecard and private interview notes</sub></td>
<td><img src="docs/images/match.png" alt="JD match"><br><sub><b>JD Match</b> — rank a shortlist against one role</sub></td>
</tr>
<tr>
<td><img src="docs/images/bulk.png" alt="Bulk upload"><br><sub><b>Bulk</b> — up to 50 resumes, live ranking</sub></td>
<td><img src="docs/images/report-questions.png" alt="Interview questions"><br><sub><b>Questions</b> — generated from this candidate's own flags</sub></td>
</tr>
<tr>
<td><img src="docs/images/teams.png" alt="Teams"><br><sub><b>Teams</b> — share a candidate, comment, vote</sub></td>
<td><img src="docs/images/analyze.png" alt="Analyze"><br><sub><b>Analyze</b> — one resume, with the limits stated up front</sub></td>
</tr>
</table>

<div align="center">
<img src="docs/images/mobile-dashboard.png" alt="HireLens on a phone" width="300">
<br><em>The same dashboard at 390px — a recruiter reviewing between meetings gets the whole thing, not a cut-down version.</em>
</div>

---

## Quick start

```bash
git clone https://github.com/Shweta-Mishra-ai/hirelens.git && cd hirelens

# API
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                                  # add GEMINI_API_KEY (free)
uvicorn app.main:app --reload --port 8000

# Frontend, in a second terminal
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

App on **localhost:3000**, interactive API docs on **localhost:8000/docs**.

Leave the Supabase variables unset and everything runs on a local SQLite file —
no cloud account needed to develop. For production, follow
[**docs/DEPLOYMENT.md**](docs/DEPLOYMENT.md): five SQL files, one Render
service, one Vercel project.

---

## Built to degrade, not to break

A screening tool is used under time pressure, often on a shortlist that took
weeks to assemble. It is designed so that no single failure costs a recruiter
their work.

| Condition | Behaviour |
|---|---|
| The primary model is rate-limited | Falls through to the next provider immediately |
| No model is reachable | Uploads are refused up front, rather than producing a partial report |
| The database is unreachable at signup | A clear 503 — accounts are never created outside the identity store |
| The database blips mid-session | A real error the UI can retry. An empty page never stands in for "your candidates are gone" |
| One verification check fails | The other three still return, and the failing one says so |
| A stored report is shaped unexpectedly | Coerced at the read boundary, so one record cannot affect the rest of the list |
| A panel fails to render | Contained by its error boundary — navigation and every other panel stay up |
| An analysis outlives the process that ran it | Recovered from storage and reported complete, never re-charged |
| An upload is engineered to exhaust memory | Refused from the archive header, before anything is decompressed |

Every row is covered by a test that fails if the behaviour regresses.

---

## Testing

```bash
cd backend && python -m pytest tests/ -v           # 1,307 tests
cd frontend && npm test                            # 151 tests
cd frontend && npm run build                       # types + production build
```

| | |
|---|---|
| Backend | **1,307** tests · **87%** coverage |
| Frontend | **151** tests · strict TypeScript · zero lint warnings |
| CI | pytest · vitest · `pip-audit` · `npm audit` · production build |

Two things the suite does that a typical one does not:

**Both storage paths are covered.** Every endpoint has a Supabase
implementation and a local fallback, and both are exercised.
`tests/fake_supabase.py` holds the real column list for every table and raises
the same errors PostgREST would, so a query that could only fail against the
real database fails in CI instead.

**Undefined names fail the build.** A pyflakes check runs as a test, so a name
used before it is imported or defined is caught immediately rather than on the
one request that reaches that line.

---

## Performance

Measured locally against 500 stored reports, cold cache:

| Endpoint | p50 |
|---|---|
| `GET /reports` | 6.4 ms |
| `GET /reports?search=` | 6.1 ms |
| `GET /reports?sort=score_desc` | 6.2 ms |
| `GET /reports/analytics` | 5.8 ms |
| `GET /reports/export.csv` | 11.8 ms |
| `GET /health` | 3.0 ms |

Frontend: 87.3 kB shared JS, 176–196 kB First Load per route. Eight unused
dependencies were removed rather than carried.

---

## Stack

**Backend** — FastAPI · Python 3.12 · Pydantic v2 · Supabase (Postgres + Auth)
· SQLite fallback · optional Redis · pdfminer.six · python-docx · bcrypt

**Frontend** — Next.js 14 App Router · TypeScript (strict) · Tailwind ·
Zustand · Vitest + Testing Library

**AI** — Gemini 2.5 Flash, with Groq and Anthropic as fallbacks

---

## Documentation

| | |
|---|---|
| [**Architecture**](docs/ARCHITECTURE.md) | Diagrams, request lifecycle, where state lives, the degradation table |
| [**Deployment**](docs/DEPLOYMENT.md) | Supabase schema, Render, Vercel, keeping the free tier awake |
| [**API**](docs/API.md) | Every endpoint, the error envelope, the limits |
| [**Security**](docs/SECURITY.md) | Tenancy model, resume-borne attacks, what is deliberately not disclosed |
| [**Contributing**](CONTRIBUTING.md) | Setup, conventions, what a good PR looks like |

---

## Licence

**Proprietary.** Copyright © 2026 Shweta Mishra, all rights reserved — see
[LICENSE](LICENSE). This is not open-source software: no licence to use, copy,
modify or distribute it is granted by default, and viewing this repository
does not grant one.

Every open-source dependency permits commercial, closed-source distribution —
no GPL, AGPL or SSPL anywhere in the tree. The audit and the obligations that
do apply are in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

Commercial licensing and evaluation enquiries: add your contact address to
`LICENSE`.
