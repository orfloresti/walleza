"""RED -> GREEN, design D22, spec `transaction-splits` (tasks.md 4.1-4.6):

`service.replace_splits` is the ONLY function that ever writes a
`transaction_category_split` row — a single whole-set-replacement
function, never a partial-edit endpoint, never a DB trigger. These tests
prove:

- Split lines not summing EXACTLY to the transaction's amount are
  rejected on both create and update, in both directions (too little,
  too much), and no partial write occurs (design RED #3).
- Decimal-exact comparison: `3.33 + 3.33 + 3.34` sums exactly to `10.00`
  and is accepted; `3.33 * 3` is `9.99`, never `10.00`, and is rejected —
  Decimal arithmetic only, never float tolerance (design RED #4).
- A split naming a category from another workspace is rejected, never
  silently written (design RED #13).
- A split line never leaks across members or across sibling transactions
  (spec's transaction-visibility "a split line does not leak account
  ownership" scenario).
- Updating a transaction's splits REPLACES the whole set — old lines are
  gone, only the new lines are present — never additive.
- Updating `amount` alone, leaving `splits` untouched, is rejected when
  the existing splits no longer sum to the new amount (spec's "Updating
  amount without updating splits is rejected" scenario — reported as a
  judgment call in apply-progress: not literally one of tasks.md's 4.1-4.6
  bullets, but a direct consequence of the "Split Lines Must Sum to the
  Parent Amount" requirement task 4.1 targets).
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


def _token_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


async def _join_same_workspace(client, owner_cookie: str, joiner_cookie: str) -> str:
    owner_ws = await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
    await client.get("/api/workspace", cookies={"walleza_access": joiner_cookie})
    invite = await client.post("/api/workspace/invites", cookies={"walleza_access": owner_cookie})
    assert invite.status_code == 201
    token = _token_from_url(invite.json()["url"])
    accept = await client.post(
        "/api/workspace/invites/accept",
        json={"token": token},
        cookies={"walleza_access": joiner_cookie},
    )
    assert accept.status_code == 204
    return owner_ws.json()["id"]


async def _create_account(client, cookie: str, *, name: str = "Checking") -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": name, "currency": "USD", "is_personal": False},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_category(client, cookie: str, *, name: str, type_: str = "expense") -> str:
    response = await client.post(
        "/api/categories",
        json={"name": name, "type": type_},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_split_lines_summing_to_less_than_amount_rejected_on_create(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="splits-under-create@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)
        category_a = await _create_category(client, cookie, name="Groceries")
        category_b = await _create_category(client, cookie, name="Transport")

        before = await client.get("/api/transactions", cookies={"walleza_access": cookie})

        response = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "100.00",
                "occurred_on": "2026-03-01",
                "splits": [
                    {"category_id": category_a, "amount": "60.00"},
                    {"category_id": category_b, "amount": "30.00"},
                ],
            },
            cookies={"walleza_access": cookie},
        )

        after = await client.get("/api/transactions", cookies={"walleza_access": cookie})

    assert response.status_code == 422
    assert len(after.json()) == len(before.json()), (
        "a rejected create must leave no transaction row behind"
    )


async def test_split_lines_summing_to_more_than_amount_rejected_on_create(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="splits-over-create@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)
        category_a = await _create_category(client, cookie, name="Groceries")
        category_b = await _create_category(client, cookie, name="Transport")

        before = await client.get("/api/transactions", cookies={"walleza_access": cookie})

        response = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "100.00",
                "occurred_on": "2026-03-01",
                "splits": [
                    {"category_id": category_a, "amount": "60.00"},
                    {"category_id": category_b, "amount": "60.00"},
                ],
            },
            cookies={"walleza_access": cookie},
        )

        after = await client.get("/api/transactions", cookies={"walleza_access": cookie})

    assert response.status_code == 422
    assert len(after.json()) == len(before.json()), (
        "a rejected create must leave no transaction row behind"
    )


async def test_split_lines_not_summing_to_amount_rejected_on_update_no_partial_write(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="splits-mismatch-update@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)
        category_a = await _create_category(client, cookie, name="Groceries")
        category_b = await _create_category(client, cookie, name="Transport")

        created = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "100.00",
                "occurred_on": "2026-03-01",
                "splits": [{"category_id": category_a, "amount": "100.00"}],
            },
            cookies={"walleza_access": cookie},
        )
        assert created.status_code == 201
        transaction_id = created.json()["id"]

        update_response = await client.patch(
            f"/api/transactions/{transaction_id}",
            json={
                "splits": [
                    {"category_id": category_a, "amount": "60.00"},
                    {"category_id": category_b, "amount": "30.00"},
                ]
            },
            cookies={"walleza_access": cookie},
        )

        unchanged = await client.get(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie}
        )

    assert update_response.status_code == 422
    assert unchanged.status_code == 200
    assert unchanged.json()["splits"] == [
        {"id": unchanged.json()["splits"][0]["id"], "category_id": category_a, "amount": "100.00"}
    ], "a rejected update must leave the existing split set byte-for-byte untouched"


async def test_decimal_exact_split_sum_accepted_and_float_style_rounding_rejected(
    seed_user, app_factory
) -> None:
    """Design RED #4: `3.33 + 3.33 + 3.34 == 10.00` exactly in Decimal and
    is accepted; `3.33 * 3 == 9.99`, never `10.00`, and is rejected — the
    comparison must be exact Decimal arithmetic, never float-tolerant."""
    owner = seed_user(email="splits-decimal-precision@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)
        category_a = await _create_category(client, cookie, name="A")
        category_b = await _create_category(client, cookie, name="B")
        category_c = await _create_category(client, cookie, name="C")

        accepted = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "10.00",
                "occurred_on": "2026-03-02",
                "splits": [
                    {"category_id": category_a, "amount": "3.33"},
                    {"category_id": category_b, "amount": "3.33"},
                    {"category_id": category_c, "amount": "3.34"},
                ],
            },
            cookies={"walleza_access": cookie},
        )

        rejected = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "10.00",
                "occurred_on": "2026-03-02",
                "splits": [
                    {"category_id": category_a, "amount": "3.33"},
                    {"category_id": category_b, "amount": "3.33"},
                    {"category_id": category_c, "amount": "3.33"},
                ],
            },
            cookies={"walleza_access": cookie},
        )

    assert accepted.status_code == 201
    assert {s["amount"] for s in accepted.json()["splits"]} == {"3.33", "3.34"}
    assert rejected.status_code == 422


async def test_split_referencing_another_workspaces_category_is_rejected(
    seed_user, app_factory
) -> None:
    owner_w1 = seed_user(email="splits-w1@example.com")
    owner_w2 = seed_user(email="splits-w2@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_w1 = _cookie_for(owner_w1)
    cookie_w2 = _cookie_for(owner_w2)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w1})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w2})

        account_id = await _create_account(client, cookie_w1)
        w2_category_id = await _create_category(client, cookie_w2, name="W2 category")

        before = await client.get("/api/transactions", cookies={"walleza_access": cookie_w1})

        response = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "50.00",
                "occurred_on": "2026-03-03",
                "splits": [{"category_id": w2_category_id, "amount": "50.00"}],
            },
            cookies={"walleza_access": cookie_w1},
        )

        after = await client.get("/api/transactions", cookies={"walleza_access": cookie_w1})

    assert response.status_code == 422
    assert "W2 category" not in response.text
    assert len(after.json()) == len(before.json())


async def test_split_line_does_not_leak_across_members_or_transactions(
    seed_user, app_factory
) -> None:
    """Spec transaction-visibility scenario: 'A split line does not leak
    account ownership' — member B must never see member A's split lines
    (via the 404 boundary already proven elsewhere), AND, independently,
    each member's OWN transaction must only ever show ITS OWN splits, not
    a sibling transaction's — a cross-contamination regression guard on
    `service.list_splits`."""
    owner_a = seed_user(email="splits-leak-a@example.com")
    owner_b = seed_user(email="splits-leak-b@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)

        a_personal = await client.post(
            "/api/accounts",
            json={"name": "A Personal", "currency": "USD", "is_personal": True},
            cookies={"walleza_access": cookie_a},
        )
        a_account_id = a_personal.json()["id"]
        a_category_id = await _create_category(client, cookie_a, name="A Category")

        a_txn = await client.post(
            "/api/transactions",
            json={
                "account_id": a_account_id,
                "type": "expense",
                "amount": "20.00",
                "occurred_on": "2026-03-04",
                "notes": "A's secret expense",
                "splits": [{"category_id": a_category_id, "amount": "20.00"}],
            },
            cookies={"walleza_access": cookie_a},
        )
        assert a_txn.status_code == 201
        a_txn_id = a_txn.json()["id"]

        b_personal = await client.post(
            "/api/accounts",
            json={"name": "B Personal", "currency": "USD", "is_personal": True},
            cookies={"walleza_access": cookie_b},
        )
        b_account_id = b_personal.json()["id"]
        b_category_id = await _create_category(client, cookie_b, name="B Category")

        b_txn = await client.post(
            "/api/transactions",
            json={
                "account_id": b_account_id,
                "type": "expense",
                "amount": "15.00",
                "occurred_on": "2026-03-04",
                "notes": "B's own expense",
                "splits": [{"category_id": b_category_id, "amount": "15.00"}],
            },
            cookies={"walleza_access": cookie_b},
        )
        assert b_txn.status_code == 201
        b_txn_id = b_txn.json()["id"]

        b_gets_a = await client.get(
            f"/api/transactions/{a_txn_id}", cookies={"walleza_access": cookie_b}
        )
        a_view = await client.get(
            f"/api/transactions/{a_txn_id}", cookies={"walleza_access": cookie_a}
        )
        b_view = await client.get(
            f"/api/transactions/{b_txn_id}", cookies={"walleza_access": cookie_b}
        )

    assert b_gets_a.status_code == 404
    assert "A Category" not in b_gets_a.text
    assert str(a_category_id) not in b_gets_a.text

    assert a_view.status_code == 200
    assert [s["category_id"] for s in a_view.json()["splits"]] == [a_category_id]

    assert b_view.status_code == 200
    assert [s["category_id"] for s in b_view.json()["splits"]] == [b_category_id]


async def test_updating_transactions_splits_replaces_the_whole_set_not_additive(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="splits-replace-whole-set@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)
        category_old = await _create_category(client, cookie, name="Old")
        category_new = await _create_category(client, cookie, name="New")

        created = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "80.00",
                "occurred_on": "2026-03-05",
                "splits": [{"category_id": category_old, "amount": "80.00"}],
            },
            cookies={"walleza_access": cookie},
        )
        assert created.status_code == 201
        transaction_id = created.json()["id"]
        assert [s["category_id"] for s in created.json()["splits"]] == [category_old]

        updated = await client.patch(
            f"/api/transactions/{transaction_id}",
            json={"splits": [{"category_id": category_new, "amount": "80.00"}]},
            cookies={"walleza_access": cookie},
        )

    assert updated.status_code == 200
    body = updated.json()
    assert [s["category_id"] for s in body["splits"]] == [category_new], (
        "the old split line must be entirely gone, not additive"
    )
    assert category_old not in [s["category_id"] for s in body["splits"]]


async def test_updating_amount_alone_leaving_stale_splits_is_rejected(
    seed_user, app_factory
) -> None:
    """Spec `transaction-splits`: 'Updating amount without updating
    splits is rejected' — the existing splits still sum to the OLD
    amount, so changing `amount` alone (without touching `splits`) must
    be rejected, and neither the amount nor the splits may change."""
    owner = seed_user(email="splits-amount-alone@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)
        category_id = await _create_category(client, cookie, name="Only")

        created = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "50.00",
                "occurred_on": "2026-03-06",
                "splits": [{"category_id": category_id, "amount": "50.00"}],
            },
            cookies={"walleza_access": cookie},
        )
        assert created.status_code == 201
        transaction_id = created.json()["id"]

        update_response = await client.patch(
            f"/api/transactions/{transaction_id}",
            json={"amount": "70.00"},
            cookies={"walleza_access": cookie},
        )

        unchanged = await client.get(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie}
        )

    assert update_response.status_code == 422
    assert unchanged.json()["amount"] == "50.00"
    assert unchanged.json()["splits"] == [
        {"id": unchanged.json()["splits"][0]["id"], "category_id": category_id, "amount": "50.00"}
    ]
