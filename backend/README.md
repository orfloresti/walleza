# Backend

FastAPI backend, managed with [uv](https://docs.astral.sh/uv/). Deployed to
AWS Lambda through Mangum (see `../infra/`).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) `0.10+`
- Python `3.13` — uv provisions this automatically via `.python-version`;
  no separate manual install is required.

## Scripts

| Command | Purpose |
|---|---|
| `uv sync` | Install dependencies into `.venv` |
| `uv run ruff check .` | Lint |
| `uv run pytest -q` | Tests |

There is no separate "build" step for this workspace: Python has no
compile/bundle stage, and packaging for deployment is handled by the Lambda
build step introduced in PR5 (`infra/`), not by this workspace directly.

## Configuration

Settings are read from `WALLEZA_*` environment variables (see
`app/config.py`), optionally via a local `.env` file (git-ignored). In
deployed environments the same variable names are expected to be populated
from AWS SSM Parameter Store (SecureString) per design D10 — this workspace
never calls AWS directly; deployment tooling (`infra/`, added in PR5) is
responsible for resolving SSM parameters into the Lambda function's
environment.

## Testing migrations

`tests/migrations/test_baseline.py` runs `alembic upgrade head` /
`alembic downgrade base` against a **real, ephemeral PostgreSQL server** —
not a mock, not SQLite. A migration that only "looks right" but was never
executed is not verified.

It normally uses [testcontainers](https://testcontainers.com/)-style Docker
Postgres, but this sandbox has no usable Docker socket (present, but this
user has no `docker` group membership and there is no passwordless sudo).
Instead, the test starts a throwaway PostgreSQL cluster directly from
server binaries (`initdb`/`pg_ctl`), resolved in this order:

1. `WALLEZA_TEST_PG_BIN_DIR` environment variable, if set.
2. `initdb` already on `PATH`.
3. A dedicated conda environment at `~/apps/miniconda/envs/pgtest/bin`.

If none of those resolve, the test **skips** with an explicit message
rather than silently passing. To provision a real server locally (no
Docker, no root required):

```bash
conda create -y -n pgtest -c conda-forge postgresql
```

## Authentication (PR3)

`app/auth/` wires Google OAuth Authorization Code + PKCE into the
endpoints listed in the design's Interfaces/Contracts section:

```
GET  /api/auth/login     302 -> Google        (sets pkce_state cookie)
GET  /api/auth/callback  302 -> /             (sets access + refresh cookies)
POST /api/auth/refresh   204                  (rotates both cookies)
POST /api/auth/logout    204                  (revokes family, clears cookies)
GET  /api/me             200 {id,email} | 401
```

- `app/auth/google.py` — PKCE pair + signed `state`/`nonce` cookie
  (10-minute TTL, design D7), the Google authorization URL, a one-time
  code-exchange guard against authorization-code replay (in-memory,
  process-global — defense in depth only: it is empty on every Lambda
  cold start, so Google's own `invalid_grant` rejection of a reused
  code remains the real backstop), code exchange via `httpx`, and
  wiring into `app/security.py`'s Google ID-token JWKS verification
  (`iss`/`aud`/`exp`/`nonce`). The `nonce` is generated alongside
  `state`, round-tripped through the same signed cookie, and must match
  the ID token's own `nonce` claim or the callback is rejected.
- `app/auth/session.py` — access-JWT issuance (`app/security.py`) plus
  opaque, rotating refresh tokens hashed (SHA-256) in `app.auth_session`
  (design D8). Reuse of an already-rotated refresh token revokes the
  entire session family, not just the replayed token.
- `app/auth/router.py` — wires the two modules above into the actual
  FastAPI endpoints, including httpOnly/Secure/`SameSite=Lax` cookies.
- `app/main.py` `OriginTokenMiddleware` — verifies the `X-Origin-Token`
  header the Cloudflare Worker injects on every proxied request (design
  D9), locking the Lambda Function URL (`AuthType: NONE`, publicly
  reachable) down to Worker-proxied traffic only. Enforcement is skipped
  while `WALLEZA_WORKER_ORIGIN_TOKEN` is unset (the local-dev default),
  matching every other real secret's local-dev default in this project.

### Local manual testing over HTTP will silently fail to persist cookies

All three auth cookies (`pkce_state`, `walleza_access`, `walleza_refresh`)
are set with `Secure` unconditionally — there is no environment-conditional
toggle, because this app is only ever served same-origin over HTTPS through
the Cloudflare Worker in every real deployment (design D9). Browsers
silently drop a `Secure` cookie set over a plain `http://` origin, so
running `uv run uvicorn app.main:app` and hitting it directly at
`http://localhost:8000` in a real browser will complete the OAuth redirect
but the login will appear to silently fail to "stick" — no cookie is ever
actually stored, so every subsequent request looks unauthenticated again.
This is not a bug; it is the same behavior production requires.

The automated test suite (`tests/auth/test_login_flow.py`) sidesteps this
entirely by driving the app through httpx's `ASGITransport` with an
`https://` `base_url`, which round-trips `Secure` cookies through httpx's
cookie jar without any real network layer or real TLS involved. That is
sufficient for everything this project currently automates, but it is not
a real browser, so it cannot substitute for manual end-to-end testing
before a deploy.

To manually exercise the login flow against a real browser locally,
terminate TLS in front of the backend — for example, a locally-trusted
certificate (`mkcert`) passed to `uvicorn --ssl-keyfile ... --ssl-certfile
...`, or any local HTTPS-terminating reverse proxy — and browse to the
`https://` URL instead of `http://`. There is no Cloudflare Worker local
dev server wired up yet in this repository (the Worker itself is
provisioned in PR5/PR7); until it exists, a local TLS terminator in front
of the FastAPI process directly is the only way to reproduce the
Secure-cookie behavior outside of the automated test suite.

### Required environment before this works against real Google

No real Google Cloud OAuth client, Lambda Function URL, or Worker exists
in this sandbox. Before any of this can complete a real login, supply
real values for (via env vars locally, AWS SSM SecureString in deployed
environments per design D10):

| Variable | Purpose |
|---|---|
| `WALLEZA_GOOGLE_CLIENT_ID` | Google OAuth client ID (also a public Cloudflare Worker var per D10) |
| `WALLEZA_GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `WALLEZA_GOOGLE_REDIRECT_URI` | Must exactly match a redirect URI registered on that Google OAuth client |
| `WALLEZA_JWT_SECRET` | Real, sufficiently long HS256 signing secret for access JWTs |
| `WALLEZA_WORKER_ORIGIN_TOKEN` | Shared secret the Cloudflare Worker injects as `X-Origin-Token` (see `frontend/wrangler.toml`) |

All tests in `tests/auth/` mock the Google JWKS endpoint and the OAuth
token exchange (via `httpx.MockTransport`/monkeypatching, the same
pattern `tests/test_security.py` already established) — no test in this
project ever calls real Google endpoints.

## Status

PR2 scaffold: core application modules exist —

- `app/config.py` — SSM-backed settings loader (env-var based locally)
- `app/db.py` — SQLAlchemy engine at module scope, Supavisor transaction
  pooler (`:6543`) + `NullPool`
- `app/security.py` — access-JWT issue/verify (with `kid` header) and
  Google ID-token JWKS verification primitives
- `app/main.py` — FastAPI app factory + `GET /api/health`
- `app/handler.py` — `Mangum(app, lifespan="off")` Lambda entrypoint

PR2b: migrations framework —

- `alembic.ini` / `migrations/env.py` — Alembic wired to a direct/session-mode
  `:5432` connection for DDL (`app.config.Settings.resolved_migrations_database_url`),
  never through the `:6543` transaction pooler used by `app/db.py` at
  runtime (design D2/D3). Alembic's own `alembic_version` table also lives
  in schema `app`, not `public`.
- `migrations/versions/0001_baseline.py` — baseline revision creating
  schema `app` and exactly `app.app_user` + `app.auth_session` (no other
  product/domain table), per spec's "Migration Framework with Auth-Only
  Baseline" requirement.

PR3: auth RED+GREEN — see "Authentication" above. Reuse-detection tests
in `tests/auth/test_refresh_reuse.py` and the end-to-end happy-path test
in `tests/auth/test_login_flow.py` run against the same real, ephemeral
Postgres pattern as `tests/migrations/test_baseline.py` (see "Testing
migrations" above) — refresh-token rotation and reuse detection are
security-critical and are proven against real FK constraints and real
transactions, not a mock.

PR3b: closed a design-vs-implementation gap found during `sdd-verify` of
PR3 — design D7 calls for verifying the ID token's `iss`/`aud`/`exp`/
**`nonce`**, but PR3 only implemented the first three. `nonce` generation,
storage in the signed state cookie, inclusion in the Google authorization
URL, and required verification against the ID token's `nonce` claim are
now implemented and covered by RED→GREEN tests in `tests/auth/test_id_token.py`
and `tests/auth/test_login_flow.py`. Also documented the `Secure`-cookie
local-testing caveat above (the verify report's other WARNING).

The frontend shell landed in PR4.

PR5: CI/CD + infra provisioning — `.github/workflows/ci-cd.yml` runs
`uv run ruff check .` + `uv run pytest -q` on every PR/push to `main`
(task 7.1), then a `deploy` job gated on `main` merges (or a manual
`workflow_dispatch` for staging) that: reads `WALLEZA_MIGRATIONS_DATABASE_URL`
from SSM and runs `uv run alembic upgrade head` before touching any code,
cross-compiles this package (`uv export` + `uv pip install
--python-platform aarch64-manylinux2014`) into a Lambda zip, and updates
the already-provisioned Lambda's code via `aws lambda
update-function-code` (task 7.2). `infra/` (Terraform) provisions the
Lambda function, its Function URL, the execution role, the GitHub OIDC
deploy role, and every SSM SecureString parameter this module's
`Settings` reads at runtime (task 7.3) — see `infra/README.md` for the
full provisioning story, bootstrap order, and this sandbox's Terraform
validation caveat.
