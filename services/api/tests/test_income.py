"""Synthetic income facts, immutable replay, household boundaries and real DB races."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from test_accounts import make_actor

from sallimbook.accounts import service as accounts
from sallimbook.accounts.schemas import AccountCreate
from sallimbook.assets import month_service
from sallimbook.assets import service as asset_service
from sallimbook.assets.month_schemas import MonthDraft, MonthValueUpdate
from sallimbook.assets.schemas import AssetArchive
from sallimbook.cashflow import service
from sallimbook.cashflow.calculations import IncomeValue, income_totals
from sallimbook.cashflow.models import CashRecord, CashRecordRevision, IncomeConversion
from sallimbook.cashflow.router import router
from sallimbook.cashflow.schemas import CashInput, IncomeCreate, IncomePatch
from sallimbook.config import Settings
from sallimbook.core.audit import AuditEvent
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract
from sallimbook.core.idempotency import IdempotencyRecord
from sallimbook.core.types import MAX_KRW, month_start

CATALOG = json.loads(
    (Path(__file__).resolve().parents[3] / "packages/test-fixtures/catalog.json").read_text()
)


def test_income_contract_requires_mutation_headers_and_describes_resource_headers():
    app = FastAPI()
    app.include_router(router)
    for path, operations in app.openapi()["paths"].items():
        for method, operation in operations.items():
            if method not in {"post", "patch"}:
                continue
            headers = {p["name"]: p for p in operation["parameters"] if p["in"] == "header"}
            assert headers["Idempotency-Key"]["required"] is True
            if "{record_id}" in path:
                assert headers["If-Match"]["required"] is True
            if not path.endswith("/convert"):
                status = "201" if path.endswith(("income", "returns")) else "200"
                assert "ETag" in operation["responses"][status]["headers"]


def income_payload(actor=None, **overrides):
    return {
        "kind": "salary",
        "amount_krw": "3000000",
        "period_month": "2026-01",
        "date_precision": "month",
        "member_id": str(actor.member_id if actor else uuid4()),
        **overrides,
    }


def headers(actor, key=None, version=None):
    return {
        **actor.headers,
        "Idempotency-Key": key or str(uuid4()),
        **({"If-Match": f'"{version}"'} if version is not None else {}),
    }


@pytest.mark.parametrize("amount", ["0", 3000, 1.5, "-1", "01", "1.5", "1e3", str(MAX_KRW + 1)])
def test_income_requires_positive_exact_decimal_strings(amount):
    with pytest.raises(ValidationError):
        IncomeCreate(**income_payload(amount_krw=amount))


def test_month_precision_has_no_invented_date_and_day_can_differ_from_accrual_month():
    monthly = IncomeCreate(**income_payload())
    assert monthly.occurred_on is None
    daily = IncomeCreate(**income_payload(date_precision="day", occurred_on="2026-02-05"))
    assert daily.period_month == "2026-01" and daily.occurred_on.isoformat() == "2026-02-05"
    for values in (
        {"date_precision": "day"},
        {"occurred_on": "2026-01-01"},
        {"date_precision": "day", "occurred_on": "2026-01-01T00:00:00Z"},
    ):
        with pytest.raises(ValidationError):
            IncomeCreate(**income_payload(**values))


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "insurance_receipt"),
        ("kind", "medical_refund"),
        ("kind", "income_return"),
        ("flow", "out"),
        ("household_id", str(uuid4())),
        ("card_id", str(uuid4())),
        ("reverses_id", str(uuid4())),
        ("state", "void"),
        ("duplicate_acknowledged", "true"),
    ],
)
def test_income_schema_cannot_create_subtypes_or_inject_household_state_or_card(field, value):
    with pytest.raises(ValidationError):
        IncomeCreate(**income_payload(**{field: value}))


def test_actual_date_uses_seoul_today_without_restricting_accrual_month(monkeypatch):
    monkeypatch.setattr(service, "utcnow", lambda: datetime(2026, 1, 31, 15, 30, tzinfo=UTC))
    actual = CashInput(
        amount_krw="1", period_month="2026-12", date_precision="day", occurred_on="2026-02-01"
    )
    service._validate_actual_date(actual)
    service._validate_actual_date(
        CashInput(amount_krw="1", period_month="2026-12", date_precision="month")
    )
    with pytest.raises(DomainError) as rejected:
        service._validate_actual_date(
            actual.model_copy(update={"occurred_on": datetime(2026, 2, 2).date()})
        )
    assert rejected.value.code == "INVALID_OCCURRED_DATE"


def test_corrections_require_reason_and_preserve_omission_vs_clear():
    patch = IncomePatch(reason="합성 사유", note=None)
    assert patch.model_fields_set == {"reason", "note"}
    for values in (
        {"reason": "합성"},
        {"note": None},
        {"reason": " ", "note": None},
        {"reason": "합성", "member_id": None},
    ):
        with pytest.raises(ValidationError):
            IncomePatch(**values)


@pytest.mark.parametrize(
    "field", ["kind", "amount_krw", "period_month", "date_precision", "member_id"]
)
def test_income_patch_contract_allows_omission_but_not_null(field):
    schema = IncomePatch.model_json_schema()
    assert field not in schema["required"]
    assert "default" not in schema["properties"][field]
    assert '"null"' not in json.dumps(schema["properties"][field])
    assert IncomePatch(reason="합성", note=None).model_fields_set == {"reason", "note"}
    with pytest.raises(ValidationError):
        IncomePatch.model_validate({"reason": "합성", "note": None, field: None})


def test_income_projection_deduplicates_actual_insurance_sources_and_separates_returns():
    salary = IncomeValue("synthetic-salary", "salary", 3_000_000)
    receipt = IncomeValue("synthetic-payout", "insurance_receipt", 500_000)
    result = income_totals(
        [
            salary,
            receipt,
            receipt,
            IncomeValue("synthetic-return", "insurance_return", 50_000),
            IncomeValue("synthetic-income-return", "income_return", 100_000),
            IncomeValue("synthetic-void", "bonus", 900_000, "void"),
        ]
    )
    assert result["salary_krw"] == "3000000"
    assert result["earned_net_krw"] == "2900000"
    assert result["insurance_net_krw"] == "450000"
    assert result["net_inflow_krw"] == "3350000" and result["record_count"] == 4
    with pytest.raises(ValueError):
        income_totals([salary, IncomeValue(salary.source_id, "salary", 4_000_000)])
    # A return in a later month can create negative net inflow in that month.
    assert income_totals([IncomeValue("later", "income_return", 100)])["earned_net_krw"] == "-100"


@pytest.mark.parametrize("amount", [True, 1.5, Decimal("1.5"), Decimal("NaN"), 0, -1, MAX_KRW + 1])
def test_projection_rejects_invalid_amounts(amount):
    with pytest.raises(ValueError):
        IncomeValue("synthetic", "salary", amount)


def test_projection_preserves_large_integers_and_rejects_aggregate_overflow():
    assert (
        income_totals([IncomeValue("a", "salary", 9007199254740993)])["salary_krw"]
        == "9007199254740993"
    )
    with pytest.raises(ValueError):
        income_totals([IncomeValue("a", "salary", MAX_KRW), IncomeValue("b", "salary", 1)])


@pytest.fixture
def income_actors(db_engine):
    first = make_actor(db_engine)
    return first, make_actor(db_engine, first.household_id), make_actor(db_engine)


@pytest.fixture
def income_app(db_engine):
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(app)
    app.include_router(router)
    return app


def make_account(engine, actor):
    with Session(engine) as session:
        return accounts.create_account(
            session,
            actor.principal,
            AccountCreate(
                institution_name="합성 입금 기관",
                account_type="checking",
                asset={
                    "name": "합성 입금 자산",
                    "kind": "asset",
                    "category": "financial",
                    "ownership_kind": "joint",
                    "amount_basis": "owned",
                    "started_on": "2025-01-01",
                },
            ),
            None,
        )


def close_account(engine, actor, account, ended_on):
    with Session(engine) as session:
        asset_service.archive_asset(
            session, actor.principal, account.asset_id, AssetArchive(ended_on=ended_on), '"1"'
        )


def post_income(client, actor, *, key=None, **overrides):
    response = client.post(
        "/api/v1/income", json=income_payload(actor, **overrides), headers=headers(actor, key)
    )
    assert response.status_code == 201
    return response


@pytest.mark.database
class TestIncomeDatabase:
    def test_closed_account_accepts_records_dated_through_its_end(
        self, income_app, income_actors, db_engine
    ):
        actor = income_actors[0]
        account = make_account(db_engine, actor)
        with TestClient(income_app) as client:
            kept = post_income(client, actor, period_month="2026-02", account_id=str(account.id))
            other = post_income(client, actor, period_month="2026-02", kind="bonus")
            close_account(db_engine, actor, account, "2026-01-15")

            def create(**fields):
                body = income_payload(
                    actor, account_id=str(account.id), duplicate_acknowledged=True
                )
                return client.post("/api/v1/income", json=body | fields, headers=headers(actor))

            # Money that moved while the account was open can be entered later.
            assert create(date_precision="day", occurred_on="2026-01-15").status_code == 201
            assert create(period_month="2026-01").status_code == 201
            for late in (
                create(date_precision="day", occurred_on="2026-01-16"),
                create(period_month="2026-02"),
            ):
                assert late.status_code == 422
                assert late.json()["error"]["code"] == "ACCOUNT_UNAVAILABLE"
            # A correction keeps its original link; moving another record onto it does not.
            changed = client.patch(
                f"/api/v1/income/{kept.json()['id']}",
                headers=headers(actor, version=1),
                json={"amount_krw": "3100000", "reason": "합성 금액 정정"},
            )
            assert changed.status_code == 200, changed.text
            moved = client.patch(
                f"/api/v1/income/{other.json()['id']}",
                headers=headers(actor, version=1),
                json={"account_id": str(account.id), "reason": "합성 계좌 정정"},
            )
            assert moved.status_code == 422
            assert moved.json()["error"]["code"] == "ACCOUNT_UNAVAILABLE"

    def test_t08_income_never_mutates_real_monthly_snapshot(
        self, income_app, income_actors, db_engine
    ):
        actor = income_actors[0]
        account = make_account(db_engine, actor)
        vector = next(row for row in CATALOG["vectors"] if row["id"] == "T-08")
        with Session(db_engine) as session:
            reference = month_service.create_draft(
                session,
                actor.principal,
                "2026-01",
                MonthDraft(copy_previous=False),
                "synthetic-t08-draft",
            )
            month = month_service.get_month(session, actor.principal, "2026-01")
            value = month.values[0]
            month_service.update_value(
                session,
                actor.principal,
                "2026-01",
                account.asset_id,
                MonthValueUpdate(
                    revision_id=reference.revision_id,
                    value_id=value.id,
                    input_amount_krw=vector["inputs"]["snapshot_before_krw"],
                    as_of_date="2026-01-31",
                ),
                f'"{value.version}"',
            )
            before = month_service.get_month(session, actor.principal, "2026-01").model_dump(
                mode="json"
            )
        with TestClient(income_app) as client:
            response = post_income(
                client, actor, account_id=str(account.id), amount_krw=vector["inputs"]["income_krw"]
            )
            assert response.json()["occurred_on"] is None
        with Session(db_engine) as session:
            after = month_service.get_month(session, actor.principal, "2026-01").model_dump(
                mode="json"
            )
            assert after == before
            assert after["values"][0]["input_amount_krw"] == vector["inputs"]["snapshot_before_krw"]

    def test_original_idempotent_response_survives_correction_and_void(
        self, income_app, income_actors, db_engine
    ):
        actor = income_actors[0]
        with TestClient(income_app) as client:
            original = post_income(client, actor, key="synthetic-original")
            row = original.json()
            path = f"/api/v1/income/{row['id']}"
            changed = client.patch(
                path,
                headers=headers(actor, "synthetic-correct", 1),
                json={"amount_krw": "3100000", "reason": "합성 입력 정정"},
            )
            assert changed.status_code == 200 and changed.json()["version"] == 2
            replay = post_income(client, actor, key="synthetic-original")
            assert replay.json() == row and replay.headers["etag"] == '"1"'
            replay_correct = client.patch(
                path,
                headers=headers(actor, "synthetic-correct", 1),
                json={"amount_krw": "3100000", "reason": "합성 입력 정정"},
            )
            assert replay_correct.json() == changed.json()
            stale = client.patch(
                path,
                headers=headers(actor, "synthetic-stale", 1),
                json={"note": "합성", "reason": "합성"},
            )
            assert stale.status_code == 409
            voided = client.post(
                path + "/void",
                headers=headers(actor, "synthetic-void", 2),
                json={"reason": "합성 취소"},
            )
            assert voided.status_code == 200 and voided.json()["version"] == 3
            assert post_income(client, actor, key="synthetic-original").json() == row
            conflict = client.post(
                "/api/v1/income",
                headers=headers(actor, "synthetic-original"),
                json=income_payload(actor, amount_krw="3200000"),
            )
            assert conflict.status_code == 409
            history = client.get(path + "/history", headers=actor.headers).json()["items"]
            assert [item["version"] for item in history] == [3, 2, 1]
            assert [item["action"] for item in history] == ["void", "correct", "create"]
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 1
            assert session.scalar(select(func.count()).select_from(CashRecordRevision)) == 3

    def test_same_household_partner_can_correct_and_audit_stores_only_metadata(
        self, income_app, income_actors, db_engine
    ):
        actor, partner, _ = income_actors
        with TestClient(income_app) as client:
            row = post_income(client, actor, note="합성 원문 복제 금지").json()
            changed = client.patch(
                f"/api/v1/income/{row['id']}",
                headers=headers(partner, version=1),
                json={"amount_krw": "3333333", "reason": "합성 정정 사유"},
            )
            assert changed.status_code == 200
            assert changed.json()["updated_by_member_id"] == str(partner.member_id)
        with Session(db_engine) as session:
            events = list(
                session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "cash_record"))
            )
            data = json.dumps([event.safe_diff for event in events])
            assert "3333333" not in data and "합성 원문" not in data and "합성 정정" not in data
            assert events[-1].actor_id == partner.user_id

    def test_cross_household_resource_member_account_and_history_are_denied(
        self, income_app, income_actors, db_engine
    ):
        actor, _, foreign = income_actors
        foreign_account = make_account(db_engine, foreign)
        with TestClient(income_app) as client:
            row = post_income(client, actor).json()
            path = f"/api/v1/income/{row['id']}"
            for response in (
                client.get(path, headers=foreign.headers),
                client.get(path + "/history", headers=foreign.headers),
                client.patch(
                    path,
                    headers=headers(foreign, version=1),
                    json={"note": "합성", "reason": "합성"},
                ),
                client.post(
                    path + "/void", headers=headers(foreign, version=1), json={"reason": "합성"}
                ),
                client.post(
                    path + "/returns",
                    headers=headers(foreign, version=1),
                    json={
                        "amount_krw": "1",
                        "period_month": "2026-01",
                        "date_precision": "month",
                        "reason": "합성",
                    },
                ),
                client.post(
                    "/api/v1/income",
                    headers=headers(actor),
                    json=income_payload(actor, member_id=str(foreign.member_id)),
                ),
                client.post(
                    "/api/v1/income",
                    headers=headers(actor),
                    json=income_payload(actor, account_id=str(foreign_account.id)),
                ),
            ):
                assert response.status_code == 404
            assert (
                client.get("/api/v1/income/summary?month=2026-01", headers=foreign.headers).json()[
                    "totals"
                ]["record_count"]
                == 0
            )

    def test_database_composite_fk_rejects_foreign_member(self, income_actors, db_engine):
        actor, _, foreign = income_actors
        with Session(db_engine) as session:
            session.add(
                CashRecord(
                    household_id=actor.household_id,
                    member_id=foreign.member_id,
                    kind="salary",
                    flow="in",
                    amount_krw=Decimal(1),
                    period_month=month_start("2026-01"),
                    date_precision="month",
                    state="active",
                    created_by_member_id=actor.member_id,
                    updated_by_member_id=actor.member_id,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()

    def test_month_day_overlap_requires_acknowledgement_and_lists_candidates(
        self, income_app, income_actors
    ):
        actor = income_actors[0]
        with TestClient(income_app) as client:
            original = post_income(client, actor).json()
            daily = income_payload(actor, date_precision="day", occurred_on="2026-02-05")
            response = client.post("/api/v1/income", headers=headers(actor), json=daily)
            assert (
                response.status_code == 409
                and response.json()["error"]["code"] == "INCOME_DUPLICATE_SUSPECTED"
            )
            candidates = client.get(
                "/api/v1/income/duplicates",
                headers=actor.headers,
                params={
                    "month": "2026-01",
                    "member_id": str(actor.member_id),
                    "kind": "salary",
                    "date_precision": "day",
                },
            ).json()
            assert candidates["suspected"] and candidates["items"][0]["id"] == original["id"]
            accepted = client.post(
                "/api/v1/income",
                headers=headers(actor),
                json={**daily, "duplicate_acknowledged": True},
            )
            assert accepted.status_code == 201 and accepted.json()["occurred_on"] == "2026-02-05"

    def test_conversion_atomically_preserves_total_history_and_original_replay(
        self, income_app, income_actors
    ):
        actor = income_actors[0]
        with TestClient(income_app) as client:
            original = post_income(client, actor, amount_krw="1000").json()
            payload = {
                "sources": [{"id": original["id"], "version": 1}],
                "reason": "합성 일별 전환",
                "replacements": [
                    income_payload(
                        actor, amount_krw="400", date_precision="day", occurred_on="2026-01-10"
                    ),
                    income_payload(
                        actor, amount_krw="600", date_precision="day", occurred_on="2026-01-20"
                    ),
                ],
            }
            response = client.post(
                "/api/v1/income/convert", headers=headers(actor, "synthetic-convert"), json=payload
            )
            assert response.status_code == 201
            result = response.json()
            assert result["sources"][0]["state"] == "void" and len(result["replacements"]) == 2
            assert (
                client.get("/api/v1/income/summary?month=2026-01", headers=actor.headers).json()[
                    "totals"
                ]["earned_net_krw"]
                == "1000"
            )
            replacement = result["replacements"][0]
            assert (
                client.post(
                    f"/api/v1/income/{replacement['id']}/void",
                    headers=headers(actor, version=1),
                    json={"reason": "합성 오류"},
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/api/v1/income/convert",
                    headers=headers(actor, "synthetic-convert"),
                    json=payload,
                ).json()
                == result
            )

    def test_conversion_failure_rolls_back_sources_new_facts_audit_and_reservation(
        self, income_app, income_actors, db_engine, monkeypatch
    ):
        actor = income_actors[0]
        with TestClient(income_app) as client:
            original = post_income(client, actor, amount_krw="1000").json()
            prepare = service.prepare_cash_record
            calls = 0

            def fail_second(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise DomainError("INVALID_INCOME", "합성 전환 실패", 422)
                return prepare(*args, **kwargs)

            monkeypatch.setattr(service, "prepare_cash_record", fail_second)
            response = client.post(
                "/api/v1/income/convert",
                headers=headers(actor, "synthetic-rollback"),
                json={
                    "sources": [{"id": original["id"], "version": 1}],
                    "reason": "합성 전환",
                    "replacements": [
                        income_payload(
                            actor, amount_krw="400", date_precision="day", occurred_on="2026-01-10"
                        ),
                        income_payload(
                            actor, amount_krw="600", date_precision="day", occurred_on="2026-01-20"
                        ),
                    ],
                },
            )
            assert response.status_code == 422
        with Session(db_engine) as session:
            assert session.get(CashRecord, UUID(original["id"])).state == "active"
            for model, expected in (
                (CashRecord, 1),
                (CashRecordRevision, 1),
                (IncomeConversion, 0),
            ):
                assert session.scalar(select(func.count()).select_from(model)) == expected
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(IdempotencyRecord)
                    .where(IdempotencyRecord.key == "synthetic-rollback")
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.entity_type == "cash_record")
                )
                == 1
            )

    @pytest.mark.parametrize(
        "invalid,expected",
        [
            ("total", 422),
            ("precision", 422),
            ("member", 422),
            ("version", 409),
            ("foreign_source", 404),
            ("incomplete", 409),
            ("returned", 409),
            ("foreign_account", 404),
        ],
    )
    def test_invalid_conversion_preserves_originals_and_creates_no_conversion(
        self,
        income_app,
        income_actors,
        db_engine,
        invalid,
        expected,
    ):
        actor, partner, foreign = income_actors
        with TestClient(income_app) as client:
            original = post_income(client, actor, amount_krw="1000").json()
            source = {"id": original["id"], "version": 1}
            replacement = income_payload(
                actor, amount_krw="1000", date_precision="day", occurred_on="2026-01-10"
            )
            if invalid == "total":
                replacement["amount_krw"] = "999"
            elif invalid == "precision":
                replacement["date_precision"] = "month"
                replacement.pop("occurred_on")
            elif invalid == "member":
                replacement["member_id"] = str(partner.member_id)
            elif invalid == "version":
                source["version"] = 2
            elif invalid == "foreign_source":
                source["id"] = post_income(client, foreign, amount_krw="1000").json()["id"]
            elif invalid == "incomplete":
                post_income(client, actor, amount_krw="1000")
            elif invalid == "returned":
                assert (
                    client.post(
                        f"/api/v1/income/{original['id']}/returns",
                        headers=headers(actor, version=1),
                        json={
                            "amount_krw": "100",
                            "period_month": "2026-01",
                            "date_precision": "month",
                            "reason": "합성 반환",
                        },
                    ).status_code
                    == 201
                )
            else:
                replacement["account_id"] = str(make_account(db_engine, foreign).id)
            response = client.post(
                "/api/v1/income/convert",
                headers=headers(actor),
                json={"sources": [source], "replacements": [replacement], "reason": "합성 전환"},
            )
            assert response.status_code == expected
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(IncomeConversion)) == 0
            row = session.get(CashRecord, UUID(original["id"]))
            assert row.state == "active" and row.version == 1

    def test_concurrent_idempotent_creation_has_one_source_and_original_response(
        self, income_app, income_actors, db_engine
    ):
        actor = income_actors[0]
        barrier = Barrier(2)

        def submit():
            with TestClient(income_app) as client:
                barrier.wait(timeout=10)
                result = client.post(
                    "/api/v1/income",
                    headers=headers(actor, "synthetic-concurrent-key"),
                    json=income_payload(actor),
                )
                return result.status_code, result.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(submit), pool.submit(submit)
            results = [first.result(timeout=15), second.result(timeout=15)]
        assert results[0] == results[1] and results[0][0] == 201
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 1
            assert session.scalar(select(func.count()).select_from(CashRecordRevision)) == 1

    def test_concurrent_conversions_cannot_duplicate_replacements(
        self, income_app, income_actors, db_engine
    ):
        actor, partner, _ = income_actors
        with TestClient(income_app) as client:
            original = post_income(client, actor, amount_krw="1000").json()
        body = {
            "sources": [{"id": original["id"], "version": 1}],
            "reason": "합성 경쟁 전환",
            "replacements": [
                income_payload(
                    actor, amount_krw="1000", date_precision="day", occurred_on="2026-01-10"
                )
            ],
        }
        barrier = Barrier(2)

        def submit(user):
            with TestClient(income_app) as client:
                barrier.wait(timeout=10)
                return client.post(
                    "/api/v1/income/convert", headers=headers(user), json=body
                ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(submit, actor), pool.submit(submit, partner)
            assert sorted([first.result(timeout=15), second.result(timeout=15)]) == [201, 409]
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(CashRecord).where(CashRecord.state == "active")
                )
                == 1
            )
            assert session.scalar(select(func.count()).select_from(IncomeConversion)) == 1

    def test_return_bounds_block_original_changes_and_void_releases_bound(
        self, income_app, income_actors
    ):
        actor = income_actors[0]
        with TestClient(income_app) as client:
            original = post_income(client, actor, amount_krw="1000").json()
            path = f"/api/v1/income/{original['id']}"
            body = {
                "amount_krw": "600",
                "period_month": "2026-02",
                "date_precision": "day",
                "occurred_on": "2026-02-10",
                "reason": "합성 실제 반환",
            }
            returned = client.post(
                path + "/returns", headers=headers(actor, "synthetic-return", 1), json=body
            )
            assert returned.status_code == 201 and returned.json()["kind"] == "income_return"
            assert returned.json()["reverses_id"] == original["id"]
            assert (
                client.post(
                    path + "/returns", headers=headers(actor, "synthetic-return", 1), json=body
                ).json()
                == returned.json()
            )
            assert (
                client.post(
                    path + "/returns", headers=headers(actor, version=1), json=body
                ).status_code
                == 409
            )
            assert (
                client.post(
                    path + "/void", headers=headers(actor, version=1), json={"reason": "합성"}
                ).status_code
                == 409
            )
            assert (
                client.patch(
                    path,
                    headers=headers(actor, version=1),
                    json={"amount_krw": "900", "reason": "합성"},
                ).status_code
                == 409
            )
            assert (
                client.get("/api/v1/income/summary?month=2026-02", headers=actor.headers).json()[
                    "totals"
                ]["earned_net_krw"]
                == "-600"
            )
            assert (
                client.post(
                    f"/api/v1/income/{returned.json()['id']}/void",
                    headers=headers(actor, version=1),
                    json={"reason": "합성 오입력"},
                ).status_code
                == 200
            )
            assert (
                client.post(
                    path + "/returns",
                    headers=headers(actor, version=1),
                    json={**body, "amount_krw": "1000"},
                ).status_code
                == 201
            )

    def test_concurrent_returns_cannot_exceed_original(self, income_app, income_actors, db_engine):
        actor, partner, _ = income_actors
        with TestClient(income_app) as client:
            original = post_income(client, actor, amount_krw="1000").json()
        barrier = Barrier(2)

        def submit(user):
            with TestClient(income_app) as client:
                barrier.wait(timeout=10)
                return client.post(
                    f"/api/v1/income/{original['id']}/returns",
                    headers=headers(user, version=1),
                    json={
                        "amount_krw": "600",
                        "period_month": "2026-01",
                        "date_precision": "month",
                        "reason": "합성 경쟁 반환",
                    },
                ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(submit, actor), pool.submit(submit, partner)
            assert sorted([first.result(timeout=15), second.result(timeout=15)]) == [201, 409]
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.sum(CashRecord.amount_krw)).where(
                        CashRecord.kind == "income_return"
                    )
                )
                == 600
            )

    def test_concurrent_month_day_creations_serialize_duplicate_detection(
        self, income_app, income_actors, db_engine
    ):
        actor, partner, _ = income_actors
        barrier = Barrier(2)

        def submit(user, daily):
            body = income_payload(
                actor, **({"date_precision": "day", "occurred_on": "2026-01-10"} if daily else {})
            )
            with TestClient(income_app) as client:
                barrier.wait(timeout=10)
                return client.post("/api/v1/income", headers=headers(user), json=body).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(submit, actor, False), pool.submit(submit, partner, True)
            assert sorted([first.result(timeout=15), second.result(timeout=15)]) == [201, 409]
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 1

    def test_shared_helper_rolls_back_without_committing_subtype_failure(
        self, income_actors, db_engine
    ):
        actor = income_actors[0]
        with Session(db_engine) as session:
            row = service.prepare_cash_record(
                session,
                actor.principal,
                CashInput(
                    amount_krw="500000",
                    period_month="2026-01",
                    date_precision="day",
                    occurred_on="2026-01-10",
                ),
                kind="insurance_receipt",
            )
            assert row.id is not None
            session.rollback()  # A later subtype validation/write rejected the complete operation.
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 0
            assert session.scalar(select(func.count()).select_from(CashRecordRevision)) == 0

    def test_subtype_projection_is_read_only_in_income_api(
        self, income_app, income_actors, db_engine
    ):
        actor = income_actors[0]
        # Synthetic internal fact models the future payout service's committed source.
        with Session(db_engine) as session:
            row = service.prepare_cash_record(
                session,
                actor.principal,
                CashInput(
                    amount_krw="500000",
                    period_month="2026-01",
                    date_precision="day",
                    occurred_on="2026-01-10",
                ),
                kind="insurance_receipt",
            )
            record_id = row.id
            session.commit()
        with TestClient(income_app) as client:
            summary = client.get(
                "/api/v1/income/summary?month=2026-01", headers=actor.headers
            ).json()
            assert (
                summary["totals"]["insurance_receipts_krw"] == "500000"
                and summary["totals"]["salary_krw"] == "0"
            )
            path = f"/api/v1/income/{record_id}"
            assert client.get(path, headers=actor.headers).json()["editable"] is False
            assert (
                client.patch(
                    path,
                    headers=headers(actor, version=1),
                    json={"amount_krw": "100", "reason": "합성"},
                ).status_code
                == 409
            )
            assert (
                client.post(
                    path + "/void", headers=headers(actor, version=1), json={"reason": "합성"}
                ).status_code
                == 409
            )
            assert (
                client.post(
                    path + "/returns",
                    headers=headers(actor, version=1),
                    json={
                        "amount_krw": "100",
                        "period_month": "2026-01",
                        "date_precision": "month",
                        "reason": "합성",
                    },
                ).status_code
                == 409
            )

    @pytest.mark.parametrize(
        "target,operation",
        [
            (CashRecordRevision, "update"),
            (CashRecordRevision, "delete"),
            (IncomeConversion, "update"),
            (IncomeConversion, "delete"),
        ],
    )
    def test_immutable_replay_sources_reject_database_updates_and_deletes(
        self,
        income_app,
        income_actors,
        db_engine,
        target,
        operation,
    ):
        actor = income_actors[0]
        with TestClient(income_app) as client:
            original = post_income(client, actor, amount_krw="1000").json()
            response = client.post(
                "/api/v1/income/convert",
                headers=headers(actor),
                json={
                    "sources": [{"id": original["id"], "version": 1}],
                    "reason": "합성 전환",
                    "replacements": [
                        income_payload(
                            actor, amount_krw="1000", date_precision="day", occurred_on="2026-01-10"
                        )
                    ],
                },
            )
            assert response.status_code == 201
        with Session(db_engine) as session:
            statement = (
                update(target).values(reason="합성 금지 변경")
                if operation == "update"
                else delete(target)
            )
            with pytest.raises(DBAPIError) as rejected:
                session.execute(statement)
            assert rejected.value.orig.sqlstate == "55000"
            session.rollback()
            assert session.scalar(select(func.count()).select_from(target)) > 0

    def test_mutations_require_authentication_and_idempotency_keys(self, income_app, income_actors):
        actor = income_actors[0]
        with TestClient(income_app) as client:
            assert client.post("/api/v1/income", json=income_payload(actor)).status_code == 401
            assert (
                client.post(
                    "/api/v1/income", headers=actor.headers, json=income_payload(actor)
                ).status_code
                == 400
            )
            assert client.get("/api/v1/income?month=2026-01").status_code == 401

    def test_current_capabilities_follow_returns_while_receipts_and_history_stay_immutable(
        self, income_app, income_actors
    ):
        actor = income_actors[0]
        with TestClient(income_app) as client:
            original = post_income(
                client, actor, key="synthetic-capability", amount_krw="1000"
            ).json()
            path = f"/api/v1/income/{original['id']}"
            duplicate_path = (
                "/api/v1/income/duplicates?month=2026-01&kind=salary&date_precision=day"
                f"&member_id={actor.member_id}"
            )

            def capabilities(expected):
                detail = client.get(path, headers=actor.headers).json()
                listed = client.get("/api/v1/income?month=2026-01", headers=actor.headers).json()
                duplicates = client.get(duplicate_path, headers=actor.headers).json()
                for row in [detail, listed["items"][0], duplicates["items"][0]]:
                    assert row["id"] == original["id"]
                    assert row["editable"] is expected and row["voidable"] is expected

            assert original["editable"] is False and original["voidable"] is False
            capabilities(True)
            old_history = client.get(path + "/history", headers=actor.headers).json()
            returned = client.post(
                path + "/returns",
                headers=headers(actor, version=1),
                json={
                    "amount_krw": "400",
                    "period_month": "2026-02",
                    "date_precision": "month",
                    "reason": "합성 실제 반환",
                },
            )
            assert returned.status_code == 201
            capabilities(False)
            assert (
                post_income(client, actor, key="synthetic-capability", amount_krw="1000").json()
                == original
            )
            assert client.get(path + "/history", headers=actor.headers).json() == old_history
            return_path = f"/api/v1/income/{returned.json()['id']}"
            return_current = client.get(return_path, headers=actor.headers).json()
            assert return_current["editable"] is False and return_current["voidable"] is True
            assert (
                client.post(
                    return_path + "/void",
                    headers=headers(actor, version=1),
                    json={"reason": "합성 반환 무효"},
                ).status_code
                == 200
            )
            capabilities(True)
            assert (
                client.post(
                    path + "/void", headers=headers(actor, version=1), json={"reason": "합성 무효"}
                ).status_code
                == 200
            )
            detail = client.get(path, headers=actor.headers).json()
            assert detail["editable"] is False and detail["voidable"] is False

    @pytest.mark.parametrize("read", ["list", "duplicates"])
    def test_capability_reads_use_constant_queries(
        self, income_app, income_actors, db_engine, read
    ):
        actor = income_actors[0]
        with TestClient(income_app) as client:
            post_income(client, actor)
            counts = []
            for size in (1, 8):
                if size > 1:
                    for _ in range(size - 1):
                        post_income(client, actor)
                statements = []

                def capture(
                    connection,
                    cursor,
                    statement,
                    parameters,
                    context,
                    executemany,
                    captured=statements,
                ):
                    if statement.lstrip().upper().startswith("SELECT"):
                        captured.append(statement)

                event.listen(db_engine, "before_cursor_execute", capture)
                try:
                    with Session(db_engine) as session:
                        if read == "list":
                            result = service.list_income(session, actor.principal, "2026-01")
                        else:
                            result = service.duplicates(
                                session,
                                actor.principal,
                                month="2026-01",
                                kind="salary",
                                member_id=actor.member_id,
                                date_precision="day",
                            )
                        assert len(result.items) == size
                        assert all(row.editable and row.voidable for row in result.items)
                finally:
                    event.remove(db_engine, "before_cursor_execute", capture)
                counts.append(len(statements))
            assert counts[0] == counts[1]
            assert counts[1] <= 5
