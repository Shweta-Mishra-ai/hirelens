#!/usr/bin/env bash
#
# Everything .github/workflows/ci.yml runs, run locally, in the same order
# with the same versions and environment.
#
# This exists because GitHub Actions cannot always be relied on to answer:
# when an account has no Actions minutes left, every job is marked failed in
# about two seconds without a runner ever being assigned, and the red tick
# says nothing at all about the code. This script does.
#
#   ./scripts/verify.sh
#
set -uo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
FAILED=()

step() { printf '\n\033[1m── %s\033[0m\n' "$1"; }
ok()   { printf '   \033[32m✓ %s\033[0m\n' "$1"; }
bad()  { printf '   \033[31m✗ %s\033[0m\n' "$1"; FAILED+=("$1"); }

# CI pins Python 3.12. Using a different one still tells you most of what you
# need, but say so rather than quietly testing something else.
PY=$(command -v python3.12 || command -v python3)
PYV=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
[ "$PYV" = "3.12" ] || printf '\033[33m   note: CI uses Python 3.12, this is %s\033[0m\n' "$PYV"

# ── Backend ─────────────────────────────────────────────────────────────────
step "Backend — install"
cd "$ROOT/backend"
VENV="${VERIFY_VENV:-.venv-verify}"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip -q
if "$VENV/bin/pip" install -q -r requirements.txt -r requirements-dev.txt; then
  ok "dependencies installed"
else
  bad "dependency install"
fi

step "Backend — pytest"
if APP_ENV=development \
   SECRET_KEY=test-secret-key-for-ci-only-do-not-use-in-prod \
   ALLOWED_ORIGINS="http://localhost:3000" \
   "$VENV/bin/python" -m pytest tests/ -q --tb=short; then
  ok "tests pass"
else
  bad "backend tests"
fi

step "Backend — dependency audit"
"$VENV/bin/pip" install -q pip-audit
# Reported, not enforced — same as CI, which uses `|| true` here.
"$VENV/bin/python" -m pip_audit -r requirements.txt --desc --progress-spinner off || true

# ── Frontend ────────────────────────────────────────────────────────────────
cd "$ROOT/frontend"
export NEXT_PUBLIC_SUPABASE_URL=https://placeholder.supabase.co
export NEXT_PUBLIC_SUPABASE_ANON_KEY=placeholder-anon-key
export NEXT_PUBLIC_API_URL=http://localhost:8000

step "Frontend — install"
if npm install --no-audit --no-fund >/dev/null 2>&1; then ok "packages installed"; else bad "npm install"; fi

step "Frontend — typecheck"
if npx tsc --noEmit; then ok "no type errors"; else bad "typecheck"; fi

step "Frontend — unit tests"
if npm test; then ok "tests pass"; else bad "frontend tests"; fi

step "Frontend — build (lint runs inside next build)"
if npm run build >/dev/null; then ok "production build"; else bad "frontend build"; fi

# ── Result ──────────────────────────────────────────────────────────────────
printf '\n'
if [ ${#FAILED[@]} -eq 0 ]; then
  printf '\033[32m\033[1mEverything CI checks passes locally.\033[0m\n'
  exit 0
fi
printf '\033[31m\033[1mFailed: %s\033[0m\n' "${FAILED[*]}"
exit 1
