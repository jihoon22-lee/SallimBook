"""Shared supply demand is a projection, not a stock movement or financial event."""

import json
from datetime import date
from pathlib import Path

import pytest

from sallimbook.homecare.purchase_calculations import projected_replacements, purchase_quantities


def test_shared_fixture_pools_stock_once_for_two_devices():
    example = json.loads(
        (Path(__file__).resolve().parents[3] / "packages/test-fixtures/catalog.json").read_text()
    )["edge_cases"]["shared_purchase_plan"]
    assert (
        purchase_quantities(
            example["demand_quantities"],
            example["stock_quantity"],
            example["planned_quantity"],
            example["ordered_quantity"],
        )
        == example["expected"]
    )


def test_due_and_overdue_are_one_initial_check_not_all_missed_cycles():
    today = date(2025, 3, 1)
    assert projected_replacements(date(2020, 1, 1), today, today, "days", 1) == 1
    assert projected_replacements(date(2020, 1, 1), today, date(2025, 3, 3), "days", 1) == 3
    assert projected_replacements(date(2025, 3, 2), today, today, "days", 1) == 0
    assert projected_replacements(None, today, today, "months", 1) is None


def test_manual_dates_month_end_and_maximum_date_are_bounded():
    assert (
        projected_replacements(date(2024, 1, 31), date(2024, 1, 31), date(2024, 3, 29), "months", 1)
        == 3
    )
    assert (
        projected_replacements(date(2025, 1, 31), date(2025, 1, 31), date(2025, 3, 27), "months", 1)
        == 2
    )
    assert (
        projected_replacements(
            date(2025, 1, 1), date(2025, 1, 1), date(2025, 12, 31), "manual", None
        )
        == 1
    )
    assert (
        projected_replacements(
            date(9999, 12, 31), date(9999, 12, 31), date(9999, 12, 31), "days", 1
        )
        == 1
    )
    assert (
        projected_replacements(date(2025, 1, 1), date(2025, 1, 1), date(2026, 1, 1), "days", 1)
        == 366
    )


@pytest.mark.parametrize("through", [date(2024, 12, 31), date(2026, 1, 2)])
def test_invalid_planning_range_fails(through):
    with pytest.raises(ValueError):
        projected_replacements(None, date(2025, 1, 1), through, "days", 1)


def test_outstanding_orders_are_separate_from_physical_shortage():
    assert purchase_quantities([1, 1], 1, 1, 1) == {
        "demand_quantity": 2,
        "shortage_quantity": 1,
        "additional_quantity": 0,
    }
    assert purchase_quantities([1], 3, 0, 0)["shortage_quantity"] == 0
