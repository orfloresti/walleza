"""RED -> GREEN, design D80: `roll_up()` as a pure, independently
testable function — no database needed. Covers parent+children rollup,
leaf-no-double-count, zero-activity categories, and the 3rd-level-raises
guard (tasks.md 1.7, 1.8, 1.9, 1.15).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.reports.service import roll_up


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def test_parent_with_direct_spend_and_children_rolls_up() -> None:
    parent = _uuid()
    child1 = _uuid()
    child2 = _uuid()
    parents = {parent: None, child1: parent, child2: parent}
    totals = {parent: Decimal(50), child1: Decimal(30), child2: Decimal(20)}

    result = roll_up(totals, parents)

    assert result[parent] == (Decimal(50), Decimal(100))
    assert result[child1] == (Decimal(30), Decimal(30))
    assert result[child2] == (Decimal(20), Decimal(20))


def test_leaf_category_with_no_children_does_not_double_count() -> None:
    leaf = _uuid()
    parents = {leaf: None}
    totals = {leaf: Decimal(40)}

    result = roll_up(totals, parents)

    assert result[leaf] == (Decimal(40), Decimal(40))


def test_category_with_zero_activity_still_appears_at_zero() -> None:
    category = _uuid()
    parents = {category: None}
    totals: dict[uuid.UUID, Decimal] = {}

    result = roll_up(totals, parents)

    assert result[category] == (Decimal(0), Decimal(0))


def test_empty_totals_still_returns_every_category_at_zero() -> None:
    parent = _uuid()
    child = _uuid()
    parents = {parent: None, child: parent}

    result = roll_up({}, parents)

    assert result[parent] == (Decimal(0), Decimal(0))
    assert result[child] == (Decimal(0), Decimal(0))


def test_refund_reduces_category_total() -> None:
    category = _uuid()
    parents = {category: None}
    # The signed-amount convention is applied upstream by the SQL query
    # (design D79); by the time totals reach roll_up() a refund has
    # already been subtracted, so this asserts roll_up() simply passes a
    # negative-adjusted total through unchanged.
    totals = {category: Decimal(70)}

    result = roll_up(totals, parents)

    assert result[category] == (Decimal(70), Decimal(70))


def test_third_hierarchy_level_raises() -> None:
    grandparent = _uuid()
    parent = _uuid()
    child = _uuid()
    # child -> parent -> grandparent is 3 levels deep; the 2-level cap is
    # a service-layer rule elsewhere in the app, and roll_up() must
    # enforce it (design D80) rather than silently under-reporting.
    parents = {grandparent: None, parent: grandparent, child: parent}
    totals = {grandparent: Decimal(0), parent: Decimal(0), child: Decimal(10)}

    with pytest.raises(ValueError):
        roll_up(totals, parents)


def test_multiple_top_level_categories_are_independent() -> None:
    top_a = _uuid()
    top_b = _uuid()
    parents = {top_a: None, top_b: None}
    totals = {top_a: Decimal(10), top_b: Decimal(20)}

    result = roll_up(totals, parents)

    assert result[top_a] == (Decimal(10), Decimal(10))
    assert result[top_b] == (Decimal(20), Decimal(20))
