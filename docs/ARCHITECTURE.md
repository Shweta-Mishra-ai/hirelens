# Architecture

How a PDF becomes a credibility report, where every piece of state lives, and
why the system is built to degrade rather than fall over.

---

## The shape of it

```mermaid
flowchart LR
    UI["<b>Vercel</b><br/>Next.js 14 · App Router<br/>React · Tailwind · Zustand"]

    subgraph API["Render · FastAPI"]
        direction TB
        R["Routers"]
        PAR["Document parser"]
        ENG["Analysis engine"]
        VER["Verification services"]
        Q["Job + batch store"]
        R --> PAR --> ENG
        R --> VER
        R --> Q
    end

    subgraph Data["Data"]
        direction TB
        SB[("Supabase<br/>Postgres + Auth")]
        SQL[("SQLite fallback<br/>ephemeral")]
        RD[("Redis<br/>optional")]
    end

    subgraph Ext["External"]
        direction TB
        LLM["Gemini → Groq → Anthropic"]
        PUB["GitHub · university registry<br/>certificate + employer URLs"]
        MAIL["Resend / SMTP"]
    end

    UI -->|"JSON over HTTPS · Bearer JWT"| R
    ENG --> LLM
    VER --> PUB
    R --> MAIL
    R --> SB
    R -.->|"fallback only"| SQL
    Q --> RD
```

**One rule runs through all of it:** a failure in any external box degrades one
feature, never the request that touches it. The LLM falls through three
providers, verification isolates its four checks from each other, Redis is
optional, and the reports list raises a real error rather than returning an
empty page that reads as "you have no candidates".

---

## Analysing a resume

```mermaid
sequenceDiagram
    autonumber
    actor R as Recruiter
    participant UI as Next.js
    participant API as FastAPI
    participant P as Parser
    participant E as Engine
    participant L as LLM
    participant DB as Supabase

    R->>UI: Drops a PDF
    UI->>API: POST /analysis/upload
    API->>API: Size cap · magic bytes · ZIP expansion cap
    API-->>UI: 202 { job_id }
    Note over UI,API: The browser polls the job — nothing blocks

    API->>P: extract_text()
    P-->>API: plain text (3 PDF strategies, DOCX tables)
    API->>API: scan_for_injection(full text)
    API->>E: analyse()
    E->>L: extract prompt
    L-->>E: structured JSON
    E->>L: analysis prompt
    L-->>E: scores · flags · questions
    E->>E: clamp scores · career trajectory from real dates
    E->>E: sanity-check against the injection scan
    E-->>API: report
    API->>DB: persist
    API-->>UI: status: complete + report_id
```

**Why a job id and not a response.** An analysis is two LLM round trips and can
take 20–60 seconds. Holding the HTTP connection open for that ties up a worker
and dies to any proxy timeout in between. The upload returns immediately; the
work happens in a background task and the browser polls.

---

## Verification

Four independent checks, run concurrently, each isolated from the others:

```mermaid
flowchart TD
    START["POST /verify/{id}/run"] --> GATHER{"asyncio.gather<br/>return_exceptions=True"}
    GATHER --> GH["GitHub<br/>skills evidenced in real repos"]
    GATHER --> EDU["Education<br/>open university registry"]
    GATHER --> CERT["Certifications<br/>live-fetch any verify link"]
    GATHER --> EMP["Employers<br/>domain reachability"]
    GH & EDU & CERT & EMP --> TRUST["Trust assessment<br/>signed −100…100"]
    TRUST --> ADJ{"low_confidence<br/>with evidence?"}
    ADJ -->|yes| DOWN["Downgrade one level<br/>from the AI's ORIGINAL read"]
    ADJ -->|no| KEEP["Leave the verdict alone"]
    DOWN --> SAVE["Store on the report"]
    KEEP --> SAVE
```

Three deliberate asymmetries:

| Rule | Why |
|---|---|
| Strong contradicting evidence can **downgrade** a verdict | The AI scores the resume before anything is checked against the world. A GitHub account that does not exist outranks a good writing sample. |
| Nothing can **upgrade** a verdict | Verification passing does not resolve concerns verification never looked at — timeline gaps, inconsistent claims, unbaselined metrics. |
| Re-running lands on the same verdict | The drop is measured from the AI's original read, so clicking Verify twice cannot walk a candidate down two levels on the same evidence. |

Every URL the candidate can influence — certificate links, guessed employer
domains, ATS resume URLs — goes through an SSRF guard that re-validates on
**every redirect hop**, not just the first.

---

## Where state lives

```mermaid
flowchart TB
    subgraph Durable["Durable — survives a restart"]
        A["auth.users · profiles"]
        B["reports · report_data JSONB"]
        C["teams · team_members · team_invites"]
        D["report_comments · report_votes"]
    end

    subgraph Process["Process-local — a cache, nothing more"]
        E["_jobs · per-file analysis progress"]
        F["_mem_batches · batch grouping"]
        G["_mem_rate_limit · when Redis is absent"]
    end

    Process -.->|"rebuilt from"| Durable
```

The distinction is load-bearing. Everything that must outlive the process is
written to Postgres (or the local fallback) first, and the in-process copy
exists only to save a round trip — so replacing the container costs nothing
but a cache. An analysis whose progress is lost that way is recovered from
the report it produced, by job id.

**Redis is optional on purpose.** Without it, rate limits and batch grouping
are per-process, which is correct for the single-worker free tier. Setting
`REDIS_URL` makes both shared, which is what horizontal scaling needs.

---

## Degrading instead of breaking

| What goes wrong | What happens |
|---|---|
| Gemini rate-limits | Falls straight through to Groq, then Anthropic — no backoff spent on a 429 |
| All three LLMs fail | Upload is refused up front with `analysis_unavailable`, not a half-written report |
| Supabase is unreachable at signup | **503.** No local shadow account, because its user id could never own a Supabase row |
| Supabase rejects a login | 401 stands. A stale local password cannot override the identity provider |
| Supabase blips mid-session | Reports list raises a real error; the co-pilot says "nothing has been lost" rather than "not found" |
| One verification check throws | The other three still return; the failing one reports `error` |
| A stored report has the wrong shape | Coerced at the read boundary — one odd report cannot take down the whole list |
| A panel throws while rendering | Its error boundary catches it; navigation and every other panel stay up |
| A 380 KB DOCX unpacks to 194 MB | Refused from the archive directory, before a byte is decompressed |

---

## Request lifecycle

```mermaid
flowchart LR
    REQ[Request] --> CORS[CORSMiddleware]
    CORS --> SEC[Security headers]
    SEC --> RID["Request id + timing<br/>catch-all → 500 JSON"]
    RID --> GZ[GZip]
    GZ --> ROUTE[Route]
    ROUTE --> RESP[Response]
    RESP --> REQ
```

CORS is **outermost** by design, so that error responses carry the same
headers as successful ones. A 500 that the browser refuses to hand to the app
is indistinguishable from the API being unreachable — everything the server
says, including "something went wrong", has to be readable by the app that
asked.

Every error response carries the same envelope:

```json
{ "error": "machine_code", "message": "A sentence a person can act on.", "request_id": "a1b2c3d4" }
```

---

## Layout

```
backend/
  app/
    api/v1/endpoints/   analysis · bulk · match · ats · reports · verify
                        copilot · collaboration · teams · auth · health
    core/               config · security · dependencies · exceptions
                        local_db · rate_limit · shapes
    services/
      ai/               engine (3-provider fallback) · career_trajectory
      verify/           github · education · certification · company
                        ssrf_guard · trust_assessment
      parser/           document_parser · csv_import · resume_heuristic
      fraud/            duplicate_detection · injection_detection
      queue/            job_store · batch_store
      teams/            access
      email/            sender
      directory.py      user id → a person's name, on either store
  sql/                  001 core · 002 collaboration · 003 notifications
  tests/                unit/ · integration/ · fake_supabase.py

frontend/
  src/
    app/                dashboard · analyze · bulk · match · report/[id] · teams
                        error.tsx · not-found.tsx · global-error.tsx
    components/         ui/ (design system) · report/ (panels) · AppShell
    hooks/              useBulkAnalysis · useJdMatch · useGoogleAuth
    lib/                api · format · cn · list · design-tokens
    store/              auth (Zustand + persist)
```
