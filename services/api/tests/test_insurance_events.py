"""Synthetic actual-source, allocation, correction and household boundary regressions."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from test_accounts import make_actor
from test_income import CATALOG, close_account, headers, income_payload, make_account
from test_insurance_core import case_payload, policy_payload
from test_recurring import generate, obligation_for, post_rule, settle

from sallimbook.assets import month_service
from sallimbook.assets.month_schemas import MonthDraft, MonthValueUpdate
from sallimbook.cashflow import service as cash
from sallimbook.cashflow.models import CashRecord, CashRecordRevision
from sallimbook.cashflow.recurring_router import router as recurring_router
from sallimbook.cashflow.router import router as income_router
from sallimbook.config import Settings
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract
from sallimbook.core.idempotency import IdempotencyRecord
from sallimbook.core.types import MAX_KRW
from sallimbook.insurance import calculations as calc
from sallimbook.insurance import event_service as service
from sallimbook.insurance.event_models import (
    ClaimExpense,
    ClaimRevisionExpense,
    InsuranceClaimRevision,
    InsurancePayout,
    MedicalExpense,
    MedicalExpenseLine,
    MedicalRefund,
    PayoutAllocation,
    PayoutAllocationRevision,
)
from sallimbook.insurance.event_router import router
from sallimbook.insurance.event_schemas import (
    AllocationInput,
    AllocationLinkPatch,
    ClaimPatch,
    ExpenseCreate,
    PayoutCreate,
    RefundCreate,
    ReturnCreate,
)
from sallimbook.insurance.router import router as core_router

BASE = "/api/v1/insurance"
MEDICAL = CATALOG["fixtures"]["medical_case"]


def vector(identifier):
    return next(row for row in CATALOG["vectors"] if row["id"] == identifier)


def fixture_benefit(value):
    # The design fixture predates the generated API's canonical BenefitType='fixed'.
    return "fixed" if value == "fixed_benefit" else value


def actual(amount="100", **changes):
    return {"amount_krw": amount, "occurred_on": "2026-01-31", **changes}


def expense_payload(case_id=None, node_id=None, **changes):
    return actual(case_id=str(case_id or uuid4()), node_id=str(node_id or uuid4()), **changes)


def allocation(case_id, amount="100", **changes):
    return {"case_id": str(case_id), "amount_krw": amount, "benefit_type": "other", **changes}


def payout_payload(case_id=None, **changes):
    return actual(allocations=[allocation(case_id or uuid4())]) | changes


@pytest.mark.parametrize(
    "amount", [0, 100, True, 1.5, "0", "-1", "1.5", "01", "1e3", str(MAX_KRW + 1)]
)
def test_actual_events_reject_non_positive_or_inexact_amounts(amount):
    with pytest.raises(ValidationError):
        ExpenseCreate.model_validate(expense_payload() | {"amount_krw": amount})
    with pytest.raises(ValidationError):
        PayoutCreate.model_validate(payout_payload() | {"amount_krw": amount})


def test_exact_lines_optional_references_and_allocation_sum_and_canonical_benefit():
    assert ExpenseCreate(**expense_payload(gross_medical_krw=None)).gross_medical_krw is None
    assert ExpenseCreate(**expense_payload(gross_medical_krw="0")).gross_medical_krw == "0"
    assert ExpenseCreate(**expense_payload(lines=[])).lines == []
    assert (
        len(ExpenseCreate(**expense_payload(lines=[{"label": "합성", "amount_krw": "100"}])).lines)
        == 1
    )
    with pytest.raises(ValidationError):
        ExpenseCreate(**expense_payload(lines=[{"label": "합성", "amount_krw": "99"}]))
    with pytest.raises(ValidationError):
        PayoutCreate(**payout_payload(allocations=[allocation(uuid4(), "99")]))
    with pytest.raises(ValidationError):
        PayoutCreate(**payout_payload(card_id=uuid4()))
    with pytest.raises(ValidationError):
        AllocationInput(**allocation(uuid4(), benefit_type="fixed_benefit"))
    assert AllocationInput(**allocation(uuid4(), benefit_type="fixed")).benefit_type == "fixed"
    for body in (
        {"amount_krw": "1", "reason": "합성"},
        {"case_id": str(uuid4()), "reason": "합성"},
    ):
        with pytest.raises(ValidationError):
            AllocationLinkPatch.model_validate(body)
    with pytest.raises(ValidationError):
        ClaimPatch(expense_ids=None, reason="합성")


@pytest.mark.parametrize("number", [14, 15, 16])
def test_fixture_insurance_calculations_preserve_original_money(number):
    amounts = {r["id"]: Decimal(r["amount_krw"]) for r in MEDICAL["cash_records"]}
    payments = [
        calc.MedicalPayment(r["cash_record_id"], r["case_id"], amounts[r["cash_record_id"]])
        for r in MEDICAL["expenses"]
    ]
    payouts = [
        calc.Payout(
            p["id"],
            Decimal(p["amount_krw"]),
            tuple(
                calc.Allocation(
                    a["id"],
                    a["case_id"],
                    Decimal(a["amount_krw"]),
                    fixture_benefit(a["benefit_type"]),
                    a["claim_id"],
                )
                for a in p["allocations"]
            ),
        )
        for p in CATALOG["fixtures"]["insurance_receipts"]
    ]
    refund, returned = MEDICAL["refund"], CATALOG["fixtures"]["insurance_return"]
    summary = calc.insurance_summary(
        payments,
        payouts,
        refunds=[
            calc.MedicalRefund(refund["id"], refund["reverses_id"], Decimal(refund["amount_krw"]))
        ]
        if number >= 15
        else [],
        returns=[
            calc.InsuranceReturn(
                returned["id"],
                returned["payout_id"],
                returned["original_allocation_id"],
                Decimal(returned["amount_krw"]),
            )
        ]
        if number >= 16
        else [],
    )
    expected = vector(f"T-{number}")["expected"]
    balance = summary.cases[MEDICAL["case_id"]]
    assert str(balance.net_burden_krw) == expected["net_burden_krw"]
    assert str(balance.net_received_krw) == expected.get(
        "net_received_krw", expected.get("received_krw")
    )
    assert balance.net_fixed_krw == 200000


def test_calculation_rejects_refund_return_overflow_and_deduplicates_source_ids():
    payment = calc.MedicalPayment("m", "case", 100)
    payout = calc.Payout("p", 100, (calc.Allocation("a", "case", 100, "fixed"),))
    assert (
        calc.insurance_summary([payment, payment], [payout, payout]).cases["case"].net_burden_krw
        == 0
    )
    with pytest.raises(ValueError):
        calc.insurance_summary([payment], [], refunds=[calc.MedicalRefund("r", "m", 101)])
    with pytest.raises(ValueError):
        calc.insurance_summary([], [payout], returns=[calc.InsuranceReturn("r", "p", "a", 101)])
    with pytest.raises(ValueError):
        calc.insurance_summary([payment, calc.MedicalPayment("m", "case", 101)], [])


def test_event_contract_returns_immutable_money_references_and_preserves_metadata_boundaries():
    app = FastAPI()
    app.include_router(router)
    document = app.openapi()
    assert sum(len(methods) for methods in document["paths"].values()) == 34
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            if method not in {"post", "patch"}:
                continue
            names = {p["name"] for p in operation.get("parameters", []) if p["in"] == "header"}
            claim = "/claims" in path
            assert ("Idempotency-Key" in names) is not claim
            if "{" in path:
                assert "If-Match" in names
            if not claim:
                status = "201" if method == "post" and not path.endswith("/void") else "200"
                assert operation["responses"][status]["content"]["application/json"]["schema"][
                    "$ref"
                ].endswith("/EventReference")
    fields = document["components"]["schemas"]["AllocationLinkPatch"]["properties"]
    assert set(fields) == {"policy_id", "claim_id", "reason"}


@pytest.fixture
def actors(db_engine):
    first = make_actor(db_engine)
    return first, make_actor(db_engine, first.household_id), make_actor(db_engine)


@pytest.fixture
def app(db_engine):
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(app)
    for item in (core_router, router, income_router, recurring_router):
        app.include_router(item)
    return app


def create_metadata(client, actor, path, body):
    response = client.post(BASE + path, headers=actor.headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def new_case(client, actor):
    return create_metadata(client, actor, "/cases", case_payload(actor))


def new_node(client, actor, case, **changes):
    return create_metadata(
        client,
        actor,
        f"/cases/{case['id']}/nodes",
        {"kind": "outpatient", "label": "합성 진료", **changes},
    )


def new_policy(client, actor):
    return create_metadata(client, actor, "/policies", policy_payload())


def read(client, actor, path):
    response = client.get(BASE + path, headers=actor.headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def money(client, actor, path, body, *, version=None, key=None, status=201):
    response = client.post(BASE + path, headers=headers(actor, key, version), json=body)
    assert response.status_code == status, response.text
    assert set(response.json()) == {"id", "version"}
    assert response.headers["etag"] == f'"{response.json()["version"]}"'
    return response.json()


def new_expense(client, actor, case, node, amount="100", **changes):
    reference = money(
        client,
        actor,
        "/medical-expenses",
        expense_payload(case["id"], node["id"]) | actual(amount, **changes),
    )
    return read(client, actor, f"/medical-expenses/{reference['id']}")


def new_payout(client, actor, allocations, **changes):
    body = actual(
        str(sum(int(r["amount_krw"]) for r in allocations)), allocations=allocations, **changes
    )
    reference = money(client, actor, "/payouts", body)
    return read(client, actor, f"/payouts/{reference['id']}")


def summary(client, actor, case):
    return read(client, actor, f"/cases/{case['id']}/summary")


@pytest.mark.database
class TestInsuranceEventFixtures:
    def test_t12_to_t16_and_t22_originals_claims_refunds_returns_and_subtrees(
        self, app, actors, db_engine
    ):
        actor = actors[0]
        with TestClient(app) as client:
            case = new_case(client, actor)
            nodes = {}
            aliases = {
                "procedure_detail": "surgery",
                "followup": "group",
                "followup_1": "follow_up",
                "followup_2": "follow_up",
            }
            for fixture in MEDICAL["nodes"]:
                nodes[fixture["id"]] = new_node(
                    client,
                    actor,
                    case,
                    kind=aliases.get(fixture["kind"], fixture["kind"]),
                    parent_id=nodes[fixture["parent_id"]]["id"] if fixture["parent_id"] else None,
                )
            amounts = {r["id"]: r["amount_krw"] for r in MEDICAL["cash_records"]}
            expenses = {}
            for fixture in MEDICAL["expenses"]:
                lines = [
                    {"label": row["label"], "amount_krw": row["amount_krw"]}
                    for row in MEDICAL["expense_lines"]
                    if row["expense_id"] == fixture["id"]
                ]
                expenses[fixture["id"]] = new_expense(
                    client,
                    actor,
                    case,
                    nodes[fixture["node_id"]],
                    amounts[fixture["cash_record_id"]],
                    lines=lines,
                    gross_medical_krw="1200000" if lines else None,
                    public_coverage_krw="340000" if lines else None,
                )
            assert (
                summary(client, actor, case)["medical_paid_krw"]
                == vector("T-12")["expected"]["medical_total_krw"]
            )
            policies, claims = {}, {}
            for fixture in MEDICAL["claims"]:
                policy = new_policy(client, actor)
                policies[fixture["policy_id"]] = policy
                evidence = [
                    expenses[row["expense_id"]]["id"]
                    for row in MEDICAL["claim_expenses"]
                    if row["claim_id"] == fixture["id"]
                ]
                claims[fixture["id"]] = create_metadata(
                    client,
                    actor,
                    "/claims",
                    {
                        "case_id": case["id"],
                        "policy_id": policy["id"],
                        "expense_ids": evidence,
                        "requested_krw": "860000",
                        "decided_krw": "999999",
                        "claim_state": "decided",
                    },
                )
            assert (
                summary(client, actor, case)["medical_paid_krw"]
                == vector("T-13")["expected"]["medical_total_krw"]
            )
            payouts, bodies = {}, {}
            for index, fixture in enumerate(CATALOG["fixtures"]["insurance_receipts"]):
                body = actual(
                    fixture["amount_krw"],
                    allocations=[
                        {
                            "case_id": case["id"],
                            "policy_id": policies[a["policy_id"]]["id"],
                            "claim_id": None,
                            "benefit_type": fixture_benefit(a["benefit_type"]),
                            "amount_krw": a["amount_krw"],
                        }
                        for a in fixture["allocations"]
                    ],
                )
                key = f"synthetic-fixture-payout-{index}"
                reference = money(client, actor, "/payouts", body, key=key)
                assert money(client, actor, "/payouts", body, key=key) == reference
                payouts[fixture["id"]] = read(client, actor, f"/payouts/{reference['id']}")
                bodies[fixture["id"]] = (body, key, reference)
            before = summary(client, actor, case)
            assert before["net_received_krw"] == vector("T-14")["expected"]["received_krw"]
            assert before["net_burden_krw"] == vector("T-14")["expected"]["net_burden_krw"]
            refund_fixture = MEDICAL["refund"]
            expense = expenses[refund_fixture["expense_id"]]
            money(
                client,
                actor,
                f"/medical-expenses/{expense['id']}/refunds",
                actual(refund_fixture["amount_krw"], reason="합성 병원 환불"),
                version=expense["version"],
            )
            after = summary(client, actor, case)
            assert after["net_medical_krw"] == vector("T-15")["expected"]["net_medical_krw"]
            assert after["net_burden_krw"] == vector("T-15")["expected"]["net_burden_krw"]
            returned_fixture = CATALOG["fixtures"]["insurance_return"]
            payout = payouts[returned_fixture["payout_id"]]
            money(
                client,
                actor,
                f"/payouts/{payout['id']}/returns",
                actual(
                    returned_fixture["amount_krw"],
                    original_allocation_id=payout["allocations"][0]["id"],
                    reason="합성 보험사 반환",
                ),
                version=payout["version"],
            )
            final = summary(client, actor, case)
            assert final["net_received_krw"] == vector("T-16")["expected"]["net_received_krw"]
            assert final["net_burden_krw"] == vector("T-16")["expected"]["net_burden_krw"]
            benefits = {row["benefit_type"]: row for row in final["benefits"]}
            assert benefits["fixed"]["net_received_krw"] == "200000"
            assert benefits["reimbursement"]["net_received_krw"] == "550000"
            for body, key, reference in bodies.values():
                assert money(client, actor, "/payouts", body, key=key) == reference
            inpatient = next(r for r in MEDICAL["nodes"] if r["kind"] == "inpatient")
            subtree = read(
                client, actor, f"/cases/{case['id']}/nodes/{nodes[inpatient['id']]['id']}/summary"
            )
            assert (
                subtree["medical_paid_krw"] == "860000" and subtree["net_medical_krw"] == "850000"
            )
            followup = next(r for r in MEDICAL["nodes"] if r["kind"] == "followup")
            assert (
                read(
                    client,
                    actor,
                    f"/cases/{case['id']}/nodes/{nodes[followup['id']]['id']}/summary",
                )["medical_paid_krw"]
                == "50000"
            )
            income = client.get(
                "/api/v1/income/summary?month=2026-01", headers=actor.headers
            ).json()
            assert income["totals"]["insurance_receipts_krw"] == "800000"
            assert income["totals"]["insurance_returns_krw"] == "50000"
            assert read(client, actor, f"/cases/{case['id']}")["version"] == 1
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(MedicalExpense)) == 5
            assert session.scalar(select(func.count()).select_from(MedicalExpenseLine)) == 2
            assert session.scalar(select(func.count()).select_from(ClaimExpense)) == 2
            assert session.scalar(select(func.count()).select_from(InsurancePayout)) == 2
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 9

    def test_t17_negative_burden_and_t18_shared_original_inflow(self, app, actors, db_engine):
        actor = actors[0]
        with TestClient(app) as client:
            case = new_case(client, actor)
            node = new_node(client, actor, case)
            data = vector("T-17")
            new_expense(client, actor, case, node, data["inputs"]["medical_krw"])
            new_payout(
                client,
                actor,
                [
                    allocation(
                        case["id"],
                        data["inputs"]["received_krw"],
                        benefit_type=fixture_benefit(data["inputs"]["benefit_type"]),
                    )
                ],
            )
            assert (
                summary(client, actor, case)["net_burden_krw"] == data["expected"]["net_burden_krw"]
            )
            cases = [new_case(client, actor), new_case(client, actor)]
            data = vector("T-18")
            payout = new_payout(
                client,
                actor,
                [
                    allocation(case["id"], item["amount_krw"])
                    for case, item in zip(cases, data["inputs"]["allocations"], strict=True)
                ],
            )
            for case, expected in zip(cases, data["expected"]["case_totals"], strict=True):
                assert summary(client, actor, case)["net_received_krw"] == expected["amount_krw"]
            listed = client.get("/api/v1/income?month=2026-01", headers=actor.headers).json()[
                "items"
            ]
            assert sum(row["id"] == payout["cash"]["id"] for row in listed) == 1
            assert (
                next(row for row in listed if row["id"] == payout["cash"]["id"])["amount_krw"]
                == data["expected"]["monthly_inflow_krw"]
            )

    def test_t19_mismatch_has_no_partial_sources_or_idempotency_record(
        self, app, actors, db_engine
    ):
        actor = actors[0]
        with TestClient(app) as client:
            cases = [new_case(client, actor), new_case(client, actor)]
            data = vector("T-19")
            response = client.post(
                BASE + "/payouts",
                headers=headers(actor, "synthetic-mismatch"),
                json=actual(
                    data["inputs"]["receipt_krw"],
                    allocations=[
                        allocation(case["id"], item["amount_krw"])
                        for case, item in zip(cases, data["inputs"]["allocations"], strict=True)
                    ],
                ),
            )
            assert response.status_code == 422
        with Session(db_engine) as session:
            for model in (
                CashRecord,
                CashRecordRevision,
                InsurancePayout,
                PayoutAllocation,
                IdempotencyRecord,
            ):
                assert session.scalar(select(func.count()).select_from(model)) == 0

    def test_t22_concurrent_replay_returns_same_original_reference_after_void(
        self, app, actors, db_engine
    ):
        actor = actors[0]
        data = vector("T-22")
        with TestClient(app) as client:
            case = new_case(client, actor)
        body = actual(
            data["inputs"]["payout"]["amount_krw"],
            allocations=[allocation(case["id"], data["inputs"]["payout"]["amount_krw"])],
        )
        barrier = Barrier(2)

        def create_once(_):
            with Session(db_engine) as session:
                barrier.wait(timeout=10)
                return service.create_payout(
                    session,
                    actor.principal,
                    PayoutCreate(**body),
                    data["inputs"]["payout"]["idempotency_key"],
                ).model_dump(mode="json")

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create_once, range(2)))
        assert results[0] == results[1]
        with TestClient(app) as client:
            money(
                client,
                actor,
                f"/payouts/{results[0]['id']}/void",
                {"reason": "합성 오등록"},
                version=1,
                status=200,
            )
            assert (
                money(
                    client, actor, "/payouts", body, key=data["inputs"]["payout"]["idempotency_key"]
                )
                == results[0]
            )
        with Session(db_engine) as session:
            assert (
                session.scalar(select(func.count()).select_from(CashRecord))
                == data["expected"]["cash_record_count"]
            )
            assert (
                session.scalar(select(func.count()).select_from(InsurancePayout))
                == data["expected"]["payout_count"]
            )


@pytest.mark.database
class TestInsuranceEventCorrections:
    @pytest.mark.parametrize("source", ["refund", "return"])
    def test_reversal_correction_keeps_its_original_reason(self, app, actors, source):
        actor = actors[0]
        with TestClient(app) as client:
            case = new_case(client, actor)
            if source == "refund":
                parent = new_expense(client, actor, case, new_node(client, actor, case))
                create_path = f"/medical-expenses/{parent['id']}/refunds"
                collection, body = "/medical-refunds", actual("30", reason="합성 본인부담 환불")
            else:
                parent = new_payout(client, actor, [allocation(case["id"])])
                create_path, collection = f"/payouts/{parent['id']}/returns", "/returns"
                body = actual(
                    "30",
                    original_allocation_id=parent["allocations"][0]["id"],
                    reason="합성 중복 수령 반환",
                )
            first = money(client, actor, create_path, body, version=1)
            replacement = money(
                client,
                actor,
                f"{collection}/{first['id']}/correct",
                body | {"amount_krw": "20", "reason": "합성 금액 오타 정정"},
                version=1,
            )
            corrected = read(client, actor, f"{collection}/{replacement['id']}")
            assert corrected["reason"] == body["reason"]
            voided = read(client, actor, f"{collection}/{first['id']}/history")["items"][0]
            assert voided["state"] == "void" and voided["reason"] == "합성 금액 오타 정정"
            created = read(client, actor, f"{collection}/{replacement['id']}/history")["items"][0]
            assert created["reason"] == "합성 금액 오타 정정"

    @pytest.mark.parametrize("source", ["expense", "refund", "payout", "return"])
    def test_correction_keeps_a_link_that_closed_after_the_original(
        self, app, actors, db_engine, source
    ):
        actor = actors[0]
        account = make_account(db_engine, actor)
        linked = {"account_id": str(account.id), "occurred_on": "2026-01-20"}
        with TestClient(app) as client:
            case = new_case(client, actor)
            node = new_node(client, actor, case)
            if source == "expense":
                collection = "/medical-expenses"
                body = expense_payload(case["id"], node["id"]) | actual(**linked)
                first = money(client, actor, collection, body)
            elif source == "refund":
                parent = new_expense(client, actor, case, node, occurred_on="2026-01-10")
                collection = "/medical-refunds"
                body = actual("30", reason="합성 환불", **linked)
                first = money(
                    client, actor, f"/medical-expenses/{parent['id']}/refunds", body, version=1
                )
            elif source == "payout":
                collection = "/payouts"
                body = actual(allocations=[allocation(case["id"])], **linked)
                first = money(client, actor, collection, body)
            else:
                parent = new_payout(
                    client, actor, [allocation(case["id"])], occurred_on="2026-01-10"
                )
                collection = "/returns"
                body = actual(
                    "30",
                    original_allocation_id=parent["allocations"][0]["id"],
                    reason="합성 반환",
                    **linked,
                )
                first = money(client, actor, f"/payouts/{parent['id']}/returns", body, version=1)
            close_account(db_engine, actor, account, "2026-01-25")
            fixed = body | {"occurred_on": "2026-01-31", "reason": "합성 날짜 정정"}
            replacement = money(
                client, actor, f"{collection}/{first['id']}/correct", fixed, version=1
            )
            corrected = read(client, actor, f"{collection}/{replacement['id']}")
            assert corrected["cash"]["account_id"] == str(account.id)
            assert corrected["cash"]["occurred_on"] == "2026-01-31"
            if source == "expense":
                # A new fact on the closed account still has to be dated on or before its end.
                late = client.post(
                    BASE + collection,
                    headers=headers(actor),
                    json=body | {"occurred_on": "2026-01-26"},
                )
                assert late.status_code == 422
                assert late.json()["error"]["code"] == "ACCOUNT_UNAVAILABLE"
                money(client, actor, collection, body | {"occurred_on": "2026-01-25"})

    def test_claim_evidence_must_be_explicitly_unlinked_before_expense_void(
        self, app, actors, db_engine
    ):
        actor = actors[0]
        with TestClient(app) as client:
            case = new_case(client, actor)
            node = new_node(client, actor, case)
            expense = new_expense(client, actor, case, node)
            policy = new_policy(client, actor)
            claim = create_metadata(
                client,
                actor,
                "/claims",
                {"case_id": case["id"], "policy_id": policy["id"], "expense_ids": [expense["id"]]},
            )
            path = f"/medical-expenses/{expense['id']}"
            rejected = client.post(
                BASE + path + "/void",
                headers=headers(actor, version=1),
                json={"reason": "합성 오등록"},
            )
            assert (
                rejected.status_code == 409
                and rejected.json()["error"]["code"] == "MEDICAL_EXPENSE_IN_CLAIM"
            )
            changed = client.patch(
                f"{BASE}/claims/{claim['id']}",
                headers=headers(actor, version=1),
                json={"expense_ids": [], "claim_state": "withdrawn", "reason": "합성 근거 정정"},
            )
            assert changed.status_code == 200 and changed.json()["expense_ids"] == []
            money(client, actor, path + "/void", {"reason": "합성 오등록"}, version=1, status=200)
            assert read(client, actor, path)["cash"]["state"] == "void"
            history = read(client, actor, f"/claims/{claim['id']}/history")["items"]
            assert history[0]["expense_ids"] == [] and history[1]["expense_ids"] == [expense["id"]]
            assert summary(client, actor, case)["medical_paid_krw"] == "0"
            invalid = client.patch(
                f"{BASE}/claims/{claim['id']}",
                headers=headers(actor, version=2),
                json={"expense_ids": [expense["id"]], "reason": "합성 무효비용 재연결"},
            )
            assert invalid.status_code == 422
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(ClaimExpense)) == 0
            assert session.scalar(select(func.count()).select_from(ClaimRevisionExpense)) == 1
            assert session.scalar(select(func.count()).select_from(InsuranceClaimRevision)) == 2

    @pytest.mark.parametrize("source", ["expense", "payout"])
    def test_atomic_correction_rolls_back_failed_replacement_and_keeps_old_cash_history(
        self, app, actors, db_engine, source
    ):
        actor = actors[0]
        with TestClient(app) as client:
            case = new_case(client, actor)
            node = new_node(client, actor, case)
            if source == "expense":
                original = new_expense(client, actor, case, node)
                base = "/medical-expenses"
                valid = expense_payload(case["id"], node["id"]) | actual(
                    "200", reason="합성 비용 정정"
                )
                invalid = valid | {"node_id": str(uuid4())}
            else:
                original = new_payout(client, actor, [allocation(case["id"])])
                base = "/payouts"
                valid = actual(
                    "200", allocations=[allocation(case["id"], "200")], reason="합성 지급 정정"
                )
                invalid = valid | {"allocations": [allocation(uuid4(), "200")]}
            path = f"{base}/{original['id']}"
            failed = client.post(
                BASE + path + "/correct",
                headers=headers(actor, "synthetic-correction", 1),
                json=invalid,
            )
            assert failed.status_code == 404
            still = read(client, actor, path)
            assert still["cash"]["state"] == "active" and still["version"] == 1
            result = money(
                client, actor, path + "/correct", valid, version=1, key="synthetic-correction"
            )
            assert (
                money(
                    client, actor, path + "/correct", valid, version=1, key="synthetic-correction"
                )
                == result
            )
            replacement = read(client, actor, f"{base}/{result['id']}")
            assert replacement["correction_of_id"] == original["id"]
            assert (
                replacement["cash"]["amount_krw"] == "200"
                and replacement["cash"]["state"] == "active"
            )
            history = read(client, actor, path + "/history")["items"]
            assert [r["state"] for r in history] == ["void", "active"]
            assert all(r["amount_krw"] == "100" for r in history)
            assert history[0]["reason"] == valid["reason"]
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 2
            assert session.scalar(select(func.count()).select_from(CashRecordRevision)) == 3
            assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 2

    @pytest.mark.parametrize("source", ["refund", "return"])
    def test_reversal_correction_void_and_parent_guard(self, app, actors, db_engine, source):
        actor = actors[0]
        with TestClient(app) as client:
            case = new_case(client, actor)
            if source == "refund":
                parent = new_expense(client, actor, case, new_node(client, actor, case))
                parent_path, collection = f"/medical-expenses/{parent['id']}", "/medical-refunds"
                create_path = parent_path + "/refunds"
                body = actual("30", reason="합성 환불")
            else:
                parent = new_payout(client, actor, [allocation(case["id"])])
                parent_path, collection = f"/payouts/{parent['id']}", "/returns"
                create_path = parent_path + "/returns"
                body = actual(
                    "30", original_allocation_id=parent["allocations"][0]["id"], reason="합성 반환"
                )
            first = money(client, actor, create_path, body, version=1)
            rejected = client.post(
                BASE + parent_path + "/void",
                headers=headers(actor, version=2),
                json={"reason": "합성 취소"},
            )
            assert rejected.status_code == 409
            replacement = money(
                client,
                actor,
                f"{collection}/{first['id']}/correct",
                body | {"amount_krw": "20", "reason": "합성 반환금 정정"},
                version=1,
            )
            corrected = read(client, actor, f"{collection}/{replacement['id']}")
            assert (
                corrected["correction_of_id"] == first["id"]
                and corrected["cash"]["amount_krw"] == "20"
            )
            assert read(client, actor, f"{collection}/{first['id']}")["cash"]["state"] == "void"
            totals = summary(client, actor, case)
            assert (
                totals["medical_refunded_krw" if source == "refund" else "insurance_returned_krw"]
                == "20"
            )
            money(
                client,
                actor,
                f"{collection}/{replacement['id']}/void",
                {"reason": "합성 전체 오등록"},
                version=1,
                status=200,
            )
            current = read(client, actor, parent_path)
            money(
                client,
                actor,
                parent_path + "/void",
                {"reason": "합성 원본 오등록"},
                version=current["version"],
                status=200,
            )
            assert summary(client, actor, case)["net_burden_krw"] == "0"
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 3

    @pytest.mark.parametrize("status", ["ended", "lapsed"])
    def test_inactive_policy_accepts_late_claim_and_direct_allocation(self, app, actors, status):
        actor, _, foreign = actors
        with TestClient(app) as client:
            case, policy = new_case(client, actor), new_policy(client, actor)
            changed = client.patch(
                f"{BASE}/policies/{policy['id']}",
                headers=headers(actor, version=1),
                json={"status": status},
            )
            assert changed.status_code == 200
            claim = create_metadata(
                client, actor, "/claims", {"case_id": case["id"], "policy_id": policy["id"]}
            )
            assert claim["policy_id"] == policy["id"]
            direct = new_payout(client, actor, [allocation(case["id"], policy_id=policy["id"])])
            assert direct["allocations"][0]["policy_id"] == policy["id"]
            assert direct["allocations"][0]["claim_id"] is None
            loose = new_payout(client, actor, [allocation(case["id"])])
            linked = client.patch(
                f"{BASE}/payout-allocations/{loose['allocations'][0]['id']}",
                headers=headers(actor, version=1),
                json={"policy_id": policy["id"], "reason": "합성 종료 계약 연결"},
            )
            assert linked.status_code == 200
            other = new_policy(client, foreign)
            assert (
                client.post(
                    BASE + "/claims",
                    headers=actor.headers,
                    json={"case_id": case["id"], "policy_id": other["id"]},
                ).status_code
                == 404
            )
            assert (
                client.post(
                    BASE + "/payouts",
                    headers=headers(actor),
                    json=actual(allocations=[allocation(case["id"], policy_id=other["id"])]),
                ).status_code
                == 404
            )

    def test_direct_receipt_later_claim_link_has_history_and_no_second_cash(
        self, app, actors, db_engine
    ):
        actor = actors[0]
        with TestClient(app) as client:
            case, policy = new_case(client, actor), new_policy(client, actor)
            claim = create_metadata(
                client, actor, "/claims", {"case_id": case["id"], "policy_id": policy["id"]}
            )
            payout = new_payout(client, actor, [allocation(case["id"], benefit_type="fixed")])
            allocated = payout["allocations"][0]
            ended = client.patch(
                f"{BASE}/policies/{policy['id']}",
                headers=headers(actor, version=1),
                json={"status": "ended"},
            )
            assert ended.status_code == 200
            path = f"{BASE}/payout-allocations/{allocated['id']}"
            body = {
                "policy_id": policy["id"],
                "claim_id": claim["id"],
                "reason": "합성 접수번호 확인",
            }
            first = client.patch(path, headers=headers(actor, "synthetic-later-link", 1), json=body)
            assert first.status_code == 200 and first.json()["version"] == 2
            assert (
                client.patch(
                    path, headers=headers(actor, "synthetic-later-link", 1), json=body
                ).json()
                == first.json()
            )
            history = read(client, actor, f"/payout-allocations/{allocated['id']}/history")["items"]
            assert history[0]["claim_id"] == claim["id"] and history[1]["claim_id"] is None
            late = new_payout(
                client,
                actor,
                [allocation(case["id"], policy_id=policy["id"], claim_id=claim["id"])],
            )
            assert late["cash"]["state"] == "active"
            assert summary(client, actor, case)["insurance_received_krw"] == "200"
            assert (
                client.patch(
                    path,
                    headers=headers(actor, version=2),
                    json={"amount_krw": "999", "reason": "합성"},
                ).status_code
                == 422
            )
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 2
            assert session.scalar(select(func.count()).select_from(PayoutAllocationRevision)) == 3

    def test_prescription_expense_and_later_kind_change_remain_forbidden(self, app, actors):
        actor = actors[0]
        with TestClient(app) as client:
            case = new_case(client, actor)
            prescription = new_node(client, actor, case, kind="prescription")
            rejected = client.post(
                BASE + "/medical-expenses",
                headers=headers(actor),
                json=expense_payload(case["id"], prescription["id"]),
            )
            assert rejected.status_code == 422
            node = new_node(client, actor, case)
            expense = new_expense(client, actor, case, node)
            node_path = f"{BASE}/cases/{case['id']}/nodes/{node['id']}"
            assert (
                client.patch(
                    node_path, headers=headers(actor, version=1), json={"kind": "prescription"}
                ).status_code
                == 409
            )
            assert client.delete(node_path, headers=headers(actor, version=1)).status_code == 409
            money(
                client,
                actor,
                f"/medical-expenses/{expense['id']}/void",
                {"reason": "합성 오등록"},
                version=1,
                status=200,
            )
            assert (
                client.patch(
                    node_path, headers=headers(actor, version=1), json={"kind": "prescription"}
                ).status_code
                == 409
            )

    def test_payout_filters_must_match_one_allocation(self, app, actors):
        actor = actors[0]
        with TestClient(app) as client:
            cases, policies = (
                [new_case(client, actor) for _ in range(2)],
                [new_policy(client, actor) for _ in range(2)],
            )
            claims = [
                create_metadata(
                    client, actor, "/claims", {"case_id": case["id"], "policy_id": policy["id"]}
                )
                for case, policy in zip(cases, policies, strict=True)
            ]
            payout = new_payout(
                client,
                actor,
                [
                    allocation(
                        cases[i]["id"], policy_id=policies[i]["id"], claim_id=claims[i]["id"]
                    )
                    for i in range(2)
                ],
            )
            matching = read(
                client,
                actor,
                f"/payouts?case_id={cases[0]['id']}&policy_id={policies[0]['id']}&claim_id={claims[0]['id']}",
            )
            assert [row["id"] for row in matching["items"]] == [payout["id"]]
            for filters in (
                f"case_id={cases[0]['id']}&policy_id={policies[1]['id']}",
                f"policy_id={policies[0]['id']}&claim_id={claims[1]['id']}",
            ):
                assert read(client, actor, "/payouts?" + filters)["items"] == []


@pytest.mark.database
class TestInsuranceEventBoundaries:
    def test_partial_refund_total_cap_exact_limit_and_immutable_replay(
        self, app, actors, db_engine
    ):
        actor = actors[0]
        with TestClient(app) as client:
            case = new_case(client, actor)
            expense = new_expense(client, actor, case, new_node(client, actor, case))
            path = f"/medical-expenses/{expense['id']}"
            body = actual("60", reason="합성 부분 환불")
            first = money(
                client, actor, path + "/refunds", body, version=1, key="synthetic-refund-once"
            )
            assert (
                money(
                    client, actor, path + "/refunds", body, version=1, key="synthetic-refund-once"
                )
                == first
            )
            too_much = client.post(
                BASE + path + "/refunds", headers=headers(actor, version=2), json=body
            )
            assert (
                too_much.status_code == 409
                and too_much.json()["error"]["code"] == "RETURN_EXCEEDS_ORIGINAL"
            )
            money(
                client, actor, path + "/refunds", actual("40", reason="합성 잔액 환불"), version=2
            )
            assert summary(client, actor, case)["net_medical_krw"] == "0"
            assert (
                client.post(
                    BASE + path + "/refunds",
                    headers=headers(actor, version=3),
                    json=actual("1", reason="합성 초과"),
                ).status_code
                == 409
            )
            assert (
                money(
                    client, actor, path + "/refunds", body, version=1, key="synthetic-refund-once"
                )
                == first
            )
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(MedicalRefund)) == 2
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 3

    def test_return_allocation_cap_and_original_cap_and_corrected_allocation(self, app, actors):
        actor = actors[0]
        with TestClient(app) as client:
            a, b = new_case(client, actor), new_case(client, actor)
            payout = new_payout(
                client, actor, [allocation(a["id"], "60"), allocation(b["id"], "40")]
            )
            allocations = {row["case_id"]: row for row in payout["allocations"]}
            path = f"/payouts/{payout['id']}"
            too_much = client.post(
                BASE + path + "/returns",
                headers=headers(actor, version=1),
                json=actual(
                    "61", original_allocation_id=allocations[a["id"]]["id"], reason="합성 배분 초과"
                ),
            )
            assert (
                too_much.status_code == 409
                and too_much.json()["error"]["code"] == "RETURN_EXCEEDS_ALLOCATION"
            )
            first = money(
                client,
                actor,
                path + "/returns",
                actual("30", original_allocation_id=allocations[a["id"]]["id"], reason="합성 반환"),
                version=1,
            )
            money(
                client,
                actor,
                f"/returns/{first['id']}/correct",
                actual(
                    "20", original_allocation_id=allocations[b["id"]]["id"], reason="합성 배분 정정"
                ),
                version=1,
            )
            assert summary(client, actor, a)["net_received_krw"] == "60"
            assert summary(client, actor, b)["net_received_krw"] == "20"
            current = read(client, actor, path)
            money(
                client,
                actor,
                path + "/returns",
                actual(
                    "60", original_allocation_id=allocations[a["id"]]["id"], reason="합성 잔액 반환"
                ),
                version=current["version"],
            )
            current = read(client, actor, path)
            money(
                client,
                actor,
                path + "/returns",
                actual(
                    "20", original_allocation_id=allocations[b["id"]]["id"], reason="합성 잔액 반환"
                ),
                version=current["version"],
            )
            assert (
                summary(client, actor, a)["net_received_krw"]
                == summary(client, actor, b)["net_received_krw"]
                == "0"
            )
            current = read(client, actor, path)
            assert (
                client.post(
                    BASE + path + "/returns",
                    headers=headers(actor, version=current["version"]),
                    json=actual(
                        "1", original_allocation_id=allocations[a["id"]]["id"], reason="합성 초과"
                    ),
                ).status_code
                == 409
            )

    @pytest.mark.parametrize("kind", ["refund", "return"])
    def test_concurrent_reversal_requests_cannot_overrun_source(self, app, actors, db_engine, kind):
        actor, spouse, _ = actors
        with TestClient(app) as client:
            case = new_case(client, actor)
            if kind == "refund":
                parent = new_expense(client, actor, case, new_node(client, actor, case))
                payload = RefundCreate(**actual("70", reason="합성 동시 환불"))
                create_source = service.create_refund
            else:
                parent = new_payout(client, actor, [allocation(case["id"])])
                payload = ReturnCreate(
                    **actual(
                        "70",
                        original_allocation_id=parent["allocations"][0]["id"],
                        reason="합성 동시 반환",
                    )
                )
                create_source = service.create_return
        barrier = Barrier(2)

        def attempt(who):
            with Session(db_engine) as session:
                barrier.wait(timeout=10)
                try:
                    create_source(
                        session, who.principal, UUID(parent["id"]), payload, '"1"', str(uuid4())
                    )
                    return "created"
                except DomainError as error:
                    return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(attempt, (actor, spouse))) == ["VERSION_CONFLICT", "created"]
        with TestClient(app) as client:
            total = summary(client, actor, case)
            assert (
                total["medical_refunded_krw" if kind == "refund" else "insurance_returned_krw"]
                == "70"
            )

    def test_foreign_scope_and_cross_case_links_leave_no_partial_money(
        self, app, actors, db_engine
    ):
        actor, _, foreign = actors
        with TestClient(app) as client:
            case, other = new_case(client, actor), new_case(client, actor)
            node, other_node = new_node(client, actor, case), new_node(client, actor, other)
            foreign_case = new_case(client, foreign)
            foreign_node = new_node(client, foreign, foreign_case)
            alien = new_expense(client, foreign, foreign_case, foreign_node)
            for path in (
                f"/medical-expenses/{alien['id']}",
                f"/medical-expenses/{alien['id']}/history",
                f"/medical-expenses/{alien['id']}/refunds",
                f"/cases/{foreign_case['id']}/summary",
            ):
                assert client.get(BASE + path, headers=actor.headers).status_code == 404
            assert client.get(BASE + f"/medical-expenses/{alien['id']}").status_code == 401
            for selected in (other_node, foreign_node):
                assert (
                    client.post(
                        BASE + "/medical-expenses",
                        headers=headers(actor),
                        json=expense_payload(case["id"], selected["id"]),
                    ).status_code
                    == 404
                )
            expense = new_expense(client, actor, case, node)
            policy, foreign_policy = new_policy(client, actor), new_policy(client, foreign)
            for body in (
                {"case_id": other["id"], "policy_id": policy["id"], "expense_ids": [expense["id"]]},
                {"case_id": case["id"], "policy_id": foreign_policy["id"], "expense_ids": []},
            ):
                assert (
                    client.post(BASE + "/claims", headers=actor.headers, json=body).status_code
                    == 404
                )
            claim = create_metadata(
                client, actor, "/claims", {"case_id": case["id"], "policy_id": policy["id"]}
            )
            mismatched = client.post(
                BASE + "/payouts",
                headers=headers(actor),
                json=actual(
                    allocations=[
                        allocation(other["id"], policy_id=policy["id"], claim_id=claim["id"])
                    ]
                ),
            )
            assert mismatched.status_code == 422
            payout = new_payout(client, actor, [allocation(case["id"])])
            unrelated = new_payout(client, actor, [allocation(other["id"])])
            assert (
                client.post(
                    f"{BASE}/payouts/{payout['id']}/returns",
                    headers=headers(actor, version=1),
                    json=actual(
                        "10",
                        original_allocation_id=unrelated["allocations"][0]["id"],
                        reason="합성 다른 지급",
                    ),
                ).status_code
                == 404
            )
            for path in (
                f"/payouts/{payout['id']}",
                f"/payouts/{payout['id']}/returns",
                f"/payout-allocations/{payout['allocations'][0]['id']}",
                f"/claims/{claim['id']}/history",
            ):
                assert client.get(BASE + path, headers=foreign.headers).status_code == 404
            assert (
                client.get(
                    BASE + f"/payouts?policy_id={foreign_policy['id']}", headers=actor.headers
                ).status_code
                == 404
            )
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(CashRecord)
                    .where(CashRecord.household_id == actor.household_id)
                )
                == 3
            )

    @pytest.mark.parametrize("collection", ["medical-expenses", "payouts", "claims"])
    def test_list_queries_are_batched_and_cursors_do_not_duplicate(
        self, app, actors, db_engine, collection
    ):
        actor = actors[0]
        with TestClient(app) as client:
            case, policy = new_case(client, actor), new_policy(client, actor)
            node = new_node(client, actor, case)
            counts = []
            for additional in (1, 3):
                for _ in range(additional):
                    if collection == "medical-expenses":
                        new_expense(
                            client,
                            actor,
                            case,
                            node,
                            lines=[{"label": "합성 분해", "amount_krw": "100"}],
                        )
                    elif collection == "payouts":
                        new_payout(client, actor, [allocation(case["id"])])
                    else:
                        create_metadata(
                            client,
                            actor,
                            "/claims",
                            {"case_id": case["id"], "policy_id": policy["id"]},
                        )
                queries = []

                def capture(
                    conn, cursor, statement, parameters, context, executemany, queries=queries
                ):
                    if statement.startswith("SELECT"):
                        queries.append(statement)

                event.listen(db_engine, "before_cursor_execute", capture)
                try:
                    result = read(client, actor, f"/{collection}")
                finally:
                    event.remove(db_engine, "before_cursor_execute", capture)
                counts.append(len(queries))
            assert counts[0] == counts[1]
            first = read(client, actor, f"/{collection}?limit=2")
            second = read(client, actor, f"/{collection}?limit=2&cursor={first['next_cursor']}")
            assert (
                len({r["id"] for r in first["items"] + second["items"]})
                == len(result["items"])
                == 4
            )

    def test_income_projection_is_read_only_and_cash_helper_rejects_manual_income(
        self, app, actors, db_engine
    ):
        actor = actors[0]
        with TestClient(app) as client:
            case = new_case(client, actor)
            payout = new_payout(client, actor, [allocation(case["id"])])
            cash_id = payout["cash"]["id"]
            projected = client.get(f"/api/v1/income/{cash_id}", headers=actor.headers).json()
            assert projected["editable"] is projected["voidable"] is False
            assert (
                client.patch(
                    f"/api/v1/income/{cash_id}",
                    headers=headers(actor, version=1),
                    json={"amount_krw": "200", "reason": "합성 금지"},
                ).status_code
                == 409
            )
            assert (
                client.post(
                    f"/api/v1/income/{cash_id}/void",
                    headers=headers(actor, version=1),
                    json={"reason": "합성 금지"},
                ).status_code
                == 409
            )
            income_sources = []
            for kind in ("salary", "bonus", "other_income"):
                created = client.post(
                    "/api/v1/income", headers=headers(actor), json=income_payload(actor, kind=kind)
                )
                assert created.status_code == 201
                income_sources.append(created.json())
            returned = client.post(
                f"/api/v1/income/{income_sources[0]['id']}/returns",
                headers=headers(actor, version=1),
                json={
                    "amount_krw": "10",
                    "period_month": "2026-01",
                    "date_precision": "day",
                    "occurred_on": "2026-01-31",
                    "reason": "합성 반환",
                },
            )
            assert returned.status_code == 201
            income_sources.append(returned.json())
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"], end="2026-01-31")
            paid = settle(
                client, actor, obligation_for(client, actor, "2026-01"), amount="100"
            ).json()
            canceled = client.post(
                f"/api/v1/settlements/{paid['id']}/void",
                headers=headers(actor, version=1),
                json={"reason": "합성 납부 오등록"},
            )
            assert canceled.status_code == 200 and canceled.json()["cash"]["state"] == "void"
        for row in income_sources:
            with Session(db_engine) as session:
                with pytest.raises(DomainError) as rejected:
                    cash.prepare_void_cash_record(
                        session,
                        actor.principal,
                        UUID(row["id"]),
                        kind=row["kind"],
                        reason="합성 차단",
                    )
                assert rejected.value.code == "SOURCE_DOMAIN_REQUIRED"
                session.rollback()
                assert session.get(CashRecord, UUID(row["id"])).state == "active"

    def test_expense_and_insurance_receipts_do_not_change_account_month_snapshot(
        self, app, actors, db_engine
    ):
        actor = actors[0]
        account = make_account(db_engine, actor)
        with Session(db_engine) as session:
            draft = month_service.create_draft(
                session,
                actor.principal,
                "2026-01",
                MonthDraft(copy_previous=False),
                "synthetic-medical-snapshot",
            )
            month = month_service.get_month(session, actor.principal, "2026-01")
            value = next(row for row in month.values if row.asset_id == account.asset_id)
            month_service.update_value(
                session,
                actor.principal,
                "2026-01",
                account.asset_id,
                MonthValueUpdate(
                    revision_id=draft.revision_id,
                    value_id=value.id,
                    input_amount_krw="5000000",
                    as_of_date="2026-01-31",
                ),
                f'"{value.version}"',
            )
            before = month_service.get_month(session, actor.principal, "2026-01").model_dump(
                mode="json"
            )
        with TestClient(app) as client:
            case = new_case(client, actor)
            expense = new_expense(
                client, actor, case, new_node(client, actor, case), account_id=str(account.id)
            )
            payout = new_payout(client, actor, [allocation(case["id"])], account_id=str(account.id))
            money(
                client,
                actor,
                f"/medical-expenses/{expense['id']}/refunds",
                actual("10", account_id=str(account.id), reason="합성 환불"),
                version=1,
            )
            money(
                client,
                actor,
                f"/payouts/{payout['id']}/returns",
                actual(
                    "10",
                    account_id=str(account.id),
                    original_allocation_id=payout["allocations"][0]["id"],
                    reason="합성 반환",
                ),
                version=1,
            )
        with Session(db_engine) as session:
            assert (
                month_service.get_month(session, actor.principal, "2026-01").model_dump(mode="json")
                == before
            )
