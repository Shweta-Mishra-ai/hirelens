# Contributing

Thanks for looking. This document is short on ceremony and specific about the
two or three things that actually matter here.

> **A note on licensing.** HireLens is proprietary — see [LICENSE](LICENSE).
> Contributing does not grant you a licence to use the software, and by
> submitting a change you assign its copyright to the project owner. If you
> are not sure whether that is what you want, ask before you start.

---

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env          # a free GEMINI_API_KEY is enough
uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install && cp .env.local.example .env.local && npm run dev
```

Leave the Supabase variables unset. Everything runs on a local SQLite file, so
you never need a cloud account to develop — but see *Both paths* below, because
that convenience is also a trap.

---

## Before you open a PR

```bash
cd backend  && python -m pytest tests/ -q
cd frontend && npm test && npx tsc --noEmit && npm run lint && npm run build
```

CI runs the same, plus `pip-audit` and `npm audit`.

---

## The three rules that carry their weight

### 1 · Both paths

Every endpoint has a **Supabase** implementation and a **local fallback**, and
`SUPABASE_URL` is unset under test — so without care, the branch that runs in
production is the one nothing exercises. A query that is wrong only against
the real database is exactly the kind that reaches customers.

Use `tests/fake_supabase.py`. It carries the real column list for every table
and raises the same `PGRST204` the database would, and a test parses
`backend/sql/` to check those lists stay in step. **If you add a column, update
`SCHEMA` in that file and the SQL together.**

### 2 · A test that would fail without your fix

Before committing a fix, revert it and watch the new test go red:

```bash
git stash push -- path/to/the/file.py
python -m pytest tests/path/to/test_it.py -q     # expect failures
git stash pop
```

A test that passes both ways documents nothing.

### 3 · Errors that a person can act on

Every failure uses the same envelope, and `message` is written for a recruiter,
not a developer:

```python
raise FileTooLarge("That file is 14MB. The limit is 10MB per resume.")
```

Three things never appear in a response: a traceback, a library's internal
message, and an API key. The Gemini key lives in a query string, so httpx puts
it in connection errors — it is masked before anything is logged.

---

## Conventions

**Python** — 4 spaces, type hints on anything public, `snake_case`. Comments
explain *why*, especially when the code looks odd on purpose. If you are fixing
something subtle, say what the old behaviour was.

**TypeScript** — strict mode, no `any` in new code, functional components.
Anything reading a stored blob goes through `asList` / the shape guards, because
a field is only the type you expect until it is not.

**Commits** — a subject that says what changed for a user, then a body
explaining why. Prefer *"Stop one odd report taking the whole app down"* over
*"fix: add shape guards"*.

---

## Adding a verification check

1. New module in `backend/app/services/verify/`.
2. Any URL the candidate influences goes through `ssrf_guard.is_public_http_url`
   — **re-checked on every redirect hop**, not just the first. Checking only
   the original URL is no check at all.
3. Add it to the `asyncio.gather(..., return_exceptions=True)` in
   `endpoints/verify.py` so one failure cannot take the others down.
4. Give it weight in `trust_assessment.py`, and remember the asymmetry:
   evidence may downgrade a verdict, never upgrade it.
5. Test it against a mocked `httpx` transport. No test may touch the network.

---

## Where things live

```
backend/app/api/v1/endpoints/   routes
backend/app/services/           the actual work
backend/app/core/               config, security, shapes, local_db
backend/sql/                    schema, run in numeric order
frontend/src/components/ui/     the design system
frontend/src/components/report/ report panels
frontend/src/lib/               api client, formatters, guards
```

---

## Reporting a bug

Include what you did, what happened, what you expected, and the `request_id`
from the response — it is in the error body and the `X-Request-ID` header, and
it ties straight to the server log.

For a security issue, open a private advisory instead. See
[docs/SECURITY.md](docs/SECURITY.md).
