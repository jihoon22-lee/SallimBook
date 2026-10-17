"""Synthetic contract and domain-separated server-field encryption checks."""

import secrets
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sallimbook.accounts.crypto import KeyRing, SealedNumber
from sallimbook.accounts.crypto import encrypt_number as encrypt_account
from sallimbook.core.errors import DomainError
from sallimbook.insurance.crypto import decrypt_number, encrypt_number
from sallimbook.insurance.schemas import (
    CaseInput,
    CasePatch,
    CoverageInput,
    CoveragePatch,
    MedicalNodeInput,
    MedicalNodePatch,
    PolicyCreate,
    PolicyPatch,
)


@pytest.mark.parametrize(
    "schema,field",
    [
        (PolicyPatch, "insurer"),
        (PolicyPatch, "product_name"),
        (PolicyPatch, "coverage_start"),
        (PolicyPatch, "status"),
        (CoveragePatch, "name"),
        (CoveragePatch, "benefit_type"),
        (CoveragePatch, "active"),
        (CasePatch, "title"),
        (CasePatch, "patient_member_id"),
        (CasePatch, "start_on"),
        (CasePatch, "treatment_state"),
        (CasePatch, "financial_state"),
        (MedicalNodePatch, "kind"),
        (MedicalNodePatch, "label"),
        (MedicalNodePatch, "sort_order"),
    ],
)
def test_optional_required_patch_fields_reject_null_and_do_not_advertise_it(schema, field):
    prop = schema.model_json_schema()["properties"][field]
    assert prop.get("type") != "null"
    assert not any(choice.get("type") == "null" for choice in prop.get("anyOf", []))
    assert field not in schema.model_json_schema().get("required", [])
    with pytest.raises(ValidationError):
        schema.model_validate(
            {field: None, **({"reason": "합성 정정"} if schema is CasePatch else {})}
        )


def test_clearable_fields_and_zero_coverage_are_distinct_from_missing():
    assert PolicyPatch(policy_number=None).model_fields_set == {"policy_number"}
    assert CoverageInput(name="합성 보장", benefit_type="fixed").insured_amount_krw is None
    assert (
        CoverageInput(
            name="합성 보장", benefit_type="fixed", insured_amount_krw="0"
        ).insured_amount_krw
        == "0"
    )
    assert MedicalNodePatch(parent_id=None).model_fields_set == {"parent_id"}
    for schema in (PolicyPatch, CoveragePatch, MedicalNodePatch):
        with pytest.raises(ValidationError):
            schema()
    with pytest.raises(ValidationError):
        CasePatch(reason="합성 사유만")


def test_policy_distinguishes_contract_coverage_and_payment_periods():
    policy = PolicyCreate(
        insurer="합성 보험사",
        product_name="합성 상품",
        contract_start="2026-01-01",
        contract_end="2060-01-01",
        coverage_start="2026-02-01",
        coverage_end="2050-01-01",
        payment_start="2026-01-10",
        payment_end="2030-01-10",
    )
    assert policy.contract_end != policy.coverage_end != policy.payment_end
    for field in ("contract_end", "coverage_end", "payment_end"):
        with pytest.raises(ValidationError):
            PolicyCreate.model_validate(policy.model_dump() | {field: "2025-01-01"})
    assert not any("premium" in field or "balance" in field for field in PolicyCreate.model_fields)


def test_case_states_are_independent_and_treatment_reopening_clears_end():
    payload = {"title": "합성 사건", "patient_member_id": uuid4(), "start_on": "2026-01-01"}
    assert CaseInput(**payload, financial_state="settled").treatment_state == "ongoing"
    assert (
        CaseInput(**payload, treatment_state="ended", end_on="2026-01-02").financial_state == "open"
    )
    with pytest.raises(ValidationError):
        CaseInput(**payload, treatment_state="ended")
    with pytest.raises(ValidationError):
        CaseInput(**payload, end_on="2026-01-02")
    with pytest.raises(ValidationError):
        CaseInput(**payload, policy_id=uuid4())


def test_prescription_is_a_node_with_no_amount_or_cash_fields():
    prescription = MedicalNodeInput(kind="prescription", label="합성 처방")
    assert not any(
        "amount" in field or "cash" in field for field in type(prescription).model_fields
    )
    with pytest.raises(ValidationError):
        MedicalNodeInput(kind="prescription", label="합성 처방", amount_krw="100")


def test_policy_number_encryption_random_nonce_and_all_identity_bindings():
    ring = KeyRing(1, {1: secrets.token_bytes(32), 2: secrets.token_bytes(32)})
    household, policy = uuid4(), uuid4()
    number = "SYNTHETIC-POLICY-0011"
    sealed = encrypt_number(ring, household, policy, number)
    other = encrypt_number(ring, household, policy, number)
    assert sealed.nonce != other.nonce and sealed.ciphertext != other.ciphertext
    assert number.encode() not in sealed.ciphertext
    assert decrypt_number(ring, household, policy, sealed) == number
    for hh, identifier, envelope in (
        (uuid4(), policy, sealed),
        (household, uuid4(), sealed),
        (household, policy, SealedNumber(2, sealed.nonce, sealed.ciphertext)),
        (
            household,
            policy,
            SealedNumber(
                1, sealed.nonce, sealed.ciphertext[:-1] + bytes([sealed.ciphertext[-1] ^ 1])
            ),
        ),
        (household, policy, encrypt_account(ring, household, policy, number)),
    ):
        with pytest.raises(DomainError) as rejected:
            decrypt_number(ring, hh, identifier, envelope)
        assert rejected.value.code == "POLICY_NUMBER_UNAVAILABLE"
    assert "SYNTHETIC-POLICY" not in repr(
        PolicyCreate(
            insurer="합성",
            product_name="합성",
            coverage_start="2026-01-01",
            policy_number=number,
        )
    )
