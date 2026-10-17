"""Synthetic recurrence, settlement, replay and household boundary regressions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from test_accounts import make_actor
from test_income import CATALOG, headers, make_account

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
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract
from sallimbook.core.idempotency import IdempotencyRecord
from sallimbook.core.types import MAX_KRW


def vector(identifier):
    return next(row for row in CATALOG["vectors"] if row["id"] == identifier)


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
    t10 = vector("T-10")
    dates = occurrence_dates(
        date(2025, 1, t10["inputs"]["anchor_day"]),
        date(2025, 2, 1),
        date(2025, 3, 31),
        frequency=t10["inputs"]["frequency"],
    )
    assert [day.isoformat() for day in dates] == t10["expected"]["scheduled_dates"]
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
    t09, t11 = vector("T-09"), vector("T-11")
    loan = payment_breakdown(
        Decimal(t09["inputs"]["payment_krw"]),
        economic_type="loan",
        principal_krw=Decimal(t09["inputs"]["principal_krw"]),
        interest_krw=Decimal(t09["inputs"]["interest_krw"]),
    )
    assert str(loan.cash_payment_krw) == t09["expected"]["cash_payment_krw"]
    assert str(loan.consumption_krw) == t09["expected"]["consumption_krw"]
    fixture_totals = settlement_totals(
        Decimal(t11["inputs"]["expected_krw"]),
        [Decimal(amount) for amount in t11["inputs"]["actual_payments_krw"]],
    )
    assert str(fixture_totals.actual_krw) == t11["expected"]["actual_total_krw"]
    assert str(fixture_totals.difference_krw) == t11["expected"]["difference_krw"]
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
        t10 = vector("T-10")
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor, anchor_date="2025-01-31", effective_from="2025-01-01")
            original = generate(
                client,
                actor,
                rule["id"],
                "synthetic-generate",
                start="2025-02-01",
                end="2025-02-28",
            )
            assert (
                generate(
                    client,
                    actor,
                    rule["id"],
                    "synthetic-generate",
                    start="2025-02-01",
                    end="2025-02-28",
                )
                == original
            )
            for _ in range(t10["inputs"]["generation_attempts"]):
                generate(client, actor, rule["id"], start="2025-02-01", end="2025-03-31")
            rows = [obligation_for(client, actor, month) for month in t10["inputs"]["months"]]
            assert [row["nominal_date"] for row in rows] == t10["expected"]["scheduled_dates"]
        with Session(db_engine) as session:
            counts = [
                session.scalar(
                    select(func.count())
                    .select_from(ScheduledObligation)
                    .where(ScheduledObligation.nominal_date == date.fromisoformat(day))
                )
                for day in t10["expected"]["scheduled_dates"]
            ]
            assert counts == t10["expected"]["occurrence_counts"]
            assert session.scalar(select(func.count()).select_from(ObligationRevision)) == 2

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
        t09 = vector("T-09")
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
                    input_amount_krw=t09["inputs"]["liability_snapshot_before_krw"],
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
                expected_amount_krw=t09["inputs"]["payment_krw"],
            )
            generate(client, actor, rule["id"])
            settle(
                client,
                actor,
                obligation_for(client, actor, "2026-01"),
                amount=t09["inputs"]["payment_krw"],
                principal_krw=t09["inputs"]["principal_krw"],
                interest_krw=t09["inputs"]["interest_krw"],
            )
        with Session(db_engine) as session:
            after = month_service.get_month(session, actor.principal, "2026-01").model_dump(
                mode="json"
            )
            assert (
                after == before
                and after["values"][0]["input_amount_krw"]
                == t09["expected"]["liability_snapshot_after_krw"]
            )

    def test_card_planning_and_actual_method_use_real_scoped_references(
        self, recurring_app, actors, db_engine
    ):
        from sallimbook.cards import service as cards
        from sallimbook.cards.schemas import CardCreate, CardPatch

        actor, _, foreign = actors
        with Session(db_engine) as session:
            own_card = cards.create_card(
                session,
                actor.principal,
                CardCreate(
                    owner_member_id=actor.member_id,
                    issuer_name="합성",
                    product_name="합성 카드",
                    card_type="credit",
                ),
            )
            foreign_card = cards.create_card(
                session,
                foreign.principal,
                CardCreate(
                    owner_member_id=foreign.member_id,
                    issuer_name="합성",
                    product_name="합성 외부",
                    card_type="credit",
                ),
            )
        with TestClient(recurring_app) as client:
            result = client.post(
                "/api/v1/recurring-rules",
                headers=headers(actor),
                json=rule_payload() | {"card_id": str(foreign_card.id)},
            )
            assert result.status_code == 404
            rule = post_rule(client, actor, card_id=str(own_card.id))
            generate(client, actor, rule["id"])
            row = obligation_for(client, actor, "2026-01")
            assert row["card_id"] == str(own_card.id) and row["account_id"] is None
            result = client.post(
                f"/api/v1/obligations/{row['id']}/settlements",
                headers=headers(actor, version=1),
                json={
                    "amount_krw": "100",
                    "occurred_on": "2026-01-31",
                    "card_id": str(foreign_card.id),
                },
            )
            assert result.status_code == 404
            payment = settle(client, actor, row, card_id=str(own_card.id)).json()
            assert payment["cash"]["card_id"] == str(own_card.id)
            assert payment["cash"]["account_id"] is None
            # Card cash-out is not an extra second cash fact or consumption record.
            with Session(db_engine) as session:
                assert session.scalar(select(func.count()).select_from(CashRecord)) == 1
                with pytest.raises(DomainError) as rejected:
                    cards.delete_card(session, actor.principal, own_card.id, '"1"')
                assert getattr(rejected.value, "code", None) == "CARD_IN_USE"
                cards.update_card(
                    session,
                    actor.principal,
                    own_card.id,
                    CardPatch(ended_on="2026-01-31"),
                    '"1"',
                    archive=True,
                )
            next_row = obligation_for(client, actor, "2026-02")
            result = client.post(
                f"/api/v1/obligations/{next_row['id']}/settlements",
                headers=headers(actor, version=1),
                json={
                    "amount_krw": "100",
                    "occurred_on": "2026-01-31",
                    "card_id": str(own_card.id),
                },
            )
            assert (
                result.status_code == 422 and result.json()["error"]["code"] == "CARD_UNAVAILABLE"
            )
            result = client.post(
                "/api/v1/recurring-rules",
                headers=headers(actor),
                json=rule_payload() | {"card_id": str(own_card.id)},
            )
            assert result.status_code == 422
            assert obligation_for(client, actor, "2026-01")["actual_amount_krw"] == "35000"

    def test_actual_account_and_card_are_mutually_exclusive(self, recurring_app, actors, db_engine):
        actor = actors[0]
        account = make_account(db_engine, actor)
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"])
            row = obligation_for(client, actor, "2026-01")
            result = client.post(
                f"/api/v1/obligations/{row['id']}/settlements",
                headers=headers(actor, version=1),
                json={
                    "amount_krw": "1",
                    "occurred_on": "2026-01-31",
                    "account_id": str(account.id),
                    "card_id": str(uuid4()),
                },
            )
            assert result.status_code == 422
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 0

    def test_loan_reference_rejects_assets_and_foreign_households(
        self, recurring_app, actors, db_engine
    ):
        from sallimbook.assets import service as assets
        from sallimbook.assets.schemas import AssetCreate

        actor, _, foreign = actors
        own_asset = make_account(db_engine, actor)
        with Session(db_engine) as session:
            alien_loan = assets.create_asset(
                session,
                foreign.principal,
                AssetCreate(
                    name="합성 외부 부채",
                    kind="liability",
                    category="loan",
                    ownership_kind="joint",
                    amount_basis="owned",
                    started_on="2025-01-01",
                ),
            )
        with TestClient(recurring_app) as client:
            for identifier, expected in ((own_asset.asset_id, 422), (alien_loan.id, 404)):
                result = client.post(
                    "/api/v1/recurring-rules",
                    headers=headers(actor),
                    json=rule_payload()
                    | {"economic_type": "loan", "loan_asset_id": str(identifier)},
                )
                assert result.status_code == expected

    @pytest.mark.parametrize("end_source", ["initial", "end_api"])
    def test_future_ended_rule_accepts_changes_inside_original_cutoff(
        self,
        recurring_app,
        actors,
        db_engine,
        monkeypatch,
        end_source,
    ):
        actor = actors[0]
        with Session(db_engine) as session:
            current = session.scalar(
                text("SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date")
            )
        monkeypatch.setattr(service, "today", lambda: current)
        start = current - timedelta(days=2)
        cutoff = current + timedelta(days=10)
        first_day, second_day = current + timedelta(days=1), current + timedelta(days=3)
        first_account, second_account = (
            make_account(db_engine, actor),
            make_account(db_engine, actor),
        )
        original = rule_payload() | {
            "frequency": "days",
            "interval_count": 1,
            "anchor_date": start.isoformat(),
            "effective_from": start.isoformat(),
            "account_id": str(first_account.id),
        }
        with TestClient(recurring_app) as client:
            rule = post_rule(
                client,
                actor,
                **(
                    original
                    | (
                        {"effective_until": cutoff.isoformat(), "end_reason": "합성 예정 종료"}
                        if end_source == "initial"
                        else {}
                    )
                ),
            )
            generate(
                client,
                actor,
                rule["id"],
                start=start.isoformat(),
                end=(cutoff + timedelta(days=3)).isoformat(),
            )
            path = f"/api/v1/recurring-rules/{rule['id']}"
            version = 1
            if end_source == "end_api":
                ended = client.post(
                    path + "/end",
                    headers=headers(actor, version=version),
                    json={"effective_on": cutoff.isoformat(), "reason": "합성 예정 종료"},
                )
                assert ended.status_code == 200, ended.text
                version = ended.json()["version"]
            with Session(db_engine) as session:
                occurrences = dict(
                    session.execute(
                        select(
                            ScheduledObligation.nominal_date,
                            ScheduledObligation.id,
                        ).where(ScheduledObligation.rule_id == UUID(rule["id"]))
                    ).all()
                )

            def obligation(day):
                return client.get(
                    f"/api/v1/obligations/{occurrences[day]}", headers=actor.headers
                ).json()

            past = obligation(current - timedelta(days=1))
            future_paid = obligation(first_day)
            settle(client, actor, future_paid, amount="100", occurred_on=current.isoformat())
            future_paid = obligation(first_day)
            first_body = original | {
                "effective_from": first_day.isoformat(),
                "anchor_date": first_day.isoformat(),
                "interval_count": 2,
                "expected_amount_krw": "44000",
                "account_id": str(second_account.id),
                "reason": "합성 기간 내 변경",
            }
            first_headers = headers(actor, "finite-first-change", version)
            changed = client.patch(path, headers=first_headers, json=first_body)
            assert changed.status_code == 200, changed.text
            assert obligation(current - timedelta(days=1)) == past
            assert obligation(first_day) == future_paid
            updated = obligation(second_day)
            assert updated["expected_amount_krw"] == "44000"
            assert updated["account_id"] == str(second_account.id)
            assert obligation(first_day + timedelta(days=1))["schedule_state"] == "superseded"
            second_body = first_body | {
                "effective_from": second_day.isoformat(),
                "anchor_date": second_day.isoformat(),
                "interval_count": 3,
                "expected_amount_krw": "55000",
                "reason": "합성 두 번째 변경",
            }
            second = client.patch(
                path, headers=headers(actor, version=changed.json()["version"]), json=second_body
            )
            assert second.status_code == 200, second.text
            replay = client.patch(path, headers=first_headers, json=first_body)
            assert replay.status_code == 200 and replay.json() == changed.json()
            for invalid_day in (
                cutoff,
                cutoff + timedelta(days=1),
                start,
                current - timedelta(days=1),
            ):
                rejected = client.patch(
                    path,
                    headers=headers(actor, version=second.json()["version"]),
                    json=second_body | {"effective_from": invalid_day.isoformat()},
                )
                assert rejected.status_code == 409
            stored = client.get(path, headers=actor.headers).json()
            assert (
                stored["ended_on"] == cutoff.isoformat()
                and stored["end_reason"] == "합성 예정 종료"
            )
            assert [v["effective_until"] for v in stored["versions"]] == [
                first_day.isoformat(),
                second_day.isoformat(),
                cutoff.isoformat(),
            ]
            assert [v["expected_amount_krw"] for v in stored["versions"]] == [
                "33000",
                "44000",
                "55000",
            ]
            assert (
                obligation(current - timedelta(days=1)) == past
                and obligation(first_day) == future_paid
            )
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(RecurringRuleVersion)
                    .where(RecurringRuleVersion.rule_id == UUID(rule["id"]))
                )
                == 3
            )
            active = list(
                session.scalars(
                    select(ScheduledObligation.nominal_date).where(
                        ScheduledObligation.rule_id == UUID(rule["id"]),
                        ScheduledObligation.schedule_state == "active",
                    )
                )
            )
            assert all(day < cutoff for day in active)
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 1

    @pytest.mark.parametrize("end_source", ["initial", "end_api"])
    def test_scheduled_end_can_shorten_preserving_history_payments_and_manual_rows(
        self, recurring_app, actors, db_engine, monkeypatch, end_source
    ):
        actor = actors[0]
        with Session(db_engine) as session:
            current = session.scalar(
                text("SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date")
            )
        monkeypatch.setattr(service, "today", lambda: current)
        start, cutoff = current - timedelta(days=2), current + timedelta(days=10)
        latest_start, shortened = current + timedelta(days=1), current + timedelta(days=4)
        original = rule_payload() | {
            "frequency": "days",
            "interval_count": 1,
            "anchor_date": start.isoformat(),
            "effective_from": start.isoformat(),
        }
        with TestClient(recurring_app) as client:
            rule = post_rule(
                client,
                actor,
                **(
                    original
                    | (
                        {"effective_until": cutoff.isoformat(), "end_reason": "합성 예정 종료"}
                        if end_source == "initial"
                        else {}
                    )
                ),
            )
            path = f"/api/v1/recurring-rules/{rule['id']}"
            version = 1
            if end_source == "end_api":
                ended = client.post(
                    path + "/end",
                    headers=headers(actor, version=version),
                    json={"effective_on": cutoff.isoformat(), "reason": "합성 예정 종료"},
                )
                assert ended.status_code == 200, ended.text
                version = ended.json()["version"]
            changed = client.patch(
                path,
                headers=headers(actor, version=version),
                json=original
                | {
                    "effective_from": latest_start.isoformat(),
                    "expected_amount_krw": "44000",
                    "reason": "합성 조건 변경",
                },
            )
            assert changed.status_code == 200, changed.text
            version = changed.json()["version"]
            generate(
                client,
                actor,
                rule["id"],
                start=start.isoformat(),
                end=(cutoff + timedelta(days=2)).isoformat(),
            )
            with Session(db_engine) as session:
                ids = dict(
                    session.execute(
                        select(ScheduledObligation.nominal_date, ScheduledObligation.id).where(
                            ScheduledObligation.rule_id == UUID(rule["id"])
                        )
                    ).all()
                )

            def obligation(day):
                result = client.get(f"/api/v1/obligations/{ids[day]}", headers=actor.headers)
                assert result.status_code == 200, result.text
                return result.json()

            paid_day, manual_day = shortened + timedelta(days=1), shortened + timedelta(days=2)
            payment = settle(
                client, actor, obligation(paid_day), amount="100", occurred_on=current.isoformat()
            ).json()
            manual = obligation(manual_day)
            moved = client.patch(
                f"/api/v1/obligations/{manual['id']}",
                headers=headers(actor, version=manual["version"]),
                json={
                    "scheduled_date": (manual_day + timedelta(days=1)).isoformat(),
                    "reason": "합성 수동 이동",
                },
            )
            assert moved.status_code == 200, moved.text
            protected = {
                day: obligation(day) for day in (current - timedelta(days=1), paid_day, manual_day)
            }
            before = client.get(path, headers=actor.headers).json()
            body = {"effective_on": shortened.isoformat(), "reason": "합성 종료 앞당김"}
            mutation_headers = headers(actor, "shorten-scheduled-end", version)
            foreign = client.post(
                path + "/end", headers=headers(actors[2], version=version), json=body
            )
            assert foreign.status_code == 404
            assert client.get(path, headers=actor.headers).json() == before
            ended = client.post(path + "/end", headers=mutation_headers, json=body)
            assert ended.status_code == 200, ended.text
            assert ended.json() == {"id": rule["id"], "version": version + 1}
            after = client.get(path, headers=actor.headers).json()
            assert after["ended_on"] == shortened.isoformat()
            assert after["end_reason"] == body["reason"]
            assert after["versions"][:-1] == before["versions"][:-1]
            assert after["versions"][-1] == before["versions"][-1] | {
                "effective_until": shortened.isoformat()
            }
            assert all(obligation(day) == saved for day, saved in protected.items())
            assert obligation(shortened)["schedule_state"] == "superseded"
            assert obligation(shortened - timedelta(days=1))["schedule_state"] == "active"
            for invalid_day in (
                shortened,
                cutoff,
                latest_start,
                start,
                current - timedelta(days=1),
            ):
                rejected = client.post(
                    path + "/end",
                    headers=headers(actor, version=version + 1),
                    json=body | {"effective_on": invalid_day.isoformat()},
                )
                assert rejected.status_code == 409, rejected.text
            assert (
                client.post(
                    path + "/end",
                    headers=headers(actor, version=version),
                    json=body | {"effective_on": (shortened - timedelta(days=1)).isoformat()},
                ).json()["error"]["code"]
                == "VERSION_CONFLICT"
            )
            assert (
                client.post(
                    path + "/end",
                    headers=mutation_headers,
                    json=body | {"reason": "합성 다른 요청"},
                ).json()["error"]["code"]
                == "IDEMPOTENCY_CONFLICT"
            )
            second = client.post(
                path + "/end",
                headers=headers(actor, version=version + 1),
                json=body
                | {
                    "effective_on": (shortened - timedelta(days=1)).isoformat(),
                    "reason": "합성 두 번째 앞당김",
                },
            )
            assert second.status_code == 200, second.text
            replay = client.post(path + "/end", headers=mutation_headers, json=body)
            assert replay.status_code == 200 and replay.json() == ended.json()
            generate(
                client,
                actor,
                rule["id"],
                start=start.isoformat(),
                end=(cutoff + timedelta(days=3)).isoformat(),
            )
            assert all(obligation(day) == saved for day, saved in protected.items())
            assert client.get(path, headers=actor.headers).json()["version"] == version + 2
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 1
            assert session.get(FixedSettlement, UUID(payment["id"])) is not None
            assert session.scalar(select(func.count()).select_from(RecurringRuleVersion)) == 2
            replays = list(
                session.scalars(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.operation == "recurring.end",
                        IdempotencyRecord.key == "shorten-scheduled-end",
                    )
                )
            )
            assert len(replays) == 1 and replays[0].resource_version == version + 1
            archives = list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.entity_id == UUID(rule["id"]), AuditEvent.action == "archive"
                    )
                )
            )
            assert len(archives) == (3 if end_source == "end_api" else 2)

    @pytest.mark.parametrize("ended_offset", [-1, 0])
    def test_elapsed_rule_end_cannot_reopen_extend_or_rewrite_history(
        self, recurring_app, actors, db_engine, monkeypatch, ended_offset
    ):
        actor = actors[0]
        with Session(db_engine) as session:
            current = session.scalar(
                text("SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date")
            )
        monkeypatch.setattr(service, "today", lambda: current)
        cutoff = current + timedelta(days=ended_offset)
        with TestClient(recurring_app) as client:
            rule = post_rule(
                client,
                actor,
                effective_from=(current - timedelta(days=10)).isoformat(),
                effective_until=cutoff.isoformat(),
                end_reason="합성 과거 종료",
            )
            path = f"/api/v1/recurring-rules/{rule['id']}"
            original = client.get(path, headers=actor.headers).json()
            for requested in (cutoff, cutoff - timedelta(days=1), current + timedelta(days=1)):
                rejected = client.post(
                    path + "/end",
                    headers=headers(actor, version=1),
                    json={"effective_on": requested.isoformat(), "reason": "합성 재종료 시도"},
                )
                assert rejected.status_code == 409, rejected.text
            assert client.get(path, headers=actor.headers).json() == original
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(IdempotencyRecord)
                    .where(IdempotencyRecord.operation == "recurring.end")
                )
                == 0
            )

    def test_scheduled_end_can_shorten_to_today_but_not_to_yesterday(
        self, recurring_app, actors, db_engine, monkeypatch
    ):
        actor = actors[0]
        with Session(db_engine) as session:
            current = session.scalar(
                text("SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date")
            )
        monkeypatch.setattr(service, "today", lambda: current)
        with TestClient(recurring_app) as client:
            rule = post_rule(
                client,
                actor,
                effective_from=(current - timedelta(days=10)).isoformat(),
                effective_until=(current + timedelta(days=10)).isoformat(),
                end_reason="합성 예정 종료",
            )
            path = f"/api/v1/recurring-rules/{rule['id']}"
            past = client.post(
                path + "/end",
                headers=headers(actor, version=1),
                json={
                    "effective_on": (current - timedelta(days=1)).isoformat(),
                    "reason": "합성 과거",
                },
            )
            assert past.status_code == 409 and past.json()["error"]["code"] == "PAST_RULE_CHANGE"
            ended = client.post(
                path + "/end",
                headers=headers(actor, version=1),
                json={"effective_on": current.isoformat(), "reason": "합성 당일 종료"},
            )
            assert ended.status_code == 200, ended.text
            stored = client.get(path, headers=actor.headers).json()
            assert stored["ended_on"] == current.isoformat()
            assert stored["versions"][-1]["effective_until"] == current.isoformat()

    def test_finite_rule_db_end_can_only_shorten_without_changing_terms(
        self,
        recurring_app,
        actors,
        db_engine,
    ):
        actor = actors[0]
        with Session(db_engine) as session:
            current = session.scalar(
                text("SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date")
            )
        cutoff = current + timedelta(days=30)
        with TestClient(recurring_app) as client:
            rule = post_rule(
                client,
                actor,
                effective_from=current.isoformat(),
                effective_until=cutoff.isoformat(),
                end_reason="합성 종료",
            )
        with Session(db_engine) as session:
            query = update(RecurringRuleVersion).where(
                RecurringRuleVersion.rule_id == UUID(rule["id"])
            )
            shortened = cutoff - timedelta(days=1)
            session.execute(query.values(effective_until=shortened))
            session.commit()
            for values in (
                {"effective_until": cutoff},
                {"effective_until": None},
                {"effective_until": shortened},
                {"expected_amount_krw": 1},
                {"effective_until": shortened - timedelta(days=1), "title": "합성 변조"},
                {"effective_from": current - timedelta(days=1)},
            ):
                with pytest.raises(DBAPIError) as rejected:
                    session.execute(query.values(**values))
                assert rejected.value.orig.sqlstate == "55000"
                session.rollback()
            assert (
                session.scalar(
                    select(RecurringRuleVersion.effective_until).where(
                        RecurringRuleVersion.rule_id == UUID(rule["id"])
                    )
                )
                == shortened
            )

    def test_initial_historical_ended_rule_keeps_its_original_period(self, recurring_app, actors):
        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(
                client,
                actor,
                anchor_date="2025-01-31",
                effective_from="2025-01-01",
                effective_until="2025-03-01",
                end_reason="합성 과거 종료 기록",
            )
            result = generate(client, actor, rule["id"], start="2025-01-01", end="2025-12-31")
            assert len(result["items"]) == 2
            stored = client.get(
                f"/api/v1/recurring-rules/{rule['id']}", headers=actor.headers
            ).json()
            assert stored["ended_on"] == "2025-03-01"
            assert stored["end_reason"] == "합성 과거 종료 기록"
            assert stored["versions"][0]["effective_until"] == "2025-03-01"
            assert stored["versions"][0]["reason"] == "합성 과거 종료 기록"
            assert (
                client.get("/api/v1/obligations?month=2025-03", headers=actor.headers).json()[
                    "items"
                ]
                == []
            )
            assert (
                client.patch(
                    f"/api/v1/recurring-rules/{rule['id']}",
                    headers=headers(actor, version=1),
                    json=rule_payload()
                    | {"effective_from": "2026-03-01", "reason": "합성 과거변경 금지"},
                ).status_code
                == 409
            )


@pytest.mark.parametrize(
    "overrides",
    [
        {"effective_until": "2026-03-01"},
        {"end_reason": "합성"},
        {"effective_until": "2026-01-01", "end_reason": "합성"},
        {"effective_until": "2025-12-31", "end_reason": "합성"},
    ],
)
def test_initial_ended_rule_requires_ordered_period_and_reason_pair(overrides):
    with pytest.raises(ValidationError):
        RuleCreate(**(rule_payload() | overrides))


@pytest.fixture
def reading_dataset(recurring_app, actors):
    actor = actors[0]
    with TestClient(recurring_app) as client:
        rules = [post_rule(client, actor, title=f"합성 일괄 조회 {index}") for index in range(4)]
        for rule in rules:
            generate(client, actor, rule["id"], start="2026-01-01", end="2026-01-31")
        rows = client.get("/api/v1/obligations?month=2026-01", headers=actor.headers).json()[
            "items"
        ]
        row = rows[0]
        payments = [
            settle(client, actor, row | {"version": version}, amount="10").json()
            for version in range(1, 5)
        ]
        void = client.post(
            f"/api/v1/settlements/{payments[0]['id']}/void",
            headers=headers(actor, version=1),
            json={"reason": "합성 조회 이력"},
        )
        assert void.status_code == 200
        changed = client.patch(
            f"/api/v1/recurring-rules/{rules[0]['id']}",
            headers=headers(actor, version=1),
            json=rule_payload() | {"effective_from": "2026-03-01", "reason": "합성 조회 이력"},
        )
        assert changed.status_code == 200
    return rules, row, payments


@pytest.mark.database
class TestRecurringReadQueries:
    @pytest.mark.parametrize("view", ["rules", "obligations", "settlements"])
    def test_page_queries_are_constant_and_preserve_current_cash_revision(
        self, db_engine, actors, reading_dataset, view
    ):
        from sqlalchemy import event

        actor = actors[0]
        rules, obligation, payments = reading_dataset
        counts = []
        for limit in (1, 10):
            statements = []

            def count_selects(
                connection,
                cursor,
                statement,
                parameters,
                context,
                executemany,
                statements=statements,
            ):
                if statement.lstrip().upper().startswith("SELECT"):
                    statements.append(statement)

            with Session(db_engine) as session:
                event.listen(db_engine, "before_cursor_execute", count_selects)
                try:
                    if view == "rules":
                        response = service.list_rules(session, actor.principal, limit=limit)
                    elif view == "obligations":
                        response = service.list_obligations(
                            session, actor.principal, "2026-01", limit=limit
                        )
                    else:
                        response = service.list_settlements(
                            session, actor.principal, UUID(obligation["id"]), limit=limit
                        )
                finally:
                    event.remove(db_engine, "before_cursor_execute", count_selects)
            counts.append(len(statements))
            assert len(response.items) == (1 if limit == 1 else 4)
            assert (response.next_cursor is not None) == (limit == 1)
            if limit == 10:
                if view == "rules":
                    first = next(item for item in response.items if str(item.id) == rules[0]["id"])
                    assert first.version == 2 and len(first.versions) == 2
                elif view == "obligations":
                    paid = next(item for item in response.items if str(item.id) == obligation["id"])
                    assert paid.actual_amount_krw == "30" and paid.version == 6
                    assert sum(int(item.actual_amount_krw) for item in response.items) == 30
                else:
                    voided = next(
                        item for item in response.items if str(item.id) == payments[0]["id"]
                    )
                    assert voided.cash.state == "void" and voided.cash.version == 2
                    assert sum(item.cash.state == "active" for item in response.items) == 3
        # Household barrier, page rows/scope check, and one batch relation query.
        assert counts == [3, 3]

    @pytest.mark.parametrize("view", ["get_obligation", "list_obligations", "summary"])
    def test_reader_holds_one_snapshot_while_an_actual_payment_waits(
        self, db_engine, recurring_app, actors, view
    ):
        from threading import Event
        from time import monotonic, sleep

        from sqlalchemy import event, text

        from sallimbook.cashflow.recurring_schemas import SettlementCreate

        actor = actors[0]
        with TestClient(recurring_app) as client:
            rule = post_rule(client, actor)
            generate(client, actor, rule["id"], start="2026-01-01", end="2026-01-31")
            obligation = obligation_for(client, actor, "2026-01")
        ready, release, writer_ready = Event(), Event(), Event()
        pids = {}

        def read():
            with Session(db_engine) as session:
                connection = session.connection()
                pids["reader"] = connection.connection.driver_connection.info.backend_pid

                def pause_before_actual(conn, cursor, statement, parameters, context, executemany):
                    if (
                        statement.lstrip().upper().startswith("SELECT")
                        and "FROM fixed_settlements" in statement
                    ):
                        ready.set()
                        assert release.wait(10), "Synthetic reader was not released"

                event.listen(connection, "before_cursor_execute", pause_before_actual)
                try:
                    if view == "get_obligation":
                        return service.get_obligation(
                            session, actor.principal, UUID(obligation["id"])
                        )
                    if view == "list_obligations":
                        return service.list_obligations(session, actor.principal, "2026-01").items[
                            0
                        ]
                    return service.summary(session, actor.principal, "2026-01")
                finally:
                    event.remove(connection, "before_cursor_execute", pause_before_actual)

        def write():
            with Session(db_engine) as session:
                pids["writer"] = session.connection().connection.driver_connection.info.backend_pid
                writer_ready.set()
                return service.settle(
                    session,
                    actor.principal,
                    UUID(obligation["id"]),
                    SettlementCreate(amount_krw="10", occurred_on="2026-01-31"),
                    '"1"',
                    "synthetic-snapshot-write",
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            reader = pool.submit(read)
            try:
                assert ready.wait(10)
                writer = pool.submit(write)
                assert writer_ready.wait(10)
                with db_engine.connect() as observer:
                    deadline = monotonic() + 10
                    blockers = []
                    while monotonic() < deadline:
                        blockers = observer.scalar(
                            text("SELECT pg_blocking_pids(:pid)"), {"pid": pids["writer"]}
                        )
                        if pids["reader"] in blockers:
                            break
                        sleep(0.01)
                    assert pids["reader"] in blockers
                release.set()
                before = reader.result(timeout=10)
                payment = writer.result(timeout=10)
            finally:
                release.set()
        assert before.actual_amount_krw == "0"
        if view != "summary":
            assert before.version == 1 and before.status == "unpaid"
        assert payment.cash.amount_krw == "10"
        with Session(db_engine) as session:
            after = service.get_obligation(session, actor.principal, UUID(obligation["id"]))
        assert after.version == 2 and after.actual_amount_krw == "10"
