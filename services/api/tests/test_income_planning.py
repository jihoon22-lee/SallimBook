"""Synthetic expected income and compensation; never current asset valuations."""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from test_accounts import make_actor

from sallimbook.cashflow import planning_service as service
from sallimbook.cashflow.models import CashRecord
from sallimbook.cashflow.planning_schemas import BonusChange, BonusInput, ExpectedInput
from sallimbook.core.errors import DomainError


def bonus(actor, **values):
    return BonusInput(
        member_id=actor.member_id,
        performance_year=2022,
        award_kind="opi",
        payment_month="2023-01",
        gross_krw="5000000",
        net_cash_krw="3000000",
        stock_grant_value_krw="1000000",
        payout_rate_percent="37.5",
        received=True,
        **values,
    )


@pytest.mark.parametrize("value", [37.5, "-1", "1e2", "01", "1.234", True])
def test_rate_is_exact_decimal_string(value):
    with pytest.raises(ValidationError):
        BonusInput(
            member_id=uuid4(), performance_year=2022, award_kind="opi", payout_rate_percent=value
        )


def test_expected_and_bonus_idempotency_actual_cash_and_correction(db_session, db_engine):
    actor = make_actor(db_engine)
    expected = ExpectedInput(member_id=actor.member_id, label="합성 월급", amount_krw="2500000")
    first = service.create_expected(db_session, actor.principal, expected, "expected-one")
    assert service.create_expected(db_session, actor.principal, expected, "expected-one") == first
    assert db_session.scalar(select(func.count()).select_from(CashRecord)) == 0
    record = service.create_bonus(db_session, actor.principal, bonus(actor), "bonus-one")
    assert service.create_bonus(db_session, actor.principal, bonus(actor), "bonus-one") == record
    cash = db_session.get(CashRecord, record.cash_record_id)
    assert int(cash.amount_krw) == 3000000
    assert cash.period_month.isoformat() == "2023-01-01" and cash.occurred_on is None
    corrected = BonusChange(
        **(bonus(actor).model_dump() | {"net_cash_krw": "3100000", "reason": "합성 정정"})
    )
    changed = service.change_bonus(
        db_session, actor.principal, record.id, corrected, '"1"', "change-one"
    )
    assert changed.version == 2 and changed.cash_record_id != record.cash_record_id
    assert db_session.get(CashRecord, record.cash_record_id).state == "void"
    assert service.create_bonus(db_session, actor.principal, bonus(actor), "bonus-one") == record
    with pytest.raises(DomainError) as exc:
        service.change_bonus(db_session, actor.principal, record.id, corrected, '"1"', "stale")
    assert exc.value.status == 409
    db_session.rollback()
    stranger = make_actor(db_engine)
    with pytest.raises(DomainError):
        service.change_bonus(db_session, stranger.principal, record.id, corrected, '"2"', "foreign")
    db_session.rollback()


def test_zero_unknown_and_received_validation():
    base = dict(member_id=uuid4(), performance_year=2023, award_kind="tai_h1")
    assert BonusInput(**base, net_cash_krw="0").net_cash_krw == "0"
    assert BonusInput(**base).net_cash_krw is None
    with pytest.raises(ValidationError):
        BonusInput(**base, received=True, net_cash_krw="10")


def test_http_scope_zero_duplicate_link_protection_and_return_guard(db_engine):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from test_income import headers

    from sallimbook.cashflow.planning_router import router
    from sallimbook.cashflow.router import router as cash_router
    from sallimbook.config import Settings
    from sallimbook.core.http import install_http_contract

    actor, stranger = make_actor(db_engine), make_actor(db_engine)
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(app)
    app.include_router(router)
    app.include_router(cash_router)
    with TestClient(app) as client:
        body = bonus(actor).model_dump(mode="json")
        url = "/api/v1/income-planning/bonuses"
        assert client.post(url, json=body).status_code == 401
        assert (
            client.post(
                url, json=body | {"member_id": str(stranger.member_id)}, headers=headers(actor)
            ).status_code
            == 404
        )
        row = client.post(url, json=body, headers=headers(actor)).json()
        assert client.post(url, json=body, headers=headers(actor)).status_code == 409
        assert client.get(url, headers=stranger.headers).json()["items"] == []
        assert (
            client.put(
                f"{url}/{row['id']}",
                json=body | {"reason": "합성 정정"},
                headers=headers(stranger, version=1),
            ).status_code
            == 404
        )
        cash_id = row["cash_record_id"]
        for method, suffix, patch in [
            ("patch", "", {"reason": "합성 수정", "amount_krw": "1"}),
            ("post", "/void", {"reason": "합성 취소"}),
        ]:
            assert (
                client.request(
                    method,
                    f"/api/v1/income/{cash_id}{suffix}",
                    json=patch,
                    headers=headers(actor, version=1),
                ).status_code
                == 409
            )
        refund = client.post(
            f"/api/v1/income/{cash_id}/returns",
            json={
                "reason": "합성 반환",
                "amount_krw": "100",
                "period_month": "2023-02",
                "date_precision": "month",
            },
            headers=headers(actor, version=1),
        )
        assert refund.status_code == 201
        assert (
            client.put(
                f"{url}/{row['id']}",
                json=body | {"reason": "합성 정정", "net_cash_krw": "3100000"},
                headers=headers(actor, version=1),
            ).status_code
            == 409
        )
        zero = client.post(
            url,
            json=body
            | {"award_kind": "tai_h1", "net_cash_krw": "0", "stock_grant_value_krw": None},
            headers=headers(actor),
        ).json()
        assert (
            zero["cash_record_id"] is None
            and zero["net_cash_krw"] == "0"
            and zero["stock_grant_value_krw"] is None
        )


@pytest.mark.parametrize(
    "change",
    [
        {"net_cash_krw": "0"},
        {"net_cash_krw": None, "received": False},
        {"received": False},
        {"active": False},
    ],
)
def test_cash_unlink_transitions_are_atomic(db_session, db_engine, change):
    actor = make_actor(db_engine)
    data = bonus(actor)
    saved = service.create_bonus(db_session, actor.principal, data, "create")
    changed = service.change_bonus(
        db_session,
        actor.principal,
        saved.id,
        BonusChange(**(data.model_dump() | change | {"reason": "합성 정정"})),
        '"1"',
        "change",
    )
    assert changed.cash_record_id is None
    assert db_session.get(CashRecord, saved.cash_record_id).state == "void"


def test_existing_manual_cash_duplicate_and_failed_correction_roll_back(db_session, db_engine):
    from sallimbook.cashflow import service as cash
    from sallimbook.cashflow.schemas import IncomeCreate

    actor = make_actor(db_engine)
    data = bonus(actor)
    saved = service.create_bonus(db_session, actor.principal, data, "first")
    current = cash.get_income(db_session, actor.principal, saved.cash_record_id)
    assert not current.editable and not current.voidable
    manual = cash.create_income(
        db_session,
        actor.principal,
        IncomeCreate(
            kind="bonus",
            member_id=actor.member_id,
            amount_krw="40",
            period_month="2023-02",
            date_precision="month",
        ),
        "manual",
    )
    with pytest.raises(DomainError) as error:
        service.change_bonus(
            db_session,
            actor.principal,
            saved.id,
            BonusChange(
                **(data.model_dump() | {"payment_month": "2023-02", "reason": "합성 실패"})
            ),
            '"1"',
            "fail-change",
        )
    assert error.value.code == "INCOME_DUPLICATE_SUSPECTED"
    db_session.rollback()
    assert db_session.get(CashRecord, saved.cash_record_id).state == "active"
    with pytest.raises(DomainError):
        service.create_bonus(
            db_session,
            actor.principal,
            BonusInput(
                **(data.model_dump() | {"award_kind": "tai_h1", "payment_month": "2023-02"})
            ),
            "duplicate",
        )
    db_session.rollback()
    assert cash.get_income(db_session, actor.principal, manual.id).amount_krw == "40"


def test_dashboard_baseline_is_current_scoped_exact_and_never_actual_cash(db_session, db_engine):
    from sallimbook.assets.month_models import AssetMonthRecord
    from sallimbook.cashflow.service import summary

    actor, stranger = make_actor(db_engine), make_actor(db_engine)
    for number, amount in enumerate(["9007199254740993", "0", None]):
        service.create_expected(
            db_session,
            actor.principal,
            ExpectedInput(
                member_id=actor.member_id, label=f"합성 수입 {number}", amount_krw=amount
            ),
            f"dashboard-{number}",
        )
    service.create_expected(
        db_session,
        actor.principal,
        ExpectedInput(member_id=actor.member_id, label="합성 종료", amount_krw="100", active=False),
        "ended",
    )
    service.create_expected(
        db_session,
        stranger.principal,
        ExpectedInput(member_id=stranger.member_id, label="다른 가계", amount_krw="999"),
        "foreign",
    )
    for month in ["2020-01", "2026-10"]:
        result = summary(db_session, actor.principal, month)
        assert result.totals.earned_net_krw == "0" and result.totals.record_count == 0
        assert result.expected.known_amount_krw == "9007199254740993"
        assert result.expected.record_count == 3 and result.expected.unknown_count == 1
        assert len(result.expected.members) == 1
        assert result.expected.members[0].member_id == actor.member_id
        assert result.expected.members[0].known_amount_krw == "9007199254740993"
    assert db_session.scalar(select(func.count()).select_from(CashRecord)) == 0
    assert db_session.scalar(select(func.count()).select_from(AssetMonthRecord)) == 0
