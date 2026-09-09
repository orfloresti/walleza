"""Business logic for the `category-management` capability (design D28,
D29). Every read/write here is built ONLY on top of
`app.categories.queries.visible_categories` — this module never resolves
membership itself and never builds a competing query path (mirrors
`app.accounts.service`'s exact structure).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.categories.models import Category
from app.categories.queries import visible_categories
from app.deps import WorkspaceScope


class CategoryNotFoundError(Exception):
    """Raised whenever a target category id falls outside
    `visible_categories` for the caller's scope — i.e. it belongs to a
    different workspace entirely. Design D18's 404-for-invisible-rows
    rule, reused exactly: a 403 would confirm the row exists at all."""


class CategoryValidationError(Exception):
    """Raised for design D29's depth-rule violations: a `parent_id` that
    does not resolve inside the caller's workspace, a self-reference, or
    a parent that is not itself top-level. Mapped to 422 by the router —
    never 404, because `parent_id` is a request BODY field, not a
    resource being fetched by id."""


class CategoryDeleteBlockedError(Exception):
    """Raised when the DB's `ON DELETE RESTRICT` (design D28) rejects a
    deletion because the category still has children, or is still
    referenced by a `transaction_category_split` row. Mapped to 409 by
    the router: the constraint IS the enforcement mechanism, this class
    only translates the resulting `IntegrityError` into a clean HTTP
    status — it never reimplements the check."""


def _now() -> datetime:
    return datetime.now(UTC)


def list_categories(db: Session, *, scope: WorkspaceScope) -> list[Category]:
    query = visible_categories(scope).order_by(Category.created_at)
    return list(db.execute(query).scalars())


def get_category(db: Session, *, scope: WorkspaceScope, category_id: uuid.UUID) -> Category:
    category = db.execute(
        visible_categories(scope).where(Category.id == category_id)
    ).scalar_one_or_none()
    if category is None:
        raise CategoryNotFoundError("category not found")
    return category


def _validate_parent_reference(
    db: Session,
    *,
    scope: WorkspaceScope,
    parent_id: uuid.UUID,
    self_id: uuid.UUID | None,
) -> None:
    """Design D29: exactly two hierarchy levels. `self_id` is `None` on
    create (the new id does not exist yet, so self-reference cannot
    literally happen there) and the category's own id on update."""
    if self_id is not None and parent_id == self_id:
        raise CategoryValidationError("a category cannot be its own parent")

    parent = db.execute(
        visible_categories(scope).where(Category.id == parent_id)
    ).scalar_one_or_none()
    if parent is None:
        # Reject as if the reference did not exist — mirrors the
        # cross-workspace account-id rejection pattern used elsewhere in
        # Phase 2's design (never silently accept a foreign-workspace id).
        raise CategoryValidationError("parent category not found")
    if parent.parent_id is not None:
        raise CategoryValidationError(
            "parent category must itself be top-level (design D29: exactly two levels)"
        )


def create_category(
    db: Session,
    *,
    scope: WorkspaceScope,
    name: str,
    icon: str | None,
    type: str,
    parent_id: uuid.UUID | None,
) -> Category:
    if parent_id is not None:
        _validate_parent_reference(db, scope=scope, parent_id=parent_id, self_id=None)

    now = _now()
    category = Category(
        id=uuid.uuid4(),
        workspace_id=scope.workspace_id,
        parent_id=parent_id,
        name=name,
        icon=icon,
        type=type,
        created_at=now,
        updated_at=now,
    )
    db.add(category)
    db.flush()
    return category


def update_category(
    db: Session,
    *,
    scope: WorkspaceScope,
    category_id: uuid.UUID,
    changes: dict[str, object],
) -> Category:
    """`changes` is the caller's already-`exclude_unset=True`-filtered
    patch body. Fetching through `get_category` (i.e. through
    `visible_categories`) means a PATCH aimed at a foreign workspace's
    category 404s before any write is attempted."""
    category = get_category(db, scope=scope, category_id=category_id)

    if "parent_id" in changes:
        new_parent_id = changes["parent_id"]
        if new_parent_id is not None:
            _validate_parent_reference(
                db, scope=scope, parent_id=new_parent_id, self_id=category.id
            )
            # A category that currently has children cannot itself become
            # a child — that would create a third hierarchy level from
            # underneath, which D29 forbids exactly as much as building
            # one from above.
            has_children = db.execute(
                visible_categories(scope).where(Category.parent_id == category.id)
            ).first()
            if has_children is not None:
                raise CategoryValidationError(
                    "a category with children cannot become a child itself (design D29)"
                )

    for field, value in changes.items():
        setattr(category, field, value)
    category.updated_at = _now()
    db.flush()
    return category


def delete_category(db: Session, *, scope: WorkspaceScope, category_id: uuid.UUID) -> None:
    """Design D28: the DB's `ON DELETE RESTRICT` on both `category.parent_id`
    and `transaction_category_split.category_id` IS the enforcement
    mechanism. This function only catches the resulting `IntegrityError`
    and translates it into a clean 409 for the router — it never
    reimplements a "has children" or "has splits" check itself."""
    category = get_category(db, scope=scope, category_id=category_id)
    try:
        db.delete(category)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise CategoryDeleteBlockedError(
            "category has children or is referenced by transaction splits"
        ) from exc
