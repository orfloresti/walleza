"""Application settings.

Locally, every value below is read from environment variables (optionally
via a local `.env` file, ignored by git) using `pydantic-settings`. In a
deployed environment (AWS Lambda) the same field names are populated from
AWS SSM Parameter Store (SecureString) per design D10, so `pydantic-settings`
never talks to AWS directly here — deployment tooling is expected to resolve
SSM parameters into the Lambda function's environment variables at deploy
time (e.g. `infra/` reading `/walleza/<env>/<name>` and wiring it into the
Lambda resource), or a thin bootstrap could populate `os.environ` from SSM
before this module is imported.

This indirection is intentional: `Settings` only ever reads `os.environ`,
so swapping "where the environment variables come from" later (SSM at
deploy time today, a `boto3 ssm.get_parameters_by_path()` cold-start call
tomorrow if that's ever needed) requires no changes to this file or to any
of its callers.

Design ref: D10 (SSM SecureString-backed runtime secrets).
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, sourced from `WALLEZA_*` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="WALLEZA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "local"
    app_version: str = "0.0.0-dev"
    commit_sha: str = "unknown"

    # Supavisor transaction-pooler URL, port 6543 (design D2). The local
    # default points nowhere real — it exists so importing app.db never
    # crashes when no environment is configured (e.g. during `uv run ruff`
    # or a plain module import), not as a usable connection.
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:6543/postgres",
        description="Supavisor transaction-pooler connection string (see app/db.py, design D2).",
    )

    # Access-JWT signing (design D8). `jwt_kid` is present from day one so a
    # future multi-key rotation only needs to add lookup-by-kid, not a schema
    # change to already-issued tokens.
    jwt_secret: str = Field(
        default="local-dev-only-secret-change-me-before-any-real-use",
    )
    jwt_kid: str = Field(default="local-dev-key-1")
    jwt_issuer: str = "walleza"
    jwt_audience: str = "walleza-web"
    jwt_access_ttl_seconds: int = 15 * 60

    # Google OAuth / ID-token verification (design D7).
    google_client_id: str = Field(default="")
    google_client_secret: str = Field(default="")
    google_jwks_url: str = "https://www.googleapis.com/oauth2/v3/certs"
    google_issuer: str = "https://accounts.google.com"
    google_authorization_endpoint: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_token_endpoint: str = "https://oauth2.googleapis.com/token"
    # Must exactly match a redirect URI registered on the Google OAuth
    # client. Local default only; a real value is required before any
    # real Google login can succeed.
    google_redirect_uri: str = Field(
        default="http://localhost:4200/api/auth/callback",
    )

    # PKCE `state` cookie lifetime (design D7 — "10-min signed httpOnly
    # cookie") and refresh-token sliding lifetime (design D8 — "30-day
    # sliding").
    oauth_state_ttl_seconds: int = 10 * 60
    refresh_ttl_days: int = 30

    # Shared secret the Cloudflare Worker injects as `X-Origin-Token` on
    # every proxied `/api/*` request; FastAPI middleware verifies it
    # (design D9). Empty by default (no real Worker/Function URL exists
    # in this sandbox) — see `app/main.py` for why enforcement is skipped
    # while this is unset.
    worker_origin_token: str = Field(default="")

    # Invite-link lifetime (design D12): a workspace invite is a bearer
    # credential handed to a third party, so — unlike the stateless
    # `pkce_state` cookie — it is server-state-backed, single-use, and
    # time-boxed. 7 days balances "long enough to actually be used" against
    # "short enough that a leaked, unused link stops working on its own".
    invite_ttl_days: int = 7

    # Receipt-photo S3 bucket (design D31, `sdd/phase-2-categories-
    # transactions`). Not a secret — the bucket name is in the host of every
    # presigned URL the browser receives — so it arrives as a plain Lambda
    # environment variable (`infra/lambda.tf`'s `local.non_secret_env`), not
    # an SSM parameter, exactly like `google_client_id` above. Empty/default
    # locally, same as every other field with no usable local default: no
    # real bucket exists in this sandbox. The presign/upload flow itself
    # (`app/storage.py`, `receipt_max_bytes`, `presigned_url_ttl_seconds`) is
    # a later phase's addition; these two fields only give that later code
    # somewhere to read the bucket identity from once the Lambda env vars
    # are set (see `infra/README.md`'s "S3 Receipts Bucket" section for the
    # `ignore_changes=[environment]` gotcha on an already-existing function).
    s3_receipts_bucket: str = Field(default="")
    s3_region: str = Field(default="us-east-1")

    # Receipt-photo upload constraints and presigned-URL lifetime (design
    # D25/D26/D32, PR5's actual consumer of the two fields above).
    # `receipt_max_bytes` is the exact `content-length-range` upper bound
    # `app.storage.presigned_upload` embeds in the presigned POST policy —
    # enforced by S3 itself at upload time, never re-checked here after the
    # fact (design D25's own rationale for choosing POST over PUT).
    # `presigned_url_ttl_seconds` bounds BOTH the presigned POST (upload)
    # and the presigned GET (download), matching design's stated 300s TTL
    # for each.
    receipt_max_bytes: int = 5 * 1024 * 1024
    presigned_url_ttl_seconds: int = 300

    # Direct (non-pooled) Postgres connection, used ONLY by Alembic to run
    # DDL (design D2/D3). Supavisor's transaction pooler (`:6543`, used by
    # `database_url` above for runtime traffic) forbids server-side prepared
    # statements and behaves differently under DDL/locks, so migrations must
    # bypass it entirely. Left unset in normal operation: `env.py` derives
    # it from `database_url` by swapping the pooler's `:6543` port for the
    # direct/session-mode `:5432` port on the same host. Set explicitly
    # (e.g. in CI or in tests, via `WALLEZA_MIGRATIONS_DATABASE_URL`) when
    # the direct connection needs a different host or port than that
    # derivation would produce.
    migrations_database_url: str | None = Field(default=None)

    # Bounded catch-up cap for `app.recurring.generation` (design D48): the
    # maximum number of missed occurrences a single recurrence generates in
    # one scheduled run before PAUSING (leaving the cursor mid-backlog,
    # never fast-forwarding past it — see `generation.py`'s module
    # docstring). 120 is design's own chosen value: a daily job drains a
    # 4-month backlog of a daily recurrence in one run, and a much longer
    # dormancy converges over a few subsequent daily runs instead of one
    # unbounded loop.
    generation_max_catchup_per_run: int = 120

    # SESv2 reminder email sending (design D52-D54, `recurring-reminders`,
    # `app/notifications/ses.py`/`templates.py`). Empty/default locally and
    # in this sandbox — no real SES identity exists here; a real value is
    # required before `app.recurring.generation.run_reminders` can send for
    # real. `ses_from_address` is the exact From address design D53's IAM
    # `ses:FromAddress` condition permits the scheduler role to send as.
    ses_from_address: str = Field(default="")
    ses_region: str = Field(default="us-east-1")

    # Frontend origin surfaced in the reminder email body (design D54's Data
    # Flow) so a recipient can click through to manage the recurrence that
    # generated the reminder. Local default only — no real deployment
    # exists in this sandbox.
    web_app_url: str = Field(default="http://localhost:4200")

    @property
    def resolved_migrations_database_url(self) -> str:
        """The connection string Alembic must use to run DDL.

        Returns the explicit `migrations_database_url` override when set,
        otherwise derives a direct/session-mode URL from `database_url` by
        swapping the transaction-pooler port `:6543` for `:5432`.
        """
        if self.migrations_database_url:
            return self.migrations_database_url
        return self.database_url.replace(":6543/", ":5432/")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached `Settings` instance.

    Cached rather than re-read per call because, in Lambda, this executes
    once at cold start alongside the module-scope engine in `app/db.py`
    (design D1) — both are meant to survive across warm invocations of the
    same execution environment. Tests that mutate environment variables via
    `monkeypatch` must call `get_settings.cache_clear()` before and after.
    """
    return Settings()
