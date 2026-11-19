#!/usr/bin/env bash
#
# Run the Supabase-path tests against a real Postgres + PostgREST.
#
# Every other Supabase test uses tests/fake_supabase.py — our reading of
# PostgREST. This starts the real thing in Docker, applies every migration in
# backend/sql in order, seeds three users, and runs tests/postgrest with the
# app's own supabase-py client pointed at it. It catches the queries a fake
# cannot: a JSON-path select PostgREST rejects, an upsert whose conflict
# target has no unique index, a policy or grant that blocks the service role.
#
#   ./scripts/postgrest_e2e.sh
#
# Needs Docker and the backend venv (scripts/verify.sh creates one). Image
# names can be overridden for a registry mirror:
#   E2E_PG_IMAGE=mirror.gcr.io/library/postgres:16-alpine
#   E2E_PGRST_IMAGE=mirror.gcr.io/postgrest/postgrest:v12.2.3
#
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
PY="${E2E_PYTHON:-$ROOT/backend/${VERIFY_VENV:-.venv-verify}/bin/python}"
PG_IMAGE="${E2E_PG_IMAGE:-postgres:16-alpine}"
PGRST_IMAGE="${E2E_PGRST_IMAGE:-postgrest/postgrest:v12.2.3}"
NET=hirelens-e2e
DB=hirelens-e2e-db
API=hirelens-e2e-rest
REST_PORT="${E2E_REST_PORT:-54330}"
GATEWAY_PORT="${E2E_GATEWAY_PORT:-54321}"
JWT_SECRET="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(40))')"

GATEWAY_PID=""
cleanup() {
  [ -n "$GATEWAY_PID" ] && kill "$GATEWAY_PID" 2>/dev/null || true
  docker rm -f "$API" "$DB" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

docker network create "$NET" >/dev/null
docker run -d --name "$DB" --network "$NET" -e POSTGRES_HOST_AUTH_METHOD=trust "$PG_IMAGE" >/dev/null
until docker exec "$DB" pg_isready -U postgres -q; do sleep 1; done
# pg_isready answers during the init restart; wait for the final server.
until docker exec "$DB" psql -U postgres -Atqc 'select 1' >/dev/null 2>&1; do sleep 1; done
sleep 2
until docker exec "$DB" psql -U postgres -Atqc 'select 1' >/dev/null 2>&1; do sleep 1; done

psql_db() { docker exec -i "$DB" psql -U postgres -v ON_ERROR_STOP=1 -q "$@"; }

# What Supabase provides before any migration: its roles, their default
# grants, and an auth schema with the users table and helper functions the
# migrations reference.
psql_db <<'SQL'
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
create role authenticator login noinherit;
grant anon, authenticated, service_role to authenticator;
create extension if not exists pgcrypto;
create schema auth;
create table auth.users (
  id uuid primary key default gen_random_uuid(),
  email text unique,
  raw_user_meta_data jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create function auth.uid() returns uuid language sql stable as $f$
  select nullif(coalesce(current_setting('request.jwt.claim.sub', true),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')), '')::uuid $f$;
create function auth.jwt() returns jsonb language sql stable as $f$
  select coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb $f$;
grant usage on schema auth to anon, authenticated, service_role;
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
alter default privileges in schema public grant all on functions to anon, authenticated, service_role;
grant usage on schema public to anon, authenticated, service_role;
SQL

for f in "$ROOT"/backend/sql/*.sql; do
  echo "migrate: $(basename "$f")"
  psql_db < "$f"
done
# Every migration is meant to be re-runnable; prove it.
for f in "$ROOT"/backend/sql/*.sql; do psql_db < "$f" >/dev/null 2>&1 || { echo "not idempotent: $f"; exit 1; }; done

psql_db <<'SQL'
insert into auth.users (id, email, raw_user_meta_data) values
  ('11111111-1111-1111-1111-111111111111', 'owner@e2e-example.com',    '{"full_name": "Olivia Owner"}'),
  ('22222222-2222-2222-2222-222222222222', 'mate@e2e-example.com',     '{"full_name": "Tariq Mate"}'),
  ('33333333-3333-3333-3333-333333333333', 'stranger@e2e-example.com', '{"full_name": "Sam Stranger"}'),
  ('44444444-4444-4444-4444-444444444444', 'leaver@e2e-example.com',   '{"full_name": "Lee Leaver"}');
SQL

docker run -d --name "$API" --network "$NET" -p "127.0.0.1:$REST_PORT:3000" \
  -e PGRST_DB_URI="postgres://authenticator@$DB:5432/postgres" \
  -e PGRST_DB_SCHEMAS=public -e PGRST_DB_ANON_ROLE=anon \
  -e PGRST_JWT_SECRET="$JWT_SECRET" -e PGRST_DB_MAX_ROWS=1000 \
  "$PGRST_IMAGE" >/dev/null

# Supabase serves PostgREST under /rest/v1; a small gateway does the same.
(cd "$ROOT/backend" && E2E_UPSTREAM="http://127.0.0.1:$REST_PORT" "$PY" -m uvicorn \
  tests.postgrest.rest_proxy:app --port "$GATEWAY_PORT" --log-level warning) &
GATEWAY_PID=$!

SERVICE_KEY="$("$PY" -c "import jwt,sys; print(jwt.encode({'role':'service_role','iss':'supabase','exp':4102444800}, sys.argv[1], algorithm='HS256'))" "$JWT_SECRET")"
for _ in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $SERVICE_KEY" \
    "http://127.0.0.1:$GATEWAY_PORT/rest/v1/reports?select=id&limit=1" || true)
  [ "$code" = "200" ] && break
  sleep 1
done
[ "$code" = "200" ] || { echo "PostgREST did not come up (last status $code)"; docker logs "$API" | tail -20; exit 1; }

cd "$ROOT/backend"
HIRELENS_E2E_SUPABASE_URL="http://127.0.0.1:$GATEWAY_PORT" \
HIRELENS_E2E_SERVICE_KEY="$SERVICE_KEY" \
HIRELENS_E2E_USERS="11111111-1111-1111-1111-111111111111:owner@e2e-example.com,22222222-2222-2222-2222-222222222222:mate@e2e-example.com,33333333-3333-3333-3333-333333333333:stranger@e2e-example.com,44444444-4444-4444-4444-444444444444:leaver@e2e-example.com" \
HIRELENS_E2E_DB_CONTAINER="$DB" \
APP_ENV=development SECRET_KEY=test-secret-key-for-ci-only-do-not-use-in-prod \
  "$PY" -m pytest tests/postgrest -q -p no:cacheprovider
