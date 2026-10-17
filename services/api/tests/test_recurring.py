"""Synthetic recurrence, settlement, replay and household boundary regressions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from test_accounts import make_actor
from test_income import headers, make_account

from sallimbook.cashflow import recurring_service as service
from sallimbook.cashflow.models import CashRecord, CashRecordRevision
from sallimbook.cashflow.recurring_models import (
    FixedSettlement,
    ObligationGeneration,
    ObligationGenerationItem,
    ObligationRevision,
    RecurringRule,
    RecurringRuleVersion,
    ScheduledObligation,
)
from sallimbook.cashflow.recurring_router import router
from sallimbook.cashflow.recurring_schemas import GenerateObligations, RuleCreate, SettlementCreate
from sallimbook.cashflow.scheduling import occurrence_dates, payment_breakdown, settlement_totals
from sallimbook.config import Settings
from sallimbook.core.audit import AuditEvent
from sallimbook.core.http import install_http_contract
from sallimbook.core.idempotency import IdempotencyRecord
from sallimbook.core.types import MAX_KRW


def rule_payload(**overrides):
    return dict(
        title="합성 정기 비용",
        category="subscription",
        amount_mode="fixed",
        expected_amount_krw="33000",
        economic_type="expense",
        frequency="monthly",
        anchor_date="2026-01-31",
        effective_from="2026-01-01",
        **overrides,
    )


def test_t10_original_month_end_anchor_and_leap_annual_dates():
    assert occurrence_dates(
        date(2025, 1, 31), date(2025, 2, 1), date(2025, 3, 31), frequency="monthly"
    ) == (date(2025, 2, 28), date(2025, 3, 31))
    assert occurrence_dates(
        date(2024, 2, 29), date(2025, 1, 1), date(2028, 12, 31), frequency="annual"
    ) == (date(2025, 2, 28), date(2026, 2, 28), date(2027, 2, 28), date(2028, 2, 29))
    assert occurrence_dates(
        date(2026, 1, 31),
        date(2026, 2, 1),
        date(2026, 4, 30),
        frequency="monthly",
        interval_count=2,
    ) == (date(2026, 3, 31),)
    assert occurrence_dates(
        date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 15), frequency="days", interval_count=7
    ) == (date(2026, 1, 8), date(2026, 1, 15))


@pytest.mark.parametrize(
    "frequency,interval", [("weekly", 1), ("days", 0), ("monthly", True), ("annual", -1)]
)
def test_bad_recurrence_rejected(frequency, interval):
    with pytest.raises(ValueError):
        occurrence_dates(
            date(2026, 1, 1),
            date(2026, 1, 1),
            date(2026, 2, 1),
            frequency=frequency,
            interval_count=interval,
        )


def test_t09_t11_exact_payment_breakdown_and_expected_actual_separation():
    loan = payment_breakdown(
        1_000_000, economic_type="loan", principal_krw=700_000, interest_krw=300_000
    )
    assert (loan.cash_payment_krw, loan.consumption_krw, loan.principal_krw) == (
        1_000_000,
        300_000,
        700_000,
    )
    transfer = payment_breakdown(100, economic_type="asset_transfer")
    assert transfer.asset_transfer_krw == 100 and transfer.consumption_krw == 0
    totals = settlement_totals(33_000, [30_000, 5_000])
    assert (totals.expected_krw, totals.actual_krw, totals.difference_krw) == (
        33_000,
        35_000,
        2_000,
    )
    assert settlement_totals(None, [10]).difference_krw is None
    assert settlement_totals(0, []).expected_krw == 0


@pytest.mark.parametrize("amount", [True, 1.5, Decimal("1.5"), Decimal("NaN"), -1, MAX_KRW + 1])
def test_payment_arithmetic_rejects_inexact_or_invalid_money(amount):
    with pytest.raises(ValueError):
        payment_breakdown(amount, economic_type="expense")


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount_mode": "fixed", "expected_amount_krw": None},
        {"account_id": str(uuid4()), "card_id": str(uuid4())},
        {"expected_amount_krw": 100},
        {"interval_count": True},
        {"currency_reference": "USD"},
        {"foreign_amount_reference": "1.5"},
        {"currency_reference": "USD", "foreign_amount_reference": 1.5},
        {"household_id": str(uuid4())},
        {"title": " "},
    ],
)
def test_rule_schema_rejects_missing_or_ambiguous_terms(overrides):
    with pytest.raises(ValidationError):
        RuleCreate(**(rule_payload() | overrides))


def test_optional_foreign_reference_never_becomes_exchange_rate_or_expected_amount():
    rule = RuleCreate(
        **(
            rule_payload()
            | {
                "amount_mode": "variable",
                "expected_amount_krw": None,
                "currency_reference": "USD",
                "foreign_amount_reference": "9.99",
            }
        )
    )
    assert rule.expected_amount_krw is None and rule.foreign_amount_reference == "9.99"
    with pytest.raises(ValidationError):
        GenerateObligations(start_date="2026-01-01", end_date="2027-01-02")
    with pytest.raises(ValidationError):
        SettlementCreate(amount_krw="0", occurred_on="2026-01-01")


@pytest.fixture
def actors(db_engine):
    first = make_actor(db_engine)
    return first, make_actor(db_engine, first.household_id), make_actor(db_engine)


@pytest.fixture
def recurring_app(db_engine, monkeypatch):
    monkeypatch.setattr(service, "utcnow", lambda: datetime(2026, 2, 1, 1, tzinfo=UTC))
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(app)
    app.include_router(router)
    return app


def post_rule(client, actor, **overrides):
    result = client.post(
        "/api/v1/recurring-rules", headers=headers(actor), json=rule_payload() | overrides
    )
    assert result.status_code == 201, result.text
    return result.json()


def generate(client, actor, rule_id, key=None, start="2026-01-01", end="2026-03-31"):
    result = client.post(
        "/api/v1/obligations/generate",
        headers=headers(actor, key),
        json={"start_date": start, "end_date": end, "rule_id": rule_id},
    )
    assert result.status_code == 201, result.text
    return result.json()


def obligation_for(client, actor, month):
    result = client.get(f"/api/v1/obligations?month={month}", headers=actor.headers)
    assert result.status_code == 200, result.text
    return result.json()["items"][0]


def settle(client, actor, obligation, *, amount="35000", key=None, **extra):
    result = client.post(
        f"/api/v1/obligations/{obligation['id']}/settlements",
        headers=headers(actor, key, obligation["version"]),
        json={"amount_krw": amount, "occurred_on": "2026-01-31", **extra},
    )
    assert result.status_code == 201, result.text
    return result


@pytest.mark.database
class TestRecurringDatabase:
    def test_t10_repeat_generation_and_failure_catchup(self, recurring_app, actors, db_engine):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            original = generate(client, actor, rule["id"], "synthetic-generate", end="2026-02-28")
            assert (
                generate(client, actor, rule["id"], "synthetic-generate", end="2026-02-28")
                == original
            )
            generate(client, actor, rule["id"])
            feb = obligation_for(client, actor, "2026-02")
            mar = obligation_for(client, actor, "2026-03")
            assert feb["nominal_date"] == "2026-02-28" and mar["nominal_date"] == "2026-03-31"
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(ScheduledObligation)) == 3
            assert session.scalar(select(func.count()).select_from(ObligationRevision)) == 3

    def test_t11_partial_actual_difference_and_void_replay(self, recurring_app, actors, db_engine):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            original_generation = generate(client, actor, rule["id"], "synthetic-replay")
            obligation = obligation_for(client, actor, "2026-01")
            first = settle(client, actor, obligation, amount="30000", key="synthetic-first").json()
            partial = obligation_for(client, actor, "2026-01")
            assert partial["status"] == "partial" and partial["actual_amount_krw"] == "30000"
            second = settle(client, actor, partial, amount="5000").json()
            paid = obligation_for(client, actor, "2026-01")
            assert paid["status"] == "paid" and paid["actual_amount_krw"] == "35000"
            assert paid["expected_amount_krw"] == "33000" and paid["difference_krw"] == "2000"
            summary = client.get(
                "/api/v1/obligations/summary?month=2026-01", headers=actor.headers
            ).json()
            assert summary["actual_amount_krw"] == "35000" and summary["consumption_krw"] == "35000"
            void = client.post(
                f"/api/v1/settlements/{second['id']}/void",
                headers=headers(actor, "synthetic-void", 1),
                json={"reason": "합성 취소"},
            )
            assert void.status_code == 200 and void.json()["cash"]["state"] == "void"
            assert obligation_for(client, actor, "2026-01")["status"] == "partial"
            assert (
                settle(client, actor, obligation, amount="30000", key="synthetic-first").json()
                == first
            )
            assert generate(client, actor, rule["id"], "synthetic-replay") == original_generation
            assert (
                client.post(
                    f"/api/v1/settlements/{second['id']}/void",
                    headers=headers(actor, "synthetic-void", 1),
                    json={"reason": "합성 취소"},
                ).json()
                == void.json()
            )
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 2
            assert session.scalar(select(func.count()).select_from(CashRecordRevision)) == 3

    @pytest.mark.parametrize(
        "economic,amount,extra,consumption,principal,transfer",
        [
            (
                "loan",
                "1000000",
                {"principal_krw": "700000", "interest_krw": "300000"},
                "300000",
                "700000",
                "0",
            ),
            ("asset_transfer", "100000", {}, "0", "0", "100000"),
        ],
    )
    def test_t09_loan_and_pension_separate_actual_consumption(
        self, recurring_app, actors, economic, amount, extra, consumption, principal, transfer
    ):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor, economic_type=economic)
            generate(client, actor, rule["id"])
            payment = settle(
                client, actor, obligation_for(client, actor, "2026-01"), amount=amount, **extra
            ).json()
            assert payment["cash"]["amount_krw"] == amount
            assert payment["consumption_krw"] == consumption
            assert (
                payment["principal_krw"] == principal and payment["asset_transfer_krw"] == transfer
            )

    def test_amount_change_only_refreshes_future_unpaid_unmodified(
        self, recurring_app, actors, db_engine
    ):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"], end="2026-05-31")
            past = obligation_for(client, actor, "2026-01")
            feb = obligation_for(client, actor, "2026-02")
            march = obligation_for(client, actor, "2026-03")
            april = obligation_for(client, actor, "2026-04")
            settle(client, actor, feb, amount="10")
            assert (
                client.patch(
                    f"/api/v1/obligations/{march['id']}",
                    headers=headers(actor, version=1),
                    json={"scheduled_date": "2026-03-30", "reason": "합성 은행 이연"},
                ).status_code
                == 200
            )
            changed = client.patch(
                f"/api/v1/recurring-rules/{rule['id']}",
                headers=headers(actor, version=1),
                json=rule_payload()
                | {
                    "expected_amount_krw": "50000",
                    "effective_from": "2026-02-01",
                    "reason": "합성 요금 변경",
                },
            )
            assert changed.status_code == 200, changed.text
            assert obligation_for(client, actor, "2026-01") == past
            assert obligation_for(client, actor, "2026-02")["expected_amount_krw"] == "33000"
            assert obligation_for(client, actor, "2026-03")["scheduled_date"] == "2026-03-30"
            assert obligation_for(client, actor, "2026-03")["expected_amount_krw"] == "33000"
            refreshed = obligation_for(client, actor, "2026-04")
            assert refreshed["expected_amount_krw"] == "50000" and refreshed["version"] == 2
            history = client.get(
                f"/api/v1/obligations/{april['id']}/history", headers=actor.headers
            ).json()
            assert [item["expected_amount_krw"] for item in history["items"]] == ["50000", "33000"]
        with Session(db_engine) as session:
            versions = list(
                session.scalars(
                    select(RecurringRuleVersion).order_by(RecurringRuleVersion.effective_from)
                )
            )
            assert [int(row.expected_amount_krw) for row in versions] == [33000, 50000]
            assert versions[0].effective_until == date(2026, 2, 1)

    def test_schedule_change_supersedes_old_future_occurrence(self, recurring_app, actors):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"])
            old = obligation_for(client, actor, "2026-02")
            result = client.patch(
                f"/api/v1/recurring-rules/{rule['id']}",
                headers=headers(actor, version=1),
                json=rule_payload()
                | {
                    "anchor_date": "2026-02-15",
                    "effective_from": "2026-02-01",
                    "reason": "합성 일정 변경",
                },
            )
            assert result.status_code == 200
            rows = client.get("/api/v1/obligations?month=2026-02", headers=actor.headers).json()[
                "items"
            ]
            assert {(r["nominal_date"], r["status"]) for r in rows} == {
                ("2026-02-28", "superseded"),
                ("2026-02-15", "unpaid"),
            }
            assert (
                client.post(
                    f"/api/v1/obligations/{old['id']}/settlements",
                    headers=headers(actor, version=2),
                    json={"amount_krw": "10", "occurred_on": "2026-01-31"},
                ).status_code
                == 409
            )

    def test_variable_unknown_zero_skip_complete_reopen(self, recurring_app, actors):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor, amount_mode="variable", expected_amount_krw=None)
            generate(client, actor, rule["id"])
            row = obligation_for(client, actor, "2026-01")
            assert (
                row["expected_amount_krw"] is None
                and row["difference_krw"] is None
                and row["status"] == "unpaid"
            )
            path = f"/api/v1/obligations/{row['id']}"
            assert (
                client.post(
                    path + "/complete", headers=headers(actor, version=1), json={"reason": "합성"}
                ).status_code
                == 409
            )
            assert (
                client.post(
                    path + "/skip", headers=headers(actor, version=1), json={"reason": "합성"}
                ).status_code
                == 200
            )
            assert obligation_for(client, actor, "2026-01")["status"] == "skipped"
            assert (
                client.post(
                    path + "/unskip", headers=headers(actor, version=2), json={"reason": "합성"}
                ).status_code
                == 200
            )
            payment = settle(
                client, actor, obligation_for(client, actor, "2026-01"), amount="10"
            ).json()
            assert obligation_for(client, actor, "2026-01")["status"] == "partial"
            assert (
                client.post(
                    path + "/complete", headers=headers(actor, version=4), json={"reason": "합성"}
                ).status_code
                == 200
            )
            assert obligation_for(client, actor, "2026-01")["status"] == "paid"
            assert (
                client.post(
                    path + "/reopen", headers=headers(actor, version=5), json={"reason": "합성"}
                ).status_code
                == 200
            )
            assert obligation_for(client, actor, "2026-01")["status"] == "partial"
            assert (
                client.post(
                    f"/api/v1/settlements/{payment['id']}/void",
                    headers=headers(actor, version=1),
                    json={"reason": "합성"},
                ).status_code
                == 200
            )
            assert obligation_for(client, actor, "2026-01")["status"] == "unpaid"

    def test_end_preserves_paid_and_past_but_supersedes_future_unpaid(self, recurring_app, actors):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"])
            settle(client, actor, obligation_for(client, actor, "2026-02"), amount="10")
            result = client.post(
                f"/api/v1/recurring-rules/{rule['id']}/end",
                headers=headers(actor, version=1),
                json={"effective_on": "2026-02-01", "reason": "합성 해지"},
            )
            assert result.status_code == 200
            assert obligation_for(client, actor, "2026-01")["status"] == "unpaid"
            assert obligation_for(client, actor, "2026-02")["status"] == "partial"
            assert obligation_for(client, actor, "2026-03")["status"] == "superseded"
            generate(client, actor, rule["id"], end="2026-04-30")
            assert (
                client.get("/api/v1/obligations?month=2026-04", headers=actor.headers).json()[
                    "items"
                ]
                == []
            )

    def test_overlapping_and_past_version_changes_fail_without_partial_write(
        self, recurring_app, actors, db_engine
    ):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            for start in ("2026-01-01", "2026-01-15"):
                result = client.patch(
                    f"/api/v1/recurring-rules/{rule['id']}",
                    headers=headers(actor, version=1),
                    json=rule_payload() | {"effective_from": start, "reason": "합성"},
                )
                assert result.status_code == 409
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(RecurringRuleVersion)) == 1
            assert session.get(RecurringRule, UUID(rule["id"])).version == 1

    def test_foreign_household_all_read_write_paths_and_methods_are_rejected(
        self, recurring_app, actors, db_engine
    ):
        actor, _, foreign = actors
        foreign_account = make_account(db_engine, foreign)
        with TestClient(recurring_app) as client:
            rule = post_rule(client, foreign)
            batch = generate(client, foreign, rule["id"])
            obligation = obligation_for(client, foreign, "2026-01")
            payment = settle(client, foreign, obligation).json()
            for path in (
                f"recurring-rules/{rule['id']}",
                f"obligations/{obligation['id']}",
                f"obligations/{obligation['id']}/history",
                f"obligations/{obligation['id']}/settlements",
            ):
                assert client.get("/api/v1/" + path, headers=actor.headers).status_code == 404
            assert (
                client.post(
                    "/api/v1/obligations/generate",
                    headers=headers(actor),
                    json={
                        "start_date": "2026-01-01",
                        "end_date": "2026-03-31",
                        "rule_id": rule["id"],
                    },
                ).status_code
                == 404
            )
            assert (
                client.post(
                    f"/api/v1/obligations/{obligation['id']}/settlements",
                    headers=headers(actor, version=2),
                    json={"amount_krw": "10", "occurred_on": "2026-01-31"},
                ).status_code
                == 404
            )
            assert (
                client.post(
                    f"/api/v1/settlements/{payment['id']}/void",
                    headers=headers(actor, version=1),
                    json={"reason": "합성"},
                ).status_code
                == 404
            )
            assert (
                client.post(
                    "/api/v1/recurring-rules",
                    headers=headers(actor),
                    json=rule_payload() | {"account_id": str(foreign_account.id)},
                ).status_code
                == 404
            )
            own = post_rule(client, actor)
            generate(client, actor, own["id"])
            own_obligation = obligation_for(client, actor, "2026-01")
            assert (
                client.post(
                    f"/api/v1/obligations/{own_obligation['id']}/settlements",
                    headers=headers(actor, version=1),
                    json={
                        "amount_krw": "10",
                        "occurred_on": "2026-01-31",
                        "account_id": str(foreign_account.id),
                    },
                ).status_code
                == 404
            )
            assert len(batch["items"]) == 3

    def test_idempotency_and_optimistic_conflict(self, recurring_app, actors):
        actor, partner, _ = actors
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"])
            row = obligation_for(client, actor, "2026-01")
            first = settle(client, actor, row, amount="10", key="synthetic-shared").json()
            assert settle(client, actor, row, amount="10", key="synthetic-shared").json() == first
            for person, key, amount in (
                (partner, "synthetic-new", "10"),
                (actor, "synthetic-shared", "11"),
            ):
                result = client.post(
                    f"/api/v1/obligations/{row['id']}/settlements",
                    headers=headers(person, key, 1),
                    json={"amount_krw": amount, "occurred_on": "2026-01-31"},
                )
                assert result.status_code == 409

    def test_concurrent_generation_deduplicates_database_occurrences(
        self, recurring_app, actors, db_engine
    ):
        actor, partner, _ = actors
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
        barrier = Barrier(2)

        def submit(user):
            with TestClient(recurring_app) as client:
                barrier.wait(timeout=10)
                return generate(client, user, rule["id"])

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(submit, actor), pool.submit(submit, partner)
            assert first.result(timeout=15)["items"] == second.result(timeout=15)["items"]
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(ScheduledObligation)) == 3

    def test_concurrent_settlements_same_version_one_wins(self, recurring_app, actors, db_engine):
        actor, partner, _ = actors
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"])
            row = obligation_for(client, actor, "2026-01")
        barrier = Barrier(2)

        def submit(user):
            with TestClient(recurring_app) as client:
                barrier.wait(timeout=10)
                return client.post(
                    f"/api/v1/obligations/{row['id']}/settlements",
                    headers=headers(user, version=1),
                    json={"amount_krw": "100", "occurred_on": "2026-01-31"},
                ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(submit, actor), pool.submit(submit, partner)
            assert sorted([first.result(timeout=15), second.result(timeout=15)]) == [201, 409]
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(FixedSettlement)) == 1
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 1

    def test_settlement_and_void_audit_failure_roll_back_all_facts(
        self, recurring_app, actors, db_engine, monkeypatch
    ):
        actor = actors[0]
        with TestClient(recurring_app, raise_server_exceptions=False) as client:
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"])
            row = obligation_for(client, actor, "2026-01")
            original = service._audit

            def fail(*args, **kwargs):
                if args[3] == "fixed_settlement":
                    raise RuntimeError("Synthetic transaction failure")
                return original(*args, **kwargs)

            monkeypatch.setattr(service, "_audit", fail)
            result = client.post(
                f"/api/v1/obligations/{row['id']}/settlements",
                headers=headers(actor, version=1),
                json={"amount_krw": "10", "occurred_on": "2026-01-31"},
            )
            assert result.status_code == 500
            assert obligation_for(client, actor, "2026-01")["version"] == 1
            with Session(db_engine) as session:
                assert session.scalar(select(func.count()).select_from(CashRecord)) == 0
                assert session.scalar(select(func.count()).select_from(CashRecordRevision)) == 0
                assert session.scalar(select(func.count()).select_from(FixedSettlement)) == 0
            monkeypatch.setattr(service, "_audit", original)
            payment = settle(client, actor, row, amount="10").json()
            monkeypatch.setattr(service, "_audit", fail)
            result = client.post(
                f"/api/v1/settlements/{payment['id']}/void",
                headers=headers(actor, version=1),
                json={"reason": "합성"},
            )
            assert result.status_code == 500
            assert obligation_for(client, actor, "2026-01")["actual_amount_krw"] == "10"
            assert obligation_for(client, actor, "2026-01")["version"] == 2

    @pytest.mark.parametrize(
        "target",
        [ObligationRevision, FixedSettlement, ObligationGeneration, ObligationGenerationItem],
    )
    def test_immutable_sources_reject_deletion(self, recurring_app, actors, db_engine, target):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"])
            settle(client, actor, obligation_for(client, actor, "2026-01"))
        with Session(db_engine) as session:
            with pytest.raises(DBAPIError) as rejected:
                session.execute(delete(target))
            assert rejected.value.orig.sqlstate == "55000"
            session.rollback()

    def test_database_exclusion_and_household_subtype_foreign_keys(
        self, recurring_app, actors, db_engine
    ):
        actor, _, foreign = actors
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"])
            obligation = obligation_for(client, actor, "2026-01")
            payment = settle(client, actor, obligation).json()
        with Session(db_engine) as session:
            original = session.scalar(select(RecurringRuleVersion))
            values = {
                column.name: getattr(original, column.name)
                for column in original.__table__.columns
                if column.name not in {"id", "created_at"}
            }
            session.add(RecurringRuleVersion(**(values | {"effective_from": date(2026, 1, 15)})))
            with pytest.raises(IntegrityError) as rejected:
                session.flush()
            assert rejected.value.orig.sqlstate == "23P01"
            session.rollback()
            # A new subtype must reference the same household as both source records.
            session.add(
                FixedSettlement(
                    household_id=foreign.household_id,
                    obligation_id=UUID(obligation["id"]),
                    cash_record_id=UUID(payment["cash"]["id"]),
                    economic_type="expense",
                    principal_krw=0,
                    consumption_krw=35000,
                    asset_transfer_krw=0,
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()

    def test_audit_is_metadata_only_and_mutations_require_auth_headers(
        self, recurring_app, actors, db_engine
    ):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            assert client.post("/api/v1/recurring-rules", json=rule_payload()).status_code == 401
            assert (
                client.post(
                    "/api/v1/recurring-rules", headers=actor.headers, json=rule_payload()
                ).status_code
                == 400
            )
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"])
            payment = settle(
                client, actor, obligation_for(client, actor, "2026-01"), note="합성 비공개 메모"
            ).json()
            assert (
                client.post(
                    f"/api/v1/settlements/{payment['id']}/void",
                    headers=headers(actor),
                    json={"reason": "합성"},
                ).status_code
                == 400
            )
        with Session(db_engine) as session:
            for event in session.scalars(select(AuditEvent)):
                assert set(event.safe_diff) == {"changed_fields"}
                assert "합성 비공개 메모" not in str(event.safe_diff) and "35000" not in str(
                    event.safe_diff
                )
            assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 3

    def test_change_retains_requested_horizon_and_empty_windows(self, recurring_app, actors):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor, anchor_date="2026-01-15")
            generate(client, actor, rule["id"], end="2026-03-31")
            result = client.patch(
                f"/api/v1/recurring-rules/{rule['id']}",
                headers=headers(actor, version=1),
                json=rule_payload() | {"effective_from": "2026-02-01", "reason": "합성 월말 변경"},
            )
            assert result.status_code == 200
            rows = client.get("/api/v1/obligations?month=2026-03", headers=actor.headers).json()[
                "items"
            ]
            assert {(r["scheduled_date"], r["status"]) for r in rows} == {
                ("2026-03-15", "superseded"),
                ("2026-03-31", "unpaid"),
            }
            yearly = post_rule(client, actor, anchor_date="2026-12-01", frequency="annual")
            assert (
                generate(client, actor, yearly["id"], start="2026-03-01", end="2026-03-31")["items"]
                == []
            )
            result = client.patch(
                f"/api/v1/recurring-rules/{yearly['id']}",
                headers=headers(actor, version=1),
                json=rule_payload() | {"effective_from": "2026-03-01", "reason": "합성 월납 변경"},
            )
            assert result.status_code == 200
            rows = client.get("/api/v1/obligations?month=2026-03", headers=actor.headers).json()[
                "items"
            ]
            assert any(
                r["rule_id"] == yearly["id"] and r["scheduled_date"] == "2026-03-31" for r in rows
            )

    def test_generation_failure_rolls_back_and_same_key_can_retry(
        self, recurring_app, actors, db_engine, monkeypatch
    ):
        actor = actors[0]
        original = service._remember
        count = 0

        def fail_second(*args, **kwargs):
            nonlocal count
            count += 1
            original(*args, **kwargs)
            if count == 2:
                raise RuntimeError("Synthetic batch failure")

        with TestClient(recurring_app, raise_server_exceptions=False) as client:
            rule = post_rule(client, actor)
            monkeypatch.setattr(service, "_remember", fail_second)
            result = client.post(
                "/api/v1/obligations/generate",
                headers=headers(actor, "synthetic-retry"),
                json={"start_date": "2026-01-01", "end_date": "2026-03-31", "rule_id": rule["id"]},
            )
            assert result.status_code == 500
            with Session(db_engine) as session:
                assert session.scalar(select(func.count()).select_from(ScheduledObligation)) == 0
                assert session.scalar(select(func.count()).select_from(ObligationRevision)) == 0
                assert session.scalar(select(func.count()).select_from(ObligationGeneration)) == 0
            monkeypatch.setattr(service, "_remember", original)
            assert len(generate(client, actor, rule["id"], "synthetic-retry")["items"]) == 3

    def test_same_key_concurrent_settlement_has_one_cash_fact(
        self, recurring_app, actors, db_engine
    ):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"])
            row = obligation_for(client, actor, "2026-01")
        barrier = Barrier(2)

        def submit():
            with TestClient(recurring_app) as client:
                barrier.wait(timeout=10)
                return settle(client, actor, row, key="synthetic-concurrent-payment").json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(submit), pool.submit(submit)
            assert first.result(timeout=15) == second.result(timeout=15)
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(FixedSettlement)) == 1
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 1
            assert session.get(ScheduledObligation, UUID(row["id"])).version == 2

    def test_actual_month_is_independent_of_scheduled_month(self, recurring_app, actors):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"])
            row = obligation_for(client, actor, "2026-01")
            payment = settle(client, actor, row, occurred_on="2026-02-01").json()
            assert payment["cash"]["period_month"] == "2026-02"
            jan = client.get(
                "/api/v1/obligations/summary?month=2026-01", headers=actor.headers
            ).json()
            feb = client.get(
                "/api/v1/obligations/summary?month=2026-02", headers=actor.headers
            ).json()
            assert jan["expected_known_krw"] == "33000" and jan["actual_amount_krw"] == "0"
            assert feb["expected_known_krw"] == "33000" and feb["actual_amount_krw"] == "35000"

    def test_null_and_zero_expected_are_distinct_and_unpaid(self, recurring_app, actors):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            unknown = post_rule(client, actor, amount_mode="variable", expected_amount_krw=None)
            zero = post_rule(client, actor, expected_amount_krw="0")
            generate(client, actor, unknown["id"])
            generate(client, actor, zero["id"])
            rows = client.get("/api/v1/obligations?month=2026-01", headers=actor.headers).json()[
                "items"
            ]
            assert {r["expected_amount_krw"] for r in rows} == {None, "0"}
            assert {r["status"] for r in rows} == {"unpaid"}
            result = client.get(
                "/api/v1/obligations/summary?month=2026-01", headers=actor.headers
            ).json()
            assert result["expected_known_krw"] == "0" and result["unknown_expected_count"] == 1

    @pytest.mark.parametrize(
        "economic,payment",
        [
            ("loan", {"amount_krw": "100", "principal_krw": "70"}),
            ("loan", {"amount_krw": "100", "principal_krw": "70", "interest_krw": "31"}),
            ("expense", {"amount_krw": "100", "principal_krw": "1"}),
            ("asset_transfer", {"amount_krw": "100", "interest_krw": "0"}),
            ("expense", {"amount_krw": "100", "occurred_on": "9999-01-01"}),
        ],
    )
    def test_invalid_settlement_leaves_no_cash(
        self, recurring_app, actors, db_engine, economic, payment
    ):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor, economic_type=economic)
            generate(client, actor, rule["id"])
            row = obligation_for(client, actor, "2026-01")
            result = client.post(
                f"/api/v1/obligations/{row['id']}/settlements",
                headers=headers(actor, version=1),
                json={"occurred_on": "2026-01-31", **payment},
            )
            assert result.status_code == 422
            assert obligation_for(client, actor, "2026-01")["version"] == 1
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 0
            assert session.scalar(select(func.count()).select_from(FixedSettlement)) == 0

    def test_overflow_rolls_back_additional_payment(self, recurring_app, actors, db_engine):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"])
            row = obligation_for(client, actor, "2026-01")
            settle(client, actor, row, amount=str(MAX_KRW))
            result = client.post(
                f"/api/v1/obligations/{row['id']}/settlements",
                headers=headers(actor, version=2),
                json={"amount_krw": "1", "occurred_on": "2026-01-31"},
            )
            assert (
                result.status_code == 422
                and result.json()["error"]["code"] == "AMOUNT_OUT_OF_RANGE"
            )
            assert obligation_for(client, actor, "2026-01")["actual_amount_krw"] == str(MAX_KRW)
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 1

    def test_rule_terms_are_immutable_at_database(self, recurring_app, actors, db_engine):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            post_rule(client, actor)
        with Session(db_engine) as session:
            for statement in (
                update(RecurringRuleVersion).values(expected_amount_krw=1),
                delete(RecurringRuleVersion),
            ):
                with pytest.raises(DBAPIError) as rejected:
                    session.execute(statement)
                assert rejected.value.orig.sqlstate == "55000"
                session.rollback()

    def test_t09_actual_payment_preserves_real_liability_snapshot(
        self, recurring_app, actors, db_engine
    ):
        from sallimbook.assets import month_service
        from sallimbook.assets import service as asset_service
        from sallimbook.assets.month_schemas import MonthDraft, MonthValueUpdate
        from sallimbook.assets.schemas import AssetCreate

        actor = actors[0]
        with Session(db_engine) as session:
            loan = asset_service.create_asset(
                session,
                actor.principal,
                AssetCreate(
                    name="합성 대출",
                    kind="liability",
                    category="loan",
                    ownership_kind="joint",
                    amount_basis="owned",
                    started_on="2025-01-01",
                ),
                None,
            )
            draft = month_service.create_draft(
                session,
                actor.principal,
                "2026-01",
                MonthDraft(copy_previous=False),
                "synthetic-debt-draft",
            )
            month = month_service.get_month(session, actor.principal, "2026-01")
            value = month.values[0]
            month_service.update_value(
                session,
                actor.principal,
                "2026-01",
                loan.id,
                MonthValueUpdate(
                    revision_id=draft.revision_id,
                    value_id=value.id,
                    input_amount_krw="50000000",
                    as_of_date="2026-01-31",
                ),
                f'"{value.version}"',
            )
            before = month_service.get_month(session, actor.principal, "2026-01").model_dump(
                mode="json"
            )
        with TestClient(recurring_app) as client:
            rule = post_rule(
                client,
                actor,
                economic_type="loan",
                loan_asset_id=str(loan.id),
                expected_amount_krw="1000000",
            )
            generate(client, actor, rule["id"])
            settle(
                client,
                actor,
                obligation_for(client, actor, "2026-01"),
                amount="1000000",
                principal_krw="700000",
                interest_krw="300000",
            )
        with Session(db_engine) as session:
            after = month_service.get_month(session, actor.principal, "2026-01").model_dump(
                mode="json"
            )
            assert after == before and after["values"][0]["input_amount_krw"] == "50000000"
