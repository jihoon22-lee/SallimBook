from datetime import UTC, datetime
from decimal import Decimal, localcontext

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from sallimbook.core.types import (
    KrwString,
    SignedKrwString,
    YearMonth,
    decimal_krw,
    krw_string,
    month_end,
    month_start,
    seoul_month,
)


@pytest.mark.parametrize("value", ["0", "9007199254740993", "99999999999999999999"])
def test_money_is_exact_string(value):
    assert TypeAdapter(KrwString).validate_python(value) == value
    assert krw_string(decimal_krw(value)) == value


def test_money_validation_is_independent_of_decimal_precision():
    with localcontext() as context:
        context.prec = 3
        assert krw_string(99999999999999999999) == "99999999999999999999"
        assert krw_string(Decimal("-99999999999999999999")) == "-99999999999999999999"


@pytest.mark.parametrize(
    "value", [0, 1.5, True, None, "1.5", "1e3", "+1", "01", "-0", " 1", "100000000000000000000"]
)
def test_noncanonical_money_is_rejected(value):
    with pytest.raises(ValidationError):
        TypeAdapter(SignedKrwString).validate_python(value)


@pytest.mark.parametrize("value", [1.0, True, Decimal("0.1"), Decimal("NaN"), Decimal("Infinity")])
def test_database_money_conversion_never_rounds_or_accepts_float(value):
    with pytest.raises(ValueError):
        krw_string(value)


def test_null_zero_and_negative_are_distinct():
    class Valuation(BaseModel):
        amount_krw: SignedKrwString | None

    assert Valuation(amount_krw=None).model_dump_json() == '{"amount_krw":null}'
    assert Valuation(amount_krw="0").model_dump_json() == '{"amount_krw":"0"}'
    assert Valuation(amount_krw="-50000").model_dump_json() == '{"amount_krw":"-50000"}'


@pytest.mark.parametrize("value", ["2026-13", "2026-00", "0000-01", "2026-1", "2026-01-01", 202601])
def test_invalid_month_is_rejected(value):
    with pytest.raises(ValidationError):
        TypeAdapter(YearMonth).validate_python(value)


def test_seoul_month_boundaries_and_leap_year():
    assert seoul_month(datetime(2026, 10, 31, 14, 59, tzinfo=UTC)) == "2026-10"
    assert seoul_month(datetime(2026, 10, 31, 15, tzinfo=UTC)) == "2026-11"
    assert month_start("2026-10").isoformat() == "2026-10-01"
    assert month_end("2024-02").isoformat() == "2024-02-29"
    assert month_end("2025-02").isoformat() == "2025-02-28"
    with pytest.raises(ValueError):
        seoul_month(datetime(2026, 10, 1))


def test_openapi_money_is_string_not_json_number():
    schema = TypeAdapter(KrwString).json_schema()
    assert schema["type"] == "string"
    assert schema["maxLength"] == 20


def test_audit_vocabulary_has_one_definition():
    from typing import get_args

    from sallimbook.audit import service as audit_service
    from sallimbook.core import audit

    assert audit.ENTITY_TYPES == frozenset(get_args(audit.AuditEntityType))
    assert audit.ACTIONS == frozenset(get_args(audit.AuditAction))
    assert audit_service.ENTITY_TYPES is audit.ENTITY_TYPES
    assert audit_service.ACTIONS is audit.ACTIONS
    assert {"registered_device", "passkey", "invitation"} <= audit.ENTITY_TYPES
    assert {"login", "revoke", "accept"} <= audit.ACTIONS
