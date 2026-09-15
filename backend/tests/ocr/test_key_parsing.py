"""RED -> GREEN, design D126, tasks.md Unit 5 (tasks 5.1/5.2):

`app.storage.parse_receipt_object_key` is the exact inverse of
`receipt_object_key` and the OCR worker's sole trust boundary on
attacker-influenceable S3 event data (design's threat matrix: "Untrusted
event input -> key injection/traversal"). A non-matching key must return
`None`, never raise, and never be guessed at."""

from __future__ import annotations

import uuid

import pytest

from app import storage


def test_round_trip_inverts_receipt_object_key_for_random_uuids() -> None:
    for _ in range(25):
        workspace_id = uuid.uuid4()
        transaction_id = uuid.uuid4()
        key = storage.receipt_object_key(workspace_id, transaction_id)
        assert storage.parse_receipt_object_key(key) == (workspace_id, transaction_id)


@pytest.mark.parametrize(
    "key",
    [
        "",
        "workspaces/../transactions/../receipt",
        "workspaces/not-a-uuid/transactions/not-a-uuid/receipt",
        f"workspaces/{uuid.uuid4()}/transactions/{uuid.uuid4()}/receipt/extra",
        f"workspaces/{uuid.uuid4()}/transactions/{uuid.uuid4()}",
        f"workspaces/{uuid.uuid4()}/transactions/{uuid.uuid4()}/receipt/",
        f"/workspaces/{uuid.uuid4()}/transactions/{uuid.uuid4()}/receipt",
        f"WORKSPACES/{uuid.uuid4()}/transactions/{uuid.uuid4()}/receipt",
        f"workspaces/{str(uuid.uuid4()).upper()}/transactions/{uuid.uuid4()}/receipt",
        f"workspaces/{uuid.uuid4()}/receipt",
        "../../etc/passwd",
        f"workspaces/{uuid.uuid4()}/transactions/{uuid.uuid4()}extra/receipt",
    ],
)
def test_adversarial_keys_all_return_none(key: str) -> None:
    assert storage.parse_receipt_object_key(key) is None
