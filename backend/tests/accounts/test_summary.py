"""RED -> GREEN, design D16, spec RED #3 (tasks.md 5.2):

A member's personal account balance contributes to THEIR OWN
`/api/workspace/summary` total and appears in NO OTHER member's total, in
whole or in part — `compute_summary` is a SQL aggregate over the exact
same `visible_accounts(scope, archived=False)` `Select` the account list
uses (design D16), so a total structurally cannot count a row the list
hides.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


def _token_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


async def _join_same_workspace(client, owner_cookie: str, joiner_cookie: str) -> None:
    await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
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


async def test_owners_total_includes_own_personal_others_total_excludes_it(
    seed_user, app_factory
) -> None:
    owner_a = seed_user(email="a-summary@example.com")
    owner_b = seed_user(email="b-summary@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)

        await client.post(
            "/api/accounts",
            json={
                "name": "Shared checking",
                "currency": "USD",
                "initial_funds": "100.00",
                "is_personal": False,
            },
            cookies={"walleza_access": cookie_a},
        )
        await client.post(
            "/api/accounts",
            json={
                "name": "A's secret stash",
                "currency": "USD",
                "initial_funds": "250.00",
                "is_personal": True,
            },
            cookies={"walleza_access": cookie_a},
        )

        summary_a = await client.get("/api/workspace/summary", cookies={"walleza_access": cookie_a})
        summary_b = await client.get("/api/workspace/summary", cookies={"walleza_access": cookie_b})

    assert summary_a.status_code == 200
    assert summary_b.status_code == 200

    usd_a = next(row for row in summary_a.json()["by_currency"] if row["currency"] == "USD")
    usd_b = next(row for row in summary_b.json()["by_currency"] if row["currency"] == "USD")

    # A's total: shared (100.00) + A's own personal (250.00) = 350.00.
    assert Decimal(usd_a["total"]) == Decimal("350.00")
    # B's total: shared (100.00) ONLY — A's personal balance must not
    # appear, in whole or in part.
    assert Decimal(usd_b["total"]) == Decimal("100.00")

    assert Decimal(summary_a.json()["grand_total"]) == Decimal("350.00")
    assert Decimal(summary_b.json()["grand_total"]) == Decimal("100.00")


async def test_summary_with_no_accounts_returns_zero_grand_total_and_empty_currency_list(
    seed_user, app_factory
) -> None:
    user_id = seed_user(email="empty-summary@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(user_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        summary = await client.get("/api/workspace/summary", cookies={"walleza_access": cookie})

    assert summary.status_code == 200
    body = summary.json()
    assert body["by_currency"] == []
    assert Decimal(body["grand_total"]) == Decimal(0)
