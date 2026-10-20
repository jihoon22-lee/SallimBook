"""Validate shared examples, not application/API acceptance behavior.

These checks intentionally do not implement mocked persistence or concurrency.
The pending API, database, web and Android acceptance scenarios need real tests
when those features exist.
"""

import calendar
import json
import re
from collections import Counter
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "packages" / "test-fixtures"
CATALOG = json.loads((FIXTURES / "catalog.json").read_text())
IDENTITIES = json.loads((FIXTURES / "identities.json").read_text())
VECTORS = {vector["id"]: vector for vector in CATALOG["vectors"]}
MEDICAL = CATALOG["fixtures"]["medical_case"]
RECEIPTS = CATALOG["fixtures"]["insurance_receipts"]
RETURN = CATALOG["fixtures"]["insurance_return"]
KRW = re.compile(r"(?:0|-?[1-9][0-9]{0,19})\Z")


def walk(value, path=()):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, (*path, index))


def amounts(records):
    return sum(int(record["amount_krw"]) for record in records)


def parts(number):
    vector = VECTORS[f"T-{number:02}"]
    return vector["inputs"], vector["expected"]


def test_catalog_covers_documented_ids_without_claiming_application_passes():
    documented = set(
        re.findall(r"^\| (T-\d{2}) \|", (ROOT / "docs/testing-and-acceptance.md").read_text(), re.M)
    )
    assert len(CATALOG["vectors"]) == len(VECTORS) == 24
    assert set(VECTORS) == documented == {f"T-{n:02}" for n in range(1, 25)}
    assert CATALOG["synthetic"] is IDENTITIES["synthetic"] is True
    assert CATALOG["schema_version"] == IDENTITIES["schema_version"] == 1
    assert {v["kind"] for v in VECTORS.values()} == {"calculation_vector", "integration_scenario"}


@pytest.mark.parametrize("vector", CATALOG["vectors"], ids=lambda v: v["id"])
def test_each_vector_declares_scope_and_pending_integration_evidence(vector):
    assert vector["implementation_status"] == "pending"
    assert vector["inputs"] and vector["expected"] and vector["title"]
    assert "R-22" in vector["requirements"]
    assert set(vector["required_validation"]) <= {"domain", "api", "web", "android"}
    assert {"api", "web", "android"} <= set(vector["required_validation"])
    if vector["kind"] == "calculation_vector":
        assert "domain" in vector["required_validation"]


@pytest.mark.parametrize("data", [CATALOG, IDENTITIES], ids=["catalog", "identities"])
def test_money_is_exact_decimal_text_and_identifiers_are_uuid(data):
    for path, value in walk(data):
        assert not isinstance(value, float), path
        if not path:
            continue
        field = path[-1] if isinstance(path[-1], str) else path[-2]
        if field.endswith("_krw") and not isinstance(value, list) and value is not None:
            assert isinstance(value, str) and KRW.fullmatch(value), (path, value)
            assert str(int(value)) == value
        if (field.endswith("_id") or field.endswith("_ids")) and value is not None:
            if isinstance(value, list):
                continue
            assert str(UUID(value)) == value, path


def test_identities_are_deterministic_separate_two_member_households():
    namespace = UUID(IDENTITIES["uuid_namespace"])
    households = {h["label"]: h for h in IDENTITIES["households"]}
    assert set(households) == {"H1", "H2"}
    for label, household in households.items():
        assert household["id"] == str(uuid5(namespace, "sallimbook:synthetic:" + label))
        assert household["timezone"] == "Asia/Seoul"
        assert household["base_currency"] == "KRW"
    users = {u["id"]: u for u in IDENTITIES["users"]}
    assert {u["label"] for u in users.values()} == {"A", "B", "C", "D"}
    membership = Counter(m["household_id"] for m in IDENTITIES["members"])
    assert membership == {households["H1"]["id"]: 2, households["H2"]["id"]: 2}
    assert len({m["user_id"] for m in IDENTITIES["members"]}) == 4
    for member in IDENTITIES["members"]:
        label = users[member["user_id"]]["label"]
        expected_household = "H1" if label in {"A", "B"} else "H2"
        assert member["household_id"] == households[expected_household]["id"]
        assert member["status"] == "active"
    all_rows = sum((IDENTITIES[k] for k in ["households", "users", "members", "resources"]), [])
    assert len({row["id"] for row in all_rows}) == len(all_rows)
    for resource in IDENTITIES["resources"]:
        assert resource["household_id"] in membership
    assert MEDICAL["household_id"] == households["H1"]["id"]
    assert MEDICAL["patient_member_id"] in {
        m["id"] for m in IDENTITIES["members"] if m["household_id"] == MEDICAL["household_id"]
    }


def test_fixture_payloads_have_no_secret_or_real_world_identifier_fields():
    forbidden = {
        "pan",
        "cvc",
        "cvv",
        "password",
        "password_hash",
        "access_token",
        "refresh_token",
        "recovery_code",
        "account_number",
        "policy_number",
        "diagnosis_note",
        "diagnosis_code",
        "email",
        "phone",
        "address",
    }
    for data in [CATALOG, IDENTITIES]:
        for path, value in walk(data):
            if isinstance(value, dict):
                assert not forbidden.intersection(value), path


def test_shared_fixture_references_resolve():
    for vector in VECTORS.values():
        for field, reference in vector["inputs"].items():
            if field.endswith("_fixture"):
                resolved = CATALOG["fixtures"]
                for part in reference.split("."):
                    resolved = resolved[part]
                assert resolved, (vector["id"], field)


def test_concurrent_replacements_contend_for_one_household_consumable():
    inputs, expected = parts(21)
    resources = {row["id"]: row for row in IDENTITIES["resources"]}
    assert resources[inputs["consumable_id"]]["kind"] == "consumable"
    assert resources[inputs["consumable_id"]]["household_id"] == inputs["household_id"]
    links = {row["id"]: row for row in inputs["appliance_consumables"]}
    assert len(links) == 2
    assert len({row["appliance_id"] for row in links.values()}) == 2
    assert {row["consumable_id"] for row in links.values()} == {inputs["consumable_id"]}
    assert {row["household_id"] for row in links.values()} == {inputs["household_id"]}
    for request in inputs["requests"]:
        link = links[request["appliance_consumable_id"]]
        assert link["appliance_id"] == request["appliance_id"]
        assert resources[link["appliance_id"]]["household_id"] == inputs["household_id"]
        actor = next(
            row for row in IDENTITIES["members"] if row["id"] == request["actor_member_id"]
        )
        assert actor["household_id"] == inputs["household_id"]
    assert inputs["initial_stock"] == 1 and expected["final_stock"] == 0


def test_payout_cases_exist_in_the_same_household_before_sum_validation():
    resources = {row["id"]: row for row in IDENTITIES["resources"]}
    household_id = MEDICAL["household_id"]
    for number in (18, 19):
        inputs, _ = parts(number)
        for allocation in inputs["allocations"]:
            case = resources[allocation["case_id"]]
            assert case["kind"] == "insurance_case"
            assert case["household_id"] == household_id


def test_benefit_types_match_the_documented_contract():
    benefits = {
        value["benefit_type"]
        for _, value in walk(CATALOG)
        if isinstance(value, dict) and "benefit_type" in value
    }
    assert benefits == {"reimbursement", "fixed_benefit"}


def test_net_assets_ownership_and_reference_holdings_examples():
    inputs, expected = parts(1)
    assert (
        int(inputs["assets_krw"]) - int(inputs["liabilities_krw"])
        == int(expected["net_assets_krw"])
        == 70_000_000
    )
    inputs, expected = parts(2)
    assert inputs["asset_id"] == inputs["account_asset_id"]
    assert expected["included_source_count"] == 1
    assert inputs["amount_krw"] == expected["household_total_krw"]
    inputs, expected = parts(3)
    owned = (Decimal(inputs["valuation_krw"]) * Decimal(inputs["household_share"])).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    assert int(owned) == int(expected["owned_amount_krw"]) == 300_000_000
    assert expected["owned_amount_krw"] == expected["household_total_krw"]
    assert len(inputs["owner_member_ids"]) == 2
    inputs, expected = parts(4)
    assert inputs["account_total_krw"] == expected["household_total_krw"] == "20000000"
    assert inputs["reference_holdings"] == [
        {"label": "합성 ETF", "amount_krw": "15000000", "included_in_total": False}
    ]


def test_comparison_missing_first_month_and_scope_change_expectations():
    inputs, expected = parts(5)
    assert inputs["previous_amount_krw"] is not None
    assert inputs["current_amount_krw"] is expected["delta_krw"] is None
    assert expected["can_confirm"] is False
    inputs, expected = parts(6)
    assert inputs["previous_amount_krw"] is expected["delta_krw"] is None
    assert expected["change_percent"] is None
    inputs, expected = parts(7)
    previous = {row["asset_id"]: int(row["amount_krw"]) for row in inputs["previous"]}
    current = {row["asset_id"]: int(row["amount_krw"]) for row in inputs["current"]}
    assert sum(current.values()) - sum(previous.values()) == int(expected["total_delta_krw"])
    assert (
        sum(current[k] - previous[k] for k in previous.keys() & current.keys())
        == int(expected["common_scope_delta_krw"])
        == 0
    )
    assert current.keys() != previous.keys() and expected["scope_changed"]
    assert expected["inferred_savings_krw"] is None


def test_income_and_fixed_payment_examples_preserve_snapshot_expectations():
    inputs, expected = parts(8)
    assert inputs["income_krw"] == "3000000"
    assert inputs["snapshot_before_krw"] == expected["snapshot_after_krw"] == "5000000"
    inputs, expected = parts(9)
    assert (
        int(inputs["principal_krw"]) + int(inputs["interest_krw"])
        == int(expected["cash_payment_krw"])
        == int(inputs["payment_krw"])
        == 1_000_000
    )
    assert inputs["interest_krw"] == expected["consumption_krw"] == "300000"
    assert inputs["liability_snapshot_before_krw"] == expected["liability_snapshot_after_krw"]
    inputs, expected = parts(11)
    actual = sum(map(int, inputs["actual_payments_krw"]))
    assert actual == int(expected["actual_total_krw"]) == 35_000
    assert actual - int(inputs["expected_krw"]) == int(expected["difference_krw"])


def test_calendar_expected_dates_follow_original_anchor():
    inputs, expected = parts(10)
    calculated = []
    for month in inputs["months"]:
        year, number = map(int, month.split("-"))
        day = min(inputs["anchor_day"], calendar.monthrange(year, number)[1])
        calculated.append(date(year, number, day).isoformat())
    assert calculated == expected["scheduled_dates"] == ["2025-02-28", "2025-03-31"]
    assert expected["occurrence_counts"] == [1, 1]
    annual = CATALOG["edge_cases"]["annual_leap_day"]
    assert [
        date(year, 2, min(29, calendar.monthrange(year, 2)[1])).isoformat()
        for year in annual["years"]
    ] == annual["scheduled_dates"]


def test_medical_graph_has_distinct_sources_details_and_claim_links():
    nodes = {n["id"]: n for n in MEDICAL["nodes"]}
    cash = {c["id"]: c for c in MEDICAL["cash_records"]}
    expenses = {e["id"]: e for e in MEDICAL["expenses"]}
    claims = {c["id"]: c for c in MEDICAL["claims"]}
    assert len(nodes) == len(MEDICAL["nodes"])
    assert len(cash) == len(expenses) == 5
    assert len({e["cash_record_id"] for e in expenses.values()}) == 5
    for node in nodes.values():
        seen = {node["id"]}
        parent = node["parent_id"]
        while parent is not None:
            assert parent in nodes and parent not in seen
            seen.add(parent)
            assert nodes[parent]["case_id"] == node["case_id"] == MEDICAL["case_id"]
            parent = nodes[parent]["parent_id"]
    for expense in expenses.values():
        assert expense["node_id"] in nodes
        assert expense["cash_record_id"] in cash
        assert expense["case_id"] == MEDICAL["case_id"]
    prescription = next(n for n in nodes.values() if n["kind"] == "prescription")
    assert not any(e["node_id"] == prescription["id"] for e in expenses.values())
    lines = MEDICAL["expense_lines"]
    inpatient = expenses[lines[0]["expense_id"]]
    assert all(line["expense_id"] == inpatient["id"] for line in lines)
    assert amounts(lines) == int(cash[inpatient["cash_record_id"]]["amount_krw"]) == 860_000
    links = MEDICAL["claim_expenses"]
    assert len({(link["claim_id"], link["expense_id"]) for link in links}) == 2
    assert {link["expense_id"] for link in links} == {inpatient["id"]}
    for link in links:
        assert claims[link["claim_id"]]["case_id"] == expenses[link["expense_id"]]["case_id"]
    assert amounts(cash.values()) == int(parts(12)[1]["medical_total_krw"]) == 960_000
    assert parts(13)[1]["medical_total_krw"] == "960000"
    assert parts(13)[1]["expense_source_count"] == len(expenses)


def test_refund_return_and_receipt_allocations_keep_original_references():
    refund = MEDICAL["refund"]
    expense = next(e for e in MEDICAL["expenses"] if e["id"] == refund["expense_id"])
    assert refund["reverses_id"] == expense["cash_record_id"]
    original_cash = next(c for c in MEDICAL["cash_records"] if c["id"] == refund["reverses_id"])
    assert 0 < int(refund["amount_krw"]) <= int(original_cash["amount_krw"])
    for receipt in RECEIPTS:
        assert amounts(receipt["allocations"]) == int(receipt["amount_krw"])
        assert all(a["case_id"] == MEDICAL["case_id"] for a in receipt["allocations"])
        assert all(a["claim_id"] is None for a in receipt["allocations"])
    original = next(p for p in RECEIPTS if p["id"] == RETURN["payout_id"])
    assert original["cash_record_id"] == RETURN["reverses_id"]
    allocation = next(
        a for a in original["allocations"] if a["id"] == RETURN["original_allocation_id"]
    )
    assert 0 < int(RETURN["amount_krw"]) <= int(allocation["amount_krw"])
    assert refund["flow"] == "in" and RETURN["flow"] == "out"


@pytest.mark.parametrize(
    "number,refund,returned", [(14, False, False), (15, True, False), (16, True, True)]
)
def test_insurance_example_arithmetic(number, refund, returned):
    _, expected = parts(number)
    medical = amounts(MEDICAL["cash_records"])
    received = amounts(RECEIPTS)
    if refund:
        medical -= int(MEDICAL["refund"]["amount_krw"])
    if returned:
        received -= int(RETURN["amount_krw"])
    assert medical - received == int(expected["net_burden_krw"])
    assert received == int(expected.get("net_received_krw", expected.get("received_krw")))
    if "net_medical_krw" in expected:
        assert medical == int(expected["net_medical_krw"])


def test_negative_burden_and_multi_case_allocation_examples():
    inputs, expected = parts(17)
    assert (
        int(inputs["medical_krw"]) - int(inputs["received_krw"])
        == int(expected["net_burden_krw"])
        == -50_000
    )
    inputs, expected = parts(18)
    assert (
        amounts(inputs["allocations"])
        == int(inputs["receipt_krw"])
        == int(expected["monthly_inflow_krw"])
        == 500_000
    )
    assert {a["case_id"]: a["amount_krw"] for a in inputs["allocations"]} == {
        a["case_id"]: a["amount_krw"] for a in expected["case_totals"]
    }
    inputs, expected = parts(19)
    assert amounts(inputs["allocations"]) == int(expected["allocation_total_krw"]) == 450_000
    assert amounts(inputs["allocations"]) != int(inputs["receipt_krw"])
    assert expected["accepted"] is False
    assert expected["created_cash_records"] == expected["created_payouts"] == 0
    assert expected["created_allocations"] == 0


def test_stock_example_arithmetic_and_concurrency_acceptance_expectations():
    inputs, expected = parts(20)
    assert (
        inputs["initial_stock"] + sum(m["quantity_delta"] for m in inputs["movements"])
        == (expected["final_stock"])
        == 2
    )
    assert inputs["last_replaced_on"] == expected["last_replaced_after_receipt"]
    assert expected["last_replaced_after_replacement"] == inputs["movements"][1]["occurred_on"]
    inputs, expected = parts(21)
    assert sum(r["quantity"] for r in inputs["requests"]) > inputs["initial_stock"]
    assert expected["success_count"] + expected["insufficient_stock_count"] == 2
    assert expected["success_count"] == expected["replacement_count"] == 1
    assert expected["final_stock"] == 0


def test_retry_and_conflict_are_pending_acceptance_expectations():
    inputs, expected = parts(22)
    assert inputs["payout"]["attempts"] == inputs["replacement"]["attempts"] == 2
    assert inputs["payout"]["amount_krw"] == expected["received_krw"]
    assert (
        inputs["replacement"]["initial_stock"] - inputs["replacement"]["quantity"]
        == (expected["final_stock"])
    )
    assert expected["payout_count"] == expected["replacement_count"] == 1
    inputs, expected = parts(23)
    assert inputs["request_version"] == 7 < inputs["stored_version"] == 8
    assert expected["http_status"] == 409 and expected["overwrite_allowed"] is False
    assert expected["stored_version"] == inputs["stored_version"]


def test_today_and_historical_asset_month_have_different_clock_sources():
    inputs, expected = parts(24)
    today = (
        datetime.fromisoformat(inputs["now_utc"]).astimezone(ZoneInfo(inputs["timezone"])).date()
    )
    assert today.isoformat() == expected["consumables_as_of"] == "2026-10-17"
    assert expected["asset_month"] == inputs["selected_asset_month"]
    assert today.strftime("%Y-%m") != inputs["selected_asset_month"]
    assert expected["replacement_due"] == (date.fromisoformat(inputs["next_check_on"]) <= today)
    assert expected["purchase_needed"] == (inputs["stock"] == 0)


def test_supplementary_money_states_and_rounding_examples():
    edges = CATALOG["edge_cases"]
    for case in edges["exact_money"]:
        assert str(int(case["value_krw"])) == case["canonical_krw"]
    assert any(abs(int(case["value_krw"])) > 2**53 for case in edges["exact_money"])
    for encoded in edges["invalid_money_json"]:
        value = json.loads(encoded)
        assert not (isinstance(value, str) and KRW.fullmatch(value)), encoded
    states = {s["name"]: s for s in edges["snapshot_states"]}
    assert set(states) == {"missing", "verified_zero", "carried_unconfirmed", "verified_unchanged"}
    assert states["missing"]["current_krw"] is None
    assert states["verified_zero"]["current_krw"] == "0"
    assert states["carried_unconfirmed"]["can_confirm"] is False
    for case in states.values():
        if case["verification_state"] == "verified":
            assert int(case["current_krw"]) - int(case["previous_krw"]) == int(
                case["expected_delta_krw"]
            )
        else:
            assert case["expected_delta_krw"] is None
    for case in edges["household_share_rounding"]:
        owned = Decimal(case["amount_krw"])
        if case["basis"] == "whole":
            owned *= Decimal(case["share"])
        assert str(owned.quantize(Decimal("1"), rounding=ROUND_HALF_UP)) == case["owned_krw"]
