"""Synthetic quantity, date, shared-fixture and homecare contract tests; no database claims."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateTable

from sallimbook import models as registered_models  # noqa: F401
from sallimbook.core.types import SEOUL
from sallimbook.homecare.calculations import (
    MAX_QUANTITY,
    StockMovement,
    consumable_status,
    next_check_on,
    quantity_after_replacement,
    stock_balance,
)
from sallimbook.homecare.models import (
    Appliance,
    ApplianceConsumable,
    Consumable,
    ConsumableReplacement,
)
from sallimbook.homecare.models import (
    StockMovement as StockMovementModel,
)
from sallimbook.homecare.schemas import (
    ApplianceConsumableCreate,
    ApplianceConsumableFields,
    ApplianceConsumablePatch,
    ApplianceInput,
    AppliancePatch,
    ConsumableInput,
    ConsumablePatch,
    ReplacementCreate,
    StockCancellation,
    StockMovementCreate,
    StockMutationReference,
)

CATALOG = json.loads(
    (Path(__file__).resolve().parents[3] / "packages/test-fixtures/catalog.json").read_text()
)


def vector(identifier):
    return next(row for row in CATALOG["vectors"] if row["id"] == identifier)


def test_t20_receipt_and_replacement_have_independent_stock_and_dates():
    case = vector("T-20")
    last = date.fromisoformat(case["inputs"]["last_replaced_on"])
    receipt, replacement = case["inputs"]["movements"]
    receipt_fact = StockMovement("synthetic-receipt", receipt["kind"], receipt["quantity_delta"])
    stock = stock_balance([receipt_fact])
    assert stock == case["expected"]["stock_after_receipt"]
    assert last.isoformat() == case["expected"]["last_replaced_after_receipt"]
    assert next_check_on(last, interval_unit="months", interval_count=2) == date(2025, 3, 1)
    replacement_fact = StockMovement(
        "synthetic-replacement", replacement["kind"], replacement["quantity_delta"]
    )
    assert stock_balance([receipt_fact, replacement_fact]) == case["expected"]["final_stock"]
    assert (
        quantity_after_replacement(stock, -replacement["quantity_delta"])
        == case["expected"]["final_stock"]
    )
    last = date.fromisoformat(replacement["occurred_on"])
    assert last.isoformat() == case["expected"]["last_replaced_after_replacement"]


def test_t24_current_seoul_date_is_independent_of_selected_asset_month():
    case = vector("T-24")
    moment = datetime.fromisoformat(case["inputs"]["now_utc"].replace("Z", "+00:00"))
    today = moment.astimezone(SEOUL).date()
    status = consumable_status(
        today=today,
        stock=case["inputs"]["stock"],
        next_check=date.fromisoformat(case["inputs"]["next_check_on"]),
    )
    assert status.as_of.isoformat() == case["expected"]["consumables_as_of"]
    assert status.replacement_due is case["expected"]["replacement_due"]
    assert status.purchase_needed is case["expected"]["purchase_needed"]
    assert today.strftime("%Y-%m") != case["inputs"]["selected_asset_month"]
    assert datetime(2026, 10, 16, 14, 59, tzinfo=UTC).astimezone(SEOUL).date() == date(2026, 10, 16)
    assert datetime(2026, 10, 16, 15, 0, tzinfo=UTC).astimezone(SEOUL).date() == today


def test_month_end_and_leap_day_replacement_intervals():
    assert next_check_on(date(2025, 1, 31), interval_unit="months", interval_count=1) == date(
        2025, 2, 28
    )
    assert next_check_on(date(2024, 1, 31), interval_unit="months", interval_count=1) == date(
        2024, 2, 29
    )
    assert next_check_on(date(2024, 2, 29), interval_unit="months", interval_count=12) == date(
        2025, 2, 28
    )
    assert next_check_on(date(2026, 1, 31), interval_unit="months", interval_count=2) == date(
        2026, 3, 31
    )
    assert next_check_on(date(2026, 1, 31), interval_unit="days", interval_count=1) == date(
        2026, 2, 1
    )


def test_unknown_last_replacement_and_zero_stock_remain_distinct():
    assert next_check_on(None, interval_unit="months", interval_count=1) is None
    assert next_check_on(
        None, interval_unit="months", interval_count=1, override=date(2026, 3, 1)
    ) == date(2026, 3, 1)
    unknown = consumable_status(today=date(2026, 3, 1), stock=0, next_check=None)
    assert unknown.replacement_due is None and unknown.purchase_needed is True
    due = consumable_status(today=date(2026, 3, 1), stock=1, next_check=date(2026, 3, 1))
    assert due.replacement_due is True and due.purchase_needed is False
    assert (
        consumable_status(
            today=date(2026, 3, 1), stock=1, next_check=None, required_quantity=2
        ).purchase_needed
        is True
    )


@pytest.mark.parametrize("value", [-1, True, 1.5, "1", MAX_QUANTITY + 1])
def test_invalid_stock_quantity_rejected_without_float_coercion(value):
    with pytest.raises(ValueError):
        quantity_after_replacement(value, 1)
    with pytest.raises(ValidationError):
        ConsumableInput(name="합성 필터", unit="개", low_stock_threshold=value)


@pytest.mark.parametrize("delta", [0, True, 1.5, "1", MAX_QUANTITY + 1, -MAX_QUANTITY - 1])
def test_stock_delta_requires_nonzero_bounded_integer(delta):
    with pytest.raises(ValidationError):
        StockMovementCreate(
            kind="adjustment", quantity_delta=delta, occurred_on="2026-01-01", reason="합성 조정"
        )


def test_original_movement_and_full_reversal_are_unique_and_balance_exactly():
    receipt = StockMovement("synthetic-r", "receipt", 3)
    replacement = StockMovement("synthetic-p", "replacement", -1)
    reversal = StockMovement(
        "synthetic-c", "reversal", 1, reversal_of=replacement.id, reason="합성 취소"
    )
    assert stock_balance([receipt, replacement, reversal, receipt]) == 3
    with pytest.raises(ValueError):
        stock_balance(
            [
                receipt,
                replacement,
                reversal,
                StockMovement("synthetic-c2", "reversal", 1, reversal_of=replacement.id),
            ]
        )
    with pytest.raises(ValueError):
        stock_balance(
            [
                receipt,
                replacement,
                StockMovement("synthetic-wrong", "reversal", 2, reversal_of=replacement.id),
            ]
        )
    with pytest.raises(ValueError):
        stock_balance([receipt, StockMovement("synthetic-overflow", "receipt", MAX_QUANTITY)])
    with pytest.raises(ValueError):
        quantity_after_replacement(0, 1)


@pytest.mark.parametrize(
    "overrides",
    [
        {"interval_unit": "months", "interval_count": None},
        {"interval_unit": "months", "interval_count": 121},
        {"interval_unit": "days", "interval_count": 3651},
        {"interval_unit": "manual", "interval_count": 1},
        {"interval_unit": "days", "interval_count": True},
        {"quantity_per_replacement": 0},
    ],
)
def test_device_specific_interval_requires_explicit_valid_policy(overrides):
    with pytest.raises(ValidationError):
        ApplianceConsumableFields(**overrides)


def test_manual_cycle_and_two_device_intervals_do_not_share_replacement_policy():
    sku = uuid4()
    first = ApplianceConsumableCreate(
        appliance_id=uuid4(), consumable_id=sku, interval_unit="days", interval_count=30
    )
    second = ApplianceConsumableCreate(
        appliance_id=uuid4(), consumable_id=sku, interval_unit="months", interval_count=3
    )
    assert first.consumable_id == second.consumable_id and first.appliance_id != second.appliance_id
    assert (first.interval_unit, first.interval_count) != (
        second.interval_unit,
        second.interval_count,
    )
    assert ApplianceConsumableFields().interval_count is None


def test_appliance_price_uses_decimal_strings_without_creating_asset_fields():
    for price in (None, "0", "99999999999999999999"):
        assert (
            ApplianceInput(name="합성 가전", purchase_price_krw=price).purchase_price_krw == price
        )
    for value in (0, 1.0, "-1", "1.0"):
        with pytest.raises(ValidationError):
            ApplianceInput(name="합성 가전", purchase_price_krw=value)
    with pytest.raises(ValidationError):
        ApplianceInput(name="합성 가전", asset_id=uuid4())
    with pytest.raises(ValidationError):
        ConsumableInput(name="합성 필터", unit="개", stock_quantity=3)
    with pytest.raises(ValidationError):
        ConsumablePatch(stock_quantity=3)


def test_unknown_sku_is_allowed_and_partial_patches_do_not_clear_required_fields():
    assert ConsumableInput(name="합성 사용자 규격", unit="개").sku_or_model is None
    for schema, payload in (
        (AppliancePatch, {}),
        (AppliancePatch, {"name": None}),
        (ConsumablePatch, {"unit": None}),
        (ApplianceConsumablePatch, {"active": None}),
    ):
        with pytest.raises(ValidationError):
            schema(**payload)
    assert ConsumablePatch(sku_or_model=None).model_fields_set == {"sku_or_model"}


def test_replacement_and_cancellation_commands_reject_unbound_or_forged_inputs():
    with pytest.raises(ValidationError):
        ReplacementCreate(replaced_on="2026-01-01", quantity=1)
    with pytest.raises(ValidationError):
        ReplacementCreate(
            replaced_on="2026-01-01", quantity=1, link_version=1, stock_movement_id=uuid4()
        )
    with pytest.raises(ValidationError):
        StockCancellation(occurred_on="2026-01-01", reason=" ")
    for kind in ("replacement", "reversal"):
        with pytest.raises(ValidationError):
            StockMovementCreate(kind=kind, quantity_delta=1, occurred_on="2026-01-01")
    for kind, delta in (("receipt", -1), ("return_in", -1), ("return_out", 1)):
        with pytest.raises(ValidationError):
            StockMovementCreate(kind=kind, quantity_delta=delta, occurred_on="2026-01-01")
    with pytest.raises(ValidationError):
        StockMovementCreate(kind="adjustment", quantity_delta=1, occurred_on="2026-01-01")


@pytest.mark.parametrize(
    "url",
    [
        "http://synthetic.invalid",
        "javascript:alert(1)",
        "https://user:pass@synthetic.invalid",
        "https://synthetic.invalid:invalid",
        "https://synthetic.invalid/\nnext",
    ],
)
def test_purchase_link_is_https_metadata_without_credentials(url):
    with pytest.raises(ValidationError):
        StockMovementCreate(
            kind="receipt", quantity_delta=1, occurred_on="2026-01-01", purchase_url=url
        )


def test_movement_result_keeps_original_stock_version_as_an_immutable_reference():
    result = StockMutationReference(
        id=uuid4(), consumable_id=uuid4(), stock_version=7, replacement_id=None
    )
    assert result.model_dump(mode="json")["stock_version"] == 7
    assert "stock_quantity" not in StockMutationReference.model_fields
    assert TypeAdapter(StockMutationReference).json_schema()["required"] == [
        "id",
        "consumable_id",
        "stock_version",
        "replacement_id",
    ]


def test_all_five_homecare_models_compile_with_scoped_restrictive_relationships():
    for model in (
        Appliance,
        Consumable,
        ApplianceConsumable,
        StockMovementModel,
        ConsumableReplacement,
    ):
        ddl = str(CreateTable(model.__table__).compile(dialect=dialect()))
        assert "household_id" in ddl and "ON DELETE RESTRICT" in ddl
    assert "stock_quantity" not in Appliance.__table__.c
    assert "asset_id" not in Appliance.__table__.c
    assert "last_replaced_on" not in ApplianceConsumable.__table__.c
    assert "reversal_of" in StockMovementModel.__table__.c
