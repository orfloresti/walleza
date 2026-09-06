"""JWT issuance + refresh-token rotation and reuse detection (design D8).

Refresh tokens are opaque, rotating, and stored HASHED in
`app.auth_session` (SHA-256 of the raw token) — the raw token only ever
exists in the httpOnly response cookie and in memory for the duration of
one request. Every successful `rotate_refresh_token` call retires
(`revoked_at`) the presented row and inserts a brand-new row in the same
`family_id`. If a refresh token is ever presented AFTER it has already
been rotated away (`revoked_at IS NOT NULL`), that is treated as proof of
token theft/replay: the ENTIRE family is revoked so both the thief and
the legitimate holder are logged out (design D8 "reuse detection revokes
the family").

No SQLAlchemy declarative model layer exists yet (Phase 2 built no ORM
models — see `migrations/env.py`), so this module talks to
`app.app_user` / `app.auth_session` through hand-written SQLAlchemy Core
`Table` objects matching the baseline migration's column shapes exactly,
rather than autoloading against a live database (which would make
importing this module unsafe with no DB reachable, breaking the same
import-safety guarantee `app/db.py` documents).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy import Column, ForeignKey, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Session

from app.config import get_settings
from app.security import issue_access_token

metadata = MetaData(schema="app")

app_user_table = Table(
    "app_user",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("google_sub", Text, nullable=False, unique=True),
    Column("email", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True)),
    Column("updated_at", TIMESTAMP(timezone=True)),
)

auth_session_table = Table(
    "auth_session",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("app.app_user.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("refresh_hash", Text, nullable=False),
    Column("family_id", UUID(as_uuid=True), nullable=False),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("revoked_at", TIMESTAMP(timezone=True), nullable=True),
)


class RefreshTokenError(Exception):
    """Raised when a presented refresh token is missing, unknown, or expired."""


class RefreshTokenReuseError(RefreshTokenError):
    """Raised when a refresh token is replayed after having already been
    rotated away. By the time this is raised, the entire session family
    has already been revoked."""


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    refresh_token: str
    family_id: str


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def upsert_user_by_google_sub(db: Session, *, google_sub: str, email: str) -> uuid.UUID:
    """Persist the minimal identity record, reusing the existing row by
    `google_sub` on repeat logins (spec: "Minimal User Identity
    Persistence" — first login creates a record, repeat login reuses it).
    """
    existing = db.execute(
        sa.select(app_user_table.c.id).where(app_user_table.c.google_sub == google_sub)
    ).first()
    if existing is not None:
        db.execute(
            sa.update(app_user_table)
            .where(app_user_table.c.google_sub == google_sub)
            .values(email=email, updated_at=_now())
        )
        return existing.id

    user_id = uuid.uuid4()
    db.execute(
        sa.insert(app_user_table).values(
            id=user_id,
            google_sub=google_sub,
            email=email,
            created_at=_now(),
            updated_at=_now(),
        )
    )
    return user_id


def get_user_by_id(db: Session, *, user_id: str) -> dict[str, str] | None:
    row = db.execute(
        sa.select(app_user_table.c.id, app_user_table.c.email).where(
            app_user_table.c.id == uuid.UUID(str(user_id))
        )
    ).first()
    if row is None:
        return None
    return {"id": str(row.id), "email": row.email}


def create_session(db: Session, *, user_id: uuid.UUID) -> IssuedSession:
    """Start a brand-new session family (first login, or after a full
    logout)."""
    settings = get_settings()
    family_id = uuid.uuid4()
    return _issue_new_refresh_row(
        db, user_id=user_id, family_id=family_id, ttl_days=settings.refresh_ttl_days
    )


def _issue_new_refresh_row(
    db: Session, *, user_id: uuid.UUID, family_id: uuid.UUID, ttl_days: int
) -> IssuedSession:
    refresh_token = _generate_refresh_token()
    row_id = uuid.uuid4()
    db.execute(
        sa.insert(auth_session_table).values(
            id=row_id,
            user_id=user_id,
            refresh_hash=_hash_refresh_token(refresh_token),
            family_id=family_id,
            expires_at=_now() + timedelta(days=ttl_days),
            revoked_at=None,
        )
    )
    access_token = issue_access_token(user_id=str(user_id), session_id=str(family_id))
    return IssuedSession(access_token=access_token, refresh_token=refresh_token, family_id=str(family_id))


def rotate_refresh_token(db: Session, *, presented_refresh_token: str) -> IssuedSession:
    """Rotate a valid refresh token into a fresh pair. Raises
    `RefreshTokenReuseError` (and revokes the whole family) if the
    presented token was already rotated away, or plain
    `RefreshTokenError` if it is unknown or expired.
    """
    settings = get_settings()
    presented_hash = _hash_refresh_token(presented_refresh_token)

    row = db.execute(
        sa.select(auth_session_table).where(auth_session_table.c.refresh_hash == presented_hash)
    ).first()

    if row is None:
        raise RefreshTokenError("unknown refresh token")

    if row.revoked_at is not None:
        _revoke_family(db, family_id=row.family_id)
        raise RefreshTokenReuseError("refresh token reuse detected; session family revoked")

    if row.expires_at is not None and row.expires_at < _now():
        raise RefreshTokenError("refresh token expired")

    db.execute(
        sa.update(auth_session_table)
        .where(auth_session_table.c.id == row.id)
        .values(revoked_at=_now())
    )

    return _issue_new_refresh_row(
        db, user_id=row.user_id, family_id=row.family_id, ttl_days=settings.refresh_ttl_days
    )


def _revoke_family(db: Session, *, family_id: uuid.UUID) -> None:
    db.execute(
        sa.update(auth_session_table)
        .where(auth_session_table.c.family_id == family_id)
        .where(auth_session_table.c.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def logout(db: Session, *, presented_refresh_token: str) -> None:
    """Revoke the whole family for the presented token. Idempotent: an
    unknown or already-revoked token is a silent no-op — a logout call
    must never itself fail or leak whether the presented token was
    valid."""
    presented_hash = _hash_refresh_token(presented_refresh_token)
    row = db.execute(
        sa.select(auth_session_table.c.family_id).where(
            auth_session_table.c.refresh_hash == presented_hash
        )
    ).first()
    if row is not None:
        _revoke_family(db, family_id=row.family_id)
