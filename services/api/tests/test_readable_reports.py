"""Readable export contracts and synthetic actual-year fixtures."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sallimbook.exports.annual import totals
from sallimbook.exports.schemas import ExportRequest


def test_annual_integer_net_values_preserve_refunds_and_large_amounts():
    assert totals(
        {
            "medical_paid": 9007199254740993,
            "medical_refunded": 9007199254740994,
            "insurance_received": 0,
            "insurance_returned": 25,
        }
    ) == {
        "medical_paid": 9007199254740993,
        "medical_refunded": 9007199254740994,
        "insurance_received": 0,
        "insurance_returned": 25,
        "net_medical": -1,
        "net_insurance": -25,
        "net_burden": 24,
    }


def test_readable_only_and_original_default_are_separate():
    assert ExportRequest().formats == ["json", "csv"]
    assert (
        ExportRequest(formats=[], readable={"domains": ["insurance"], "annual_year": 9999}).formats
        == []
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"formats": []},
        {"readable": {"domains": []}},
        {"readable": {"domains": ["vault"]}},
        {"readable": {"domains": ["assets", "assets"]}},
        {"readable": {"domains": ["assets"], "annual_year": 2026}},
        {"readable": {"domains": ["insurance"], "annual_year": True}},
        {"readable": {"domains": ["insurance"], "annual_year": 10000}},
        {
            "readable": {
                "domains": ["income"],
                "from_date": "2026-02-01",
                "through_date": "2026-01-31",
            }
        },
        {"readable": {"domains": ["income"], "from_date": "2026-02-30"}},
        {"readable": {"domains": ["income"], "household_id": "unknown"}},
    ],
)
def test_readable_scope_rejects_invalid_or_ambiguous_inputs(payload):
    with pytest.raises(ValidationError):
        ExportRequest.model_validate(payload)


def test_common_annual_family_fixture():
    fixture = json.loads(
        (Path(__file__).resolve().parents[3] / "packages/test-fixtures/catalog.json").read_text()
    )["edge_cases"]["annual_family_cash_year"]
    for source, expected in (
        ("patient", "expected"),
        ("prior_year_refund", "prior_year_refund_expected"),
    ):
        result = totals(
            {key.removesuffix("_krw"): int(value) for key, value in fixture[source].items()}
        )
        assert {key: str(result[key.removesuffix("_krw")]) for key in fixture[expected]} == fixture[
            expected
        ]
