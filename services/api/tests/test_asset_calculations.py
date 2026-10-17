"""Shared asset vectors; API, concurrency and platform acceptance remain separate checks."""

import json
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from sallimbook.assets.calculations import (
    AssetMonth,
    AssetValue,
    asset_totals,
    compare_months,
    owned_valuation,
)
from sallimbook.core.types import MAX_KRW, decimal_krw

CATALOG = json.loads(
    (Path(__file__).resolve().parents[3] / "packages/test-fixtures/catalog.json").read_text()
)
VECTORS = {vector["id"]: vector for vector in CATALOG["vectors"]}


def vector(number):
    row = VECTORS[f"T-{number:02}"]
    return row["inputs"], row["expected"]


def test_t01_net_assets_and_t02_repeated_account_projection():
    inputs, expected = vector(1)
    total = asset_totals(
        [
            AssetValue("asset", decimal_krw(inputs["assets_krw"])),
            AssetValue("liability", decimal_krw(inputs["liabilities_krw"]), kind="liability"),
        ]
    )
    assert total.net_assets_krw == int(expected["net_assets_krw"])
    assert total.verified_count == total.item_count == 2
    assert total.provisional is False
    inputs, expected = vector(2)
    row = AssetValue(inputs["asset_id"], decimal_krw(inputs["amount_krw"]))
    account_projection = AssetValue(inputs["account_asset_id"], decimal_krw(inputs["amount_krw"]))
    total = asset_totals([row, account_projection])
    assert total.assets_krw == int(expected["household_total_krw"])
    assert total.item_count == expected["included_source_count"]


def test_t03_share_is_applied_once_and_t04_reference_holdings_are_excluded():
    inputs, expected = vector(3)
    owned = owned_valuation(
        decimal_krw(inputs["valuation_krw"]),
        household_share=Decimal(inputs["household_share"]),
        basis=inputs["amount_basis"],
    )
    assert owned == int(expected["owned_amount_krw"])
    household = AssetValue("joint-home", owned)
    assert asset_totals([household, household]).net_assets_krw == int(
        expected["household_total_krw"]
    )
    inputs, expected = vector(4)
    total = asset_totals(
        [
            AssetValue("pension", decimal_krw(inputs["account_total_krw"])),
            *[
                AssetValue(
                    h["label"], decimal_krw(h["amount_krw"]), included=h["included_in_total"]
                )
                for h in inputs["reference_holdings"]
            ],
        ]
    )
    assert total.assets_krw == int(expected["household_total_krw"])
    assert total.item_count == 1


@pytest.mark.parametrize("case", CATALOG["edge_cases"]["household_share_rounding"])
def test_ownership_half_up_and_already_owned_values(case):
    assert owned_valuation(
        decimal_krw(case["amount_krw"]), household_share=Decimal(case["share"]), basis=case["basis"]
    ) == int(case["owned_krw"])


def test_ownership_does_not_round_intermediate_decimal_or_lose_large_integer():
    share = Decimal("0.4999999999999999999999999999999999999999")
    with localcontext() as context:
        context.prec = 3
        assert owned_valuation(1, household_share=share, basis="whole") == 0
    assert owned_valuation(MAX_KRW, household_share=Decimal("1"), basis="whole") == MAX_KRW
    assert asset_totals([AssetValue("large", 9_007_199_254_740_993)]).net_assets_krw == (
        9_007_199_254_740_993
    )


@pytest.mark.parametrize(
    "share", [0.5, 1, True, Decimal("NaN"), Decimal("Infinity"), Decimal("-0.1"), Decimal("1.1")]
)
def test_ownership_rejects_inexact_or_out_of_range_share(share):
    with pytest.raises(ValueError):
        owned_valuation(1, household_share=share, basis="whole")


@pytest.mark.parametrize("case", CATALOG["edge_cases"]["snapshot_states"], ids=lambda c: c["name"])
def test_missing_zero_carried_and_verified_months_remain_distinct(case):
    prior = AssetMonth(
        "2025-01", (AssetValue("a", decimal_krw(case["previous_krw"])),), "confirmed"
    )
    value = None if case["current_krw"] is None else decimal_krw(case["current_krw"])
    current = AssetMonth(
        "2025-02",
        (AssetValue("a", value, verification_state=case["verification_state"]),),
        "confirmed" if case["can_confirm"] else "draft",
    )
    result = compare_months(prior, current)
    expected = case["expected_delta_krw"]
    assert result.total_delta_krw == (None if expected is None else int(expected))
    totals = asset_totals(current.values)
    assert totals.net_assets_krw == (None if value is None else int(value))
    assert totals.provisional is not case["can_confirm"]
    assert result.state == ("available" if case["can_confirm"] else "unconfirmed")


def test_t05_missing_and_t06_first_month_do_not_invent_zero_comparison():
    inputs, expected = vector(5)
    previous = AssetMonth(
        "2025-01", (AssetValue("a", decimal_krw(inputs["previous_amount_krw"])),), "confirmed"
    )
    missing = AssetMonth("2025-02", (AssetValue("a", None, verification_state="missing"),))
    assert compare_months(previous, missing).total_delta_krw is expected["delta_krw"] is None
    inputs, expected = vector(6)
    first = AssetMonth(
        "2025-01", (AssetValue("a", decimal_krw(inputs["current_amount_krw"])),), "confirmed"
    )
    result = compare_months(None, first)
    assert result.state == expected["comparison_state"]
    assert result.total_delta_krw is expected["delta_krw"] is None


def test_t07_late_registration_changes_total_but_not_common_scope():
    inputs, expected = vector(7)
    previous, current = [
        AssetMonth(
            month,
            tuple(
                AssetValue(row["asset_id"], decimal_krw(row["amount_krw"])) for row in inputs[key]
            ),
            "confirmed",
        )
        for month, key in [("2025-01", "previous"), ("2025-02", "current")]
    ]
    result = compare_months(previous, current)
    assert result.total_delta_krw == int(expected["total_delta_krw"])
    assert result.common_scope_delta_krw == int(expected["common_scope_delta_krw"])
    assert result.scope_changed is expected["scope_changed"]
    assert len(result.added_asset_ids) == 1 and result.removed_asset_ids == ()


def test_comparison_handles_removed_asset_and_liability_reduction():
    previous = AssetMonth(
        "2025-01",
        (
            AssetValue("sold", 100),
            AssetValue("debt", 80, kind="liability"),
        ),
        "confirmed",
    )
    current = AssetMonth("2025-02", (AssetValue("debt", 50, kind="liability"),), "confirmed")
    result = compare_months(previous, current)
    assert result.total_delta_krw == -70
    assert result.common_scope_delta_krw == 30
    assert result.removed_asset_ids == ("sold",)
    assert compare_months(previous, replace(current, state="reopened")).total_delta_krw is None
    with pytest.raises(ValueError, match="precede"):
        compare_months(current, previous)
    with pytest.raises(ValueError, match="change"):
        compare_months(previous, replace(current, values=(AssetValue("debt", 50),)))


def test_invalid_or_incomplete_sources_cannot_yield_confirmed_comparison():
    row = AssetValue("a", 10)
    with pytest.raises(ValueError, match="Conflicting"):
        asset_totals([row, replace(row, amount_krw=20)])
    with pytest.raises(ValueError):
        AssetValue("a", None)
    with pytest.raises(ValueError):
        AssetValue("a", None, verification_state="carried_unconfirmed")
    carried_zero = asset_totals([AssetValue("a", 0, verification_state="carried_unconfirmed")])
    assert carried_zero.net_assets_krw == 0 and carried_zero.provisional
    with pytest.raises(ValueError):
        AssetValue("a", 1, verification_state="missing")
    previous = AssetMonth("2025-01", (row,), "confirmed")
    invalid_current = AssetMonth(
        "2025-02", (AssetValue("a", 10, verification_state="carried_unconfirmed"),), "confirmed"
    )
    assert compare_months(previous, invalid_current).state == "unconfirmed"
    with pytest.raises(ValueError):
        asset_totals([AssetValue("a", MAX_KRW), AssetValue("b", 1)])


@pytest.mark.parametrize(
    "amount",
    [
        1.0,
        float("nan"),
        float("inf"),
        True,
        "1",
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("0.5"),
        -1,
        MAX_KRW + 1,
    ],
)
def test_asset_money_rejects_float_nonfinite_fractional_or_out_of_range(amount):
    for operation in [
        lambda: AssetValue("asset", amount),
        lambda: owned_valuation(amount, household_share=Decimal("1"), basis="whole"),
    ]:
        with pytest.raises(ValueError):
            operation()
