"""RED -> GREEN, spec "Recurrence Never Produces a Transfer" (R2) and the
R7-mirrored no-`checked` requirement (tasks.md 1.14): the create/update
schemas have no `to_account_id`/second-amount/`checked` field available
to set at all."""

from __future__ import annotations

from app.recurring import schemas


def test_recurring_create_and_update_schemas_have_no_transfer_or_checked_field() -> None:
    create_fields = set(schemas.RecurringCreateIn.model_fields)
    update_fields = set(schemas.RecurringUpdateIn.model_fields)
    for fields in (create_fields, update_fields):
        assert "to_account_id" not in fields
        assert "to_amount" not in fields
        assert "checked" not in fields


def test_recurring_update_schema_has_no_server_managed_cursor_fields() -> None:
    """Spec: "next_date Is Server-Managed" — a client update cannot even
    NAME `next_date`, `occurrence_index`, or `last_reminded_for_date`;
    there is no field to set them through, structurally, not merely by
    convention."""
    update_fields = set(schemas.RecurringUpdateIn.model_fields)
    assert "next_date" not in update_fields
    assert "occurrence_index" not in update_fields
    assert "last_reminded_for_date" not in update_fields
    assert "starts_on" not in update_fields


def test_recurring_create_schema_has_no_next_date_field() -> None:
    create_fields = set(schemas.RecurringCreateIn.model_fields)
    assert "next_date" not in create_fields
    assert "occurrence_index" not in create_fields
