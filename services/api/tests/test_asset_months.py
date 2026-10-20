"""Synthetic monthly observations, exact money and immutable historical revisions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from test_accounts import asset_payload, create_account, make_actor
from test_asset_calculations import vector
from test_pagination import api_pages, ids, pairs

from sallimbook.accounts.router import router as account_router
from sallimbook.assets import month_service
from sallimbook.assets.calculations import AssetMonth, AssetValue, compare_months
from sallimbook.assets.month_models import AssetMonthRecord, AssetMonthRevision, AssetMonthValue
from sallimbook.assets.month_router import router as month_router
from sallimbook.assets.month_schemas import MonthConfirm, MonthDraft, MonthReopen, MonthValueUpdate
from sallimbook.assets.router import router as asset_router
from sallimbook.config import Settings
from sallimbook.core.audit import AuditEvent
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract
from sallimbook.identity.router import router as identity_router

SYNTHETIC_REVISION = UUID("00000000-0000-4000-8000-000000000001")


def test_month_openapi_describes_required_mutation_headers():
    app = FastAPI()
    app.include_router(month_router)
    paths = app.openapi()["paths"]
    expected = {
        "/{month}/draft": {"Idempotency-Key"},
        "/{month}/values/{asset_id}": {"If-Match"},
        "/{month}/sync-scope": {"If-Match"},
        "/{month}/confirm": {"If-Match", "Idempotency-Key"},
        "/{month}/reopen": {"If-Match", "Idempotency-Key"},
        "/{month}/carry-previous": {"If-Match", "Idempotency-Key"},
    }
    for suffix, names in expected.items():
        operation = paths["/api/v1/asset-months" + suffix][
            "patch" if "values" in suffix else "post"
        ]
        headers = {p["name"]: p for p in operation["parameters"] if p["in"] == "header"}
        for name in names:
            assert headers[name]["required"] is True
            assert headers[name]["schema"]["type"] == "string"
        status = "201" if suffix.endswith(("draft", "reopen")) else "200"
        response_headers = operation["responses"][status]["headers"]
        assert "ETag" in response_headers
        assert ("Location" in response_headers) == ("values" not in suffix)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"input_amount_krw": 0, "as_of_date": "2026-01-31"},
        {"input_amount_krw": "1.2", "as_of_date": "2026-01-31"},
        {"input_amount_krw": "-1", "as_of_date": "2026-01-31"},
        {"input_amount_krw": "1e3", "as_of_date": "2026-01-31"},
        {"input_amount_krw": "1"},
        {"input_amount_krw": "0", "as_of_date": "2026-01-31T00:00:00Z"},
        {"unchanged": True},
        {"unchanged": True, "as_of_date": "2026-01-31", "input_amount_krw": None},
        {"input_amount_krw": None, "verification_state": "verified"},
    ],
)
def test_invalid_month_values(payload):
    with pytest.raises(ValidationError):
        MonthValueUpdate.model_validate(
            {"revision_id": SYNTHETIC_REVISION, "value_id": SYNTHETIC_REVISION, **payload}
        )


def test_missing_zero_and_explicit_unchanged_are_different():
    missing = MonthValueUpdate(
        revision_id=SYNTHETIC_REVISION, value_id=SYNTHETIC_REVISION, input_amount_krw=None
    )
    zero = MonthValueUpdate(
        revision_id=SYNTHETIC_REVISION,
        value_id=SYNTHETIC_REVISION,
        input_amount_krw="0",
        as_of_date="2026-01-31",
    )
    unchanged = MonthValueUpdate(
        revision_id=SYNTHETIC_REVISION,
        value_id=SYNTHETIC_REVISION,
        unchanged=True,
        as_of_date="2026-01-31",
    )
    assert missing.input_amount_krw is None and not missing.unchanged
    assert zero.input_amount_krw == "0" and not zero.unchanged
    assert "input_amount_krw" not in unchanged.model_fields_set and unchanged.unchanged


@pytest.mark.parametrize("reason", [None, "", "   ", "a" * 1001])
def test_reopening_requires_a_meaningful_reason(reason):
    with pytest.raises(ValidationError):
        MonthReopen(revision_id=SYNTHETIC_REVISION, reason=reason)


def test_share_change_warns_and_does_not_enter_same_scope_delta():
    before = AssetMonth(
        "2026-01",
        (AssetValue("home", 500, household_share=Decimal("0.5")), AssetValue("cash", 100)),
        "confirmed",
    )
    after = AssetMonth(
        "2026-02",
        (AssetValue("home", 1000, household_share=Decimal("1")), AssetValue("cash", 120)),
        "confirmed",
    )
    result = compare_months(before, after)
    assert result.total_delta_krw == 520
    assert result.common_scope_delta_krw == 20
    assert result.scope_changed is True and result.changed_share_asset_ids == ("home",)


def test_equivalent_decimal_shares_keep_the_same_scope():
    before = AssetMonth(
        "2026-01", (AssetValue("home", 100, household_share=Decimal("0.50")),), "confirmed"
    )
    after = AssetMonth(
        "2026-02", (AssetValue("home", 101, household_share=Decimal("0.5")),), "confirmed"
    )
    result = compare_months(before, after)
    assert result.scope_changed is False and result.common_scope_delta_krw == 1


@pytest.fixture
def account_actor(db_engine):
    return make_actor(db_engine)


@pytest.fixture
def months_app(db_engine):
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(environment="test", _env_file=None)
    install_http_contract(app)
    for router in (identity_router, asset_router, account_router, month_router):
        app.include_router(router)
    return app


def add_asset(client, actor, **changes):
    response = client.post("/api/v1/assets", json=asset_payload(**changes), headers=actor.headers)
    assert response.status_code == 201
    return response.json()


def draft(client, actor, month, *, key=None, copy=True):
    response = client.post(
        f"/api/v1/asset-months/{month}/draft",
        json={"copy_previous": copy},
        headers={**actor.headers, "Idempotency-Key": key or uuid4().hex},
    )
    assert response.status_code == 201
    return response.json()


def read_month(client, actor, month, **params):
    response = client.get(f"/api/v1/asset-months/{month}", params=params, headers=actor.headers)
    assert response.status_code == 200
    return response.json()


def observe(client, actor, month, asset_id, amount, as_of_date, **extra):
    current = read_month(client, actor, month, limit=200)
    row = next(item for item in current["values"] if item["asset_id"] == asset_id)
    response = client.patch(
        f"/api/v1/asset-months/{month}/values/{asset_id}",
        json={
            "revision_id": current["revision_id"],
            "value_id": row["id"],
            "input_amount_krw": amount,
            "as_of_date": as_of_date,
            **extra,
        },
        headers={**actor.headers, "If-Match": f'"{row["version"]}"'},
    )
    assert response.status_code == 200
    return response.json()


def confirm(client, actor, month, *, key=None, **acknowledgments):
    current = read_month(client, actor, month)
    return client.post(
        f"/api/v1/asset-months/{month}/confirm",
        json={"revision_id": current["revision_id"], **acknowledgments},
        headers={
            **actor.headers,
            "If-Match": f'"{current["version"]}"',
            "Idempotency-Key": key or uuid4().hex,
        },
    )


@pytest.mark.database
class TestAssetMonthsDatabase:
    def test_month_values_list_assets_before_liabilities_by_name_across_pages(
        self, months_app, account_actor
    ):
        names = [
            ("나 예금", {}),
            ("가 대출", {"kind": "liability", "category": "loan"}),
            ("가 예금", {}),
            ("나 예금", {}),
            ("다 대출", {"kind": "liability", "category": "loan"}),
        ]
        with TestClient(months_app) as client:
            assets = [
                add_asset(client, account_actor, name=name, **extra)["id"] for name, extra in names
            ]
            draft(client, account_actor, "2026-01")
            pages = api_pages(
                client,
                account_actor,
                "/api/v1/asset-months/2026-01",
                items="values",
                cursor_key="asset_id",
            )
            expected = [assets[2], *sorted([assets[0], assets[3]]), assets[1], assets[4]]
            assert ids(pages, "asset_id") == pairs(expected)

    def test_carry_previous_fills_only_untouched_missing_rows_once(
        self, months_app, account_actor, db_engine
    ):
        with TestClient(months_app) as client:
            kept = add_asset(client, account_actor, name="합성 직접 입력")
            filled = add_asset(client, account_actor, name="합성 미입력")
            cleared = add_asset(client, account_actor, name="합성 직접 비움")
            switched = add_asset(
                client,
                account_actor,
                name="합성 기준 변경",
                amount_basis="whole",
                household_share="0.5",
            )
            draft(client, account_actor, "2026-01")
            for asset, amount in [
                (kept, "100"),
                (filled, "200"),
                (cleared, "300"),
                (switched, "400"),
            ]:
                observe(client, account_actor, "2026-01", asset["id"], amount, "2026-01-31")
            # M5: a February draft made before January was confirmed is all missing.
            draft(client, account_actor, "2026-02")
            assert confirm(client, account_actor, "2026-01").status_code == 200
            january = read_month(client, account_actor, "2026-01")["revision_id"]
            observe(client, account_actor, "2026-02", kept["id"], "150", "2026-02-28")
            observe(
                client,
                account_actor,
                "2026-02",
                cleared["id"],
                None,
                None,
                change_reason="합성 확인 불가",
            )
            assert (
                client.patch(
                    f"/api/v1/assets/{switched['id']}",
                    json={"amount_basis": "owned"},
                    headers={**account_actor.headers, "If-Match": f'"{switched["version"]}"'},
                ).status_code
                == 200
            )
            stale = read_month(client, account_actor, "2026-02")
            assert (
                client.post(
                    "/api/v1/asset-months/2026-02/sync-scope",
                    json={"revision_id": stale["revision_id"]},
                    headers={**account_actor.headers, "If-Match": f'"{stale["version"]}"'},
                ).status_code
                == 200
            )
            current = read_month(client, account_actor, "2026-02", limit=200)
            key = uuid4().hex

            def carry(idempotency_key):
                return client.post(
                    "/api/v1/asset-months/2026-02/carry-previous",
                    json={"revision_id": current["revision_id"]},
                    headers={
                        **account_actor.headers,
                        "If-Match": f'"{current["version"]}"',
                        "Idempotency-Key": idempotency_key,
                    },
                )

            first = carry(key)
            assert first.status_code == 200
            assert carry(key).json() == first.json()
            assert carry(uuid4().hex).json()["error"]["code"] == "VERSION_CONFLICT"
            rows = {
                r["asset_id"]: r
                for r in read_month(client, account_actor, "2026-02", limit=200)["values"]
            }
            row = rows[filled["id"]]
            assert (
                row["input_amount_krw"],
                row["verification_state"],
                row["origin"],
                row["origin_revision_id"],
                row["as_of_date"],
            ) == ("200", "carried_unconfirmed", "carried", january, None)
            assert (
                rows[kept["id"]]["input_amount_krw"],
                rows[kept["id"]]["verification_state"],
            ) == ("150", "verified")
            assert rows[cleared["id"]]["input_amount_krw"] is None
            assert rows[switched["id"]]["input_amount_krw"] is None
        with Session(db_engine) as session:
            diffs = [
                e.safe_diff
                for e in session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.entity_id == UUID(current["revision_id"]),
                        AuditEvent.action == "update",
                    )
                )
            ]
            assert diffs.count({"changed_fields": ["origin", "origin_revision_id", "values"]}) == 1

    def test_carry_previous_requires_a_confirmed_previous_month_and_an_open_revision(
        self, months_app, account_actor, db_engine
    ):
        stranger = make_actor(db_engine)
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor)
            draft(client, account_actor, "2026-01")

            def carry(actor):
                current = read_month(client, account_actor, "2026-01")
                return client.post(
                    "/api/v1/asset-months/2026-01/carry-previous",
                    json={"revision_id": current["revision_id"]},
                    headers={
                        **actor.headers,
                        "If-Match": f'"{current["version"]}"',
                        "Idempotency-Key": uuid4().hex,
                    },
                )

            assert carry(account_actor).json()["error"]["code"] == "PREVIOUS_MONTH_UNCONFIRMED"
            assert carry(stranger).json()["error"]["code"] == "MONTH_NOT_FOUND"
            observe(client, account_actor, "2026-01", asset["id"], "100", "2026-01-31")
            assert confirm(client, account_actor, "2026-01").status_code == 200
            assert carry(account_actor).json()["error"]["code"] == "MONTH_CONFIRMED"

    def test_future_month_draft_is_rejected_until_the_seoul_month_starts(
        self, months_app, account_actor, monkeypatch
    ):
        # 2026-01-31 23:59:59 Asia/Seoul
        monkeypatch.setattr(
            month_service, "utcnow", lambda: datetime(2026, 1, 31, 14, 59, 59, tzinfo=UTC)
        )
        key = uuid4().hex
        with TestClient(months_app) as client:
            add_asset(client, account_actor)
            early = client.post(
                "/api/v1/asset-months/2026-02/draft",
                json={"copy_previous": True},
                headers={**account_actor.headers, "Idempotency-Key": key},
            )
            assert early.status_code == 422
            assert early.json()["error"]["code"] == "MONTH_IN_FUTURE"
            assert (
                client.get(
                    "/api/v1/asset-months/2026-02", headers=account_actor.headers
                ).status_code
                == 404
            )
            monkeypatch.setattr(
                month_service, "utcnow", lambda: datetime(2026, 1, 31, 15, 0, tzinfo=UTC)
            )
            assert draft(client, account_actor, "2026-02", key=key)["month"] == "2026-02"

    def test_basis_change_clears_carried_origin_with_the_amount(self, months_app, account_actor):
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor, amount_basis="whole", household_share="0.5")
            draft(client, account_actor, "2026-01")
            observe(client, account_actor, "2026-01", asset["id"], "100", "2026-01-31")
            assert confirm(client, account_actor, "2026-01").status_code == 200
            draft(client, account_actor, "2026-02")
            assert read_month(client, account_actor, "2026-02")["values"][0]["origin"] == "carried"
            assert (
                client.patch(
                    f"/api/v1/assets/{asset['id']}",
                    json={"amount_basis": "owned"},
                    headers={**account_actor.headers, "If-Match": f'"{asset["version"]}"'},
                ).status_code
                == 200
            )
            before = read_month(client, account_actor, "2026-02")
            assert (
                client.post(
                    "/api/v1/asset-months/2026-02/sync-scope",
                    json={"revision_id": before["revision_id"]},
                    headers={**account_actor.headers, "If-Match": f'"{before["version"]}"'},
                ).status_code
                == 200
            )
            row = read_month(client, account_actor, "2026-02")["values"][0]
            assert (
                row["input_amount_krw"],
                row["verification_state"],
                row["origin"],
                row["origin_revision_id"],
            ) == (None, "missing", "manual", None)

    @pytest.mark.parametrize("during_confirmation", [False, True])
    def test_revision_origin_cannot_be_rewritten_before_or_during_confirmation(
        self, months_app, account_actor, db_engine, during_confirmation
    ):
        spouse = make_actor(db_engine, account_actor.household_id)
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor)
            draft(client, account_actor, "2026-01")
            observe(client, account_actor, "2026-01", asset["id"], "100", "2026-01-31")
            assert confirm(client, account_actor, "2026-01").status_code == 200
            first = read_month(client, account_actor, "2026-01")
            current = first
            for number in (2, 3):
                response = client.post(
                    "/api/v1/asset-months/2026-01/reopen",
                    json={"revision_id": current["revision_id"], "reason": f"합성 정정 {number}"},
                    headers={
                        **account_actor.headers,
                        "If-Match": f'"{current["version"]}"',
                        "Idempotency-Key": uuid4().hex,
                    },
                )
                assert response.status_code == 201
                current = read_month(client, account_actor, "2026-01")
                if number == 2:
                    assert confirm(client, account_actor, "2026-01").status_code == 200
                    current = read_month(client, account_actor, "2026-01")
            for change in (
                {"previous_revision_id": UUID(first["revision_id"])},
                {"reopened_reason": "합성 위조 사유"},
                {"created_by_member_id": spouse.member_id},
                {"created_at": datetime.now(UTC) - timedelta(days=1)},
            ):
                if during_confirmation:
                    change.update(
                        state="confirmed",
                        confirmed_at=datetime.now(UTC),
                        confirmed_by_member_id=account_actor.member_id,
                    )
                with Session(db_engine) as session, pytest.raises(DBAPIError) as caught:
                    session.execute(
                        update(AssetMonthRevision)
                        .where(AssetMonthRevision.id == UUID(current["revision_id"]))
                        .values(**change)
                    )
                    session.commit()
                assert caught.value.orig.sqlstate == "55000"
            assert confirm(client, account_actor, "2026-01").status_code == 200
            assert read_month(client, account_actor, "2026-01")["reopened_reason"] == "합성 정정 3"

    def test_scope_recreation_does_not_reuse_a_stale_value_identity(
        self, months_app, account_actor
    ):
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor)
            draft(client, account_actor, "2026-01")
            initial = read_month(client, account_actor, "2026-01")
            original_value = initial["values"][0]
            for changed_date in ("2026-02-01", "2025-01-01"):
                asset_response = client.patch(
                    f"/api/v1/assets/{asset['id']}",
                    json={"started_on": changed_date},
                    headers={**account_actor.headers, "If-Match": f'"{asset["version"]}"'},
                )
                assert asset_response.status_code == 200
                asset = asset_response.json()
                current = read_month(client, account_actor, "2026-01")
                synced = client.post(
                    "/api/v1/asset-months/2026-01/sync-scope",
                    json={"revision_id": current["revision_id"]},
                    headers={**account_actor.headers, "If-Match": f'"{current["version"]}"'},
                )
                assert synced.status_code == 200
            current = read_month(client, account_actor, "2026-01")
            assert current["revision_id"] == initial["revision_id"]
            assert current["values"][0]["version"] == original_value["version"] == 1
            assert current["values"][0]["id"] != original_value["id"]
            stale = client.patch(
                f"/api/v1/asset-months/2026-01/values/{asset['id']}",
                json={
                    "revision_id": initial["revision_id"],
                    "value_id": original_value["id"],
                    "input_amount_krw": "100",
                    "as_of_date": "2026-01-31",
                },
                headers={**account_actor.headers, "If-Match": '"1"'},
            )
            assert stale.status_code == 409 and stale.json()["error"]["code"] == "VALUE_CONFLICT"
            assert (
                read_month(client, account_actor, "2026-01")["values"][0]["input_amount_krw"]
                is None
            )

    def test_web_csrf_and_unauthenticated_requests_cannot_create_months(
        self, months_app, account_actor, db_engine
    ):
        origin = "https://sallimbook.test"
        months_app.state.settings.allowed_origins = [origin]
        with TestClient(months_app, base_url=origin) as client:
            assert client.get("/api/v1/asset-months/2026-01").status_code == 401
            login = client.post(
                "/api/v1/auth/web/login",
                headers={"Origin": origin},
                json={
                    "login_name": account_actor.login_name,
                    "password": account_actor.password,
                    "device_label": "합성 월 기록 브라우저",
                },
            )
            assert login.status_code == 200
            headers = {"Origin": origin, "Idempotency-Key": uuid4().hex}
            assert (
                client.post(
                    "/api/v1/asset-months/2026-01/draft", json={}, headers=headers
                ).status_code
                == 403
            )
            with Session(db_engine) as session:
                assert session.scalar(select(func.count()).select_from(AssetMonthRecord)) == 0
            response = client.post(
                "/api/v1/asset-months/2026-01/draft",
                json={},
                headers={
                    **headers,
                    "X-CSRF-Token": login.json()["csrf_token"],
                },
            )
            assert response.status_code == 201 and response.headers["cache-control"] == "no-store"

    @pytest.mark.parametrize("observed_on", ["2025-12-31", "2026-02-01"])
    def test_out_of_month_observation_dates_are_rejected(
        self, months_app, account_actor, observed_on
    ):
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor)
            draft(client, account_actor, "2026-01")
            current = read_month(client, account_actor, "2026-01")
            response = client.patch(
                f"/api/v1/asset-months/2026-01/values/{asset['id']}",
                json={
                    "revision_id": current["revision_id"],
                    "value_id": current["values"][0]["id"],
                    "input_amount_krw": "0",
                    "as_of_date": observed_on,
                },
                headers={**account_actor.headers, "If-Match": '"1"'},
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "INVALID_AS_OF_DATE"

    def test_total_overflow_rolls_back_observation_and_audit(
        self, months_app, account_actor, db_engine
    ):
        with TestClient(months_app) as client:
            first, second = add_asset(client, account_actor), add_asset(client, account_actor)
            draft(client, account_actor, "2026-01")
            maximum = "9" * 20
            observe(client, account_actor, "2026-01", first["id"], maximum, "2026-01-31")
            before = read_month(client, account_actor, "2026-01")
            row = next(item for item in before["values"] if item["asset_id"] == second["id"])
            failed = client.patch(
                f"/api/v1/asset-months/2026-01/values/{second['id']}",
                json={
                    "revision_id": before["revision_id"],
                    "value_id": row["id"],
                    "input_amount_krw": maximum,
                    "as_of_date": "2026-01-31",
                },
                headers={**account_actor.headers, "If-Match": f'"{row["version"]}"'},
            )
            assert (
                failed.status_code == 422 and failed.json()["error"]["code"] == "TOTAL_OUT_OF_RANGE"
            )
            assert read_month(client, account_actor, "2026-01") == before
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.entity_type == "asset_month",
                        AuditEvent.action == "update",
                    )
                )
                == 1
            )

    def test_parallel_draft_replay_creates_one_revision(self, months_app, account_actor, db_engine):
        with TestClient(months_app) as client:
            add_asset(client, account_actor)
        barrier = Barrier(2)
        key = uuid4().hex

        def submit():
            with Session(db_engine) as session:
                barrier.wait(timeout=10)
                return month_service.create_draft(
                    session, account_actor.principal, "2026-01", MonthDraft(), key
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        assert results[0] == results[1]
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(AssetMonthRevision)) == 1
            assert session.scalar(select(func.count()).select_from(AssetMonthValue)) == 1

    def test_parallel_value_edit_and_confirmation_have_one_winner(
        self, months_app, account_actor, db_engine
    ):
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor)
            draft(client, account_actor, "2026-01")
            observe(client, account_actor, "2026-01", asset["id"], "10", "2026-01-31")
            original = read_month(client, account_actor, "2026-01")
        barrier = Barrier(2)
        row = original["values"][0]

        def perform(action):
            with Session(db_engine) as session:
                barrier.wait(timeout=10)
                try:
                    if action == "confirm":
                        month_service.confirm_month(
                            session,
                            account_actor.principal,
                            "2026-01",
                            MonthConfirm(revision_id=original["revision_id"]),
                            f'"{original["version"]}"',
                            uuid4().hex,
                        )
                    else:
                        month_service.update_value(
                            session,
                            account_actor.principal,
                            "2026-01",
                            UUID(asset["id"]),
                            MonthValueUpdate(
                                revision_id=original["revision_id"],
                                value_id=row["id"],
                                input_amount_krw="11",
                                as_of_date="2026-01-31",
                            ),
                            f'"{row["version"]}"',
                        )
                    return action, 200
                except DomainError as failure:
                    session.rollback()
                    return action, failure.status

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(perform, action) for action in ("confirm", "edit")]
            outcomes = dict(future.result(timeout=20) for future in futures)
        assert sorted(outcomes.values()) == [200, 409]
        with TestClient(months_app) as client:
            result = read_month(client, account_actor, "2026-01")
            assert (result["state"], result["values"][0]["input_amount_krw"]) == (
                ("confirmed", "10") if outcomes["confirm"] == 200 else ("draft", "11")
            )

    def test_t01_and_t03_exact_totals_once_with_shared_ownership(self, months_app, account_actor):
        first, expected = vector(1)
        shared, share_expected = vector(3)
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor)
            liability = add_asset(client, account_actor, kind="liability", category="loan")
            house = add_asset(
                client,
                account_actor,
                category="real_estate",
                household_share=shared["household_share"],
                amount_basis=shared["amount_basis"],
            )
            draft(client, account_actor, "2026-01")
            observe(
                client, account_actor, "2026-01", asset["id"], first["assets_krw"], "2026-01-31"
            )
            observe(
                client,
                account_actor,
                "2026-01",
                liability["id"],
                first["liabilities_krw"],
                "2026-01-31",
            )
            response = observe(
                client, account_actor, "2026-01", house["id"], shared["valuation_krw"], "2026-01-31"
            )
            assert response["value"]["owned_amount_krw"] == share_expected["owned_amount_krw"]
            assert response["totals"]["net_assets_krw"] == str(
                int(expected["net_assets_krw"]) + int(share_expected["owned_amount_krw"])
            )
            assert response["totals"]["item_count"] == 3
            assert confirm(client, account_actor, "2026-01").status_code == 200

    def test_t02_account_and_t04_holdings_have_one_amount_source(self, months_app, account_actor):
        account_input, expected = vector(4)
        with TestClient(months_app) as client:
            account = create_account(client, account_actor, account_number=None, account_type="irp")
            for reference in account_input["reference_holdings"]:
                add_asset(
                    client, account_actor, name=reference["label"], inclusion_status="excluded"
                )
            draft(client, account_actor, "2026-01")
            observe(
                client,
                account_actor,
                "2026-01",
                account["asset_id"],
                account_input["account_total_krw"],
                "2026-01-31",
            )
            current = read_month(client, account_actor, "2026-01")
            assert current["totals"]["assets_krw"] == expected["household_total_krw"]
            assert current["totals"]["item_count"] == 1
            assert confirm(client, account_actor, "2026-01").status_code == 200

    def test_missing_zero_and_carry_require_explicit_month_verification(
        self, months_app, account_actor
    ):
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor)
            draft(client, account_actor, "2026-01")
            missing = read_month(client, account_actor, "2026-01")
            assert missing["totals"]["assets_krw"] is None
            assert missing["totals"]["missing_count"] == 1
            assert (
                confirm(client, account_actor, "2026-01").json()["error"]["code"]
                == "MONTH_UNVERIFIED"
            )
            observe(client, account_actor, "2026-01", asset["id"], "0", "2026-01-31")
            assert confirm(client, account_actor, "2026-01").status_code == 200
            draft(client, account_actor, "2026-02")
            carried = read_month(client, account_actor, "2026-02")
            row = carried["values"][0]
            assert row["input_amount_krw"] == "0" and row["as_of_date"] is None
            assert row["verification_state"] == "carried_unconfirmed"
            assert carried["totals"]["provisional"] is True
            assert confirm(client, account_actor, "2026-02").status_code == 409
            updated = client.patch(
                f"/api/v1/asset-months/2026-02/values/{asset['id']}",
                json={
                    "revision_id": carried["revision_id"],
                    "value_id": row["id"],
                    "unchanged": True,
                    "as_of_date": "2026-02-28",
                },
                headers={**account_actor.headers, "If-Match": f'"{row["version"]}"'},
            )
            assert updated.status_code == 200
            assert updated.json()["totals"]["assets_krw"] == "0"
            assert confirm(client, account_actor, "2026-02").status_code == 200

    def test_idempotent_draft_reference_survives_edits_and_confirmation(
        self, months_app, account_actor, db_engine
    ):
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor)
            key = uuid4().hex
            initial = draft(client, account_actor, "2026-01", key=key)
            observe(client, account_actor, "2026-01", asset["id"], "9007199254740993", "2026-01-31")
            confirmed = confirm(client, account_actor, "2026-01")
            assert confirmed.status_code == 200
            assert draft(client, account_actor, "2026-01", key=key) == initial
            conflict = client.post(
                "/api/v1/asset-months/2026-01/draft",
                json={"copy_previous": False},
                headers={**account_actor.headers, "Idempotency-Key": key},
            )
            assert conflict.status_code == 409
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(AssetMonthRecord)) == 1
            assert session.scalar(select(func.count()).select_from(AssetMonthRevision)) == 1

    def test_row_and_revision_conflicts_preserve_other_edit(self, months_app, account_actor):
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor)
            initial = draft(client, account_actor, "2026-01")
            observe(client, account_actor, "2026-01", asset["id"], "7", "2026-01-31")
            conflict = client.patch(
                f"/api/v1/asset-months/2026-01/values/{asset['id']}",
                json={
                    "revision_id": initial["revision_id"],
                    "value_id": read_month(client, account_actor, "2026-01")["values"][0]["id"],
                    "input_amount_krw": "8",
                    "as_of_date": "2026-01-31",
                },
                headers={**account_actor.headers, "If-Match": '"1"'},
            )
            assert (
                conflict.status_code == 409
                and conflict.json()["error"]["code"] == "VERSION_CONFLICT"
            )
            failed_confirm = client.post(
                "/api/v1/asset-months/2026-01/confirm",
                json={"revision_id": initial["revision_id"]},
                headers={
                    **account_actor.headers,
                    "If-Match": '"1"',
                    "Idempotency-Key": uuid4().hex,
                },
            )
            assert failed_confirm.status_code == 409
            assert (
                read_month(client, account_actor, "2026-01")["values"][0]["input_amount_krw"] == "7"
            )

    def test_reopening_freezes_old_amount_and_scope_and_blocks_stale_revision(
        self, months_app, account_actor
    ):
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor, household_share="0.5", amount_basis="whole")
            initial = draft(client, account_actor, "2026-01")
            observe(client, account_actor, "2026-01", asset["id"], "100", "2026-01-31")
            assert confirm(client, account_actor, "2026-01").status_code == 200
            original = read_month(client, account_actor, "2026-01")
            assert (
                client.patch(
                    f"/api/v1/assets/{asset['id']}",
                    json={"household_share": "1", "name": "합성 새 이름"},
                    headers={**account_actor.headers, "If-Match": f'"{asset["version"]}"'},
                ).status_code
                == 200
            )
            key = uuid4().hex
            reopen_payload = {
                "revision_id": original["revision_id"],
                "reason": "합성 평가 오기 정정",
            }
            reopen_headers = {
                **account_actor.headers,
                "If-Match": f'"{original["version"]}"',
                "Idempotency-Key": key,
            }
            reopened = client.post(
                "/api/v1/asset-months/2026-01/reopen", json=reopen_payload, headers=reopen_headers
            )
            assert reopened.status_code == 201 and reopened.json()["revision_no"] == 2
            current = read_month(client, account_actor, "2026-01")
            assert (
                current["values"][0]["household_share"] == "0.5" and current["scope_stale"] is True
            )
            stale = client.patch(
                f"/api/v1/asset-months/2026-01/values/{asset['id']}",
                json={
                    "revision_id": initial["revision_id"],
                    "value_id": original["values"][0]["id"],
                    "input_amount_krw": "101",
                    "as_of_date": "2026-01-31",
                },
                headers={**account_actor.headers, "If-Match": '"1"'},
            )
            assert stale.status_code == 409 and stale.json()["error"]["code"] == "REVISION_CONFLICT"
            observe(client, account_actor, "2026-01", asset["id"], "120", "2026-01-31")
            assert confirm(client, account_actor, "2026-01").status_code == 200
            assert read_month(client, account_actor, "2026-01")["totals"]["assets_krw"] == "60"
            old = client.get(
                "/api/v1/asset-months/2026-01/revisions/1", headers=account_actor.headers
            )
            assert old.status_code == 200 and old.json() == original
            assert (
                client.post(
                    "/api/v1/asset-months/2026-01/reopen",
                    json=reopen_payload,
                    headers=reopen_headers,
                ).json()
                == reopened.json()
            )
            history = client.get(
                "/api/v1/asset-months/2026-01/revisions?limit=1", headers=account_actor.headers
            ).json()
            assert (
                history["next_cursor"] == 2
                and history["items"][0]["reopened_reason"] == "합성 평가 오기 정정"
            )

    def test_scope_synchronization_requires_reverification_and_preserves_confirmed_history(
        self, months_app, account_actor
    ):
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor, amount_basis="whole", household_share="0.5")
            draft(client, account_actor, "2026-01")
            observe(client, account_actor, "2026-01", asset["id"], "100", "2026-01-31")
            assert (
                client.patch(
                    f"/api/v1/assets/{asset['id']}",
                    json={"household_share": "1"},
                    headers={**account_actor.headers, "If-Match": f'"{asset["version"]}"'},
                ).status_code
                == 200
            )
            assert (
                confirm(client, account_actor, "2026-01").json()["error"]["code"]
                == "MONTH_SCOPE_CHANGED"
            )
            before = read_month(client, account_actor, "2026-01")
            synchronized = client.post(
                "/api/v1/asset-months/2026-01/sync-scope",
                json={"revision_id": before["revision_id"]},
                headers={**account_actor.headers, "If-Match": f'"{before["version"]}"'},
            )
            assert synchronized.status_code == 200
            current = read_month(client, account_actor, "2026-01")
            assert current["values"][0]["owned_amount_krw"] == "100"
            assert current["values"][0]["verification_state"] == "carried_unconfirmed"
            assert confirm(client, account_actor, "2026-01").status_code == 409

    def test_foreign_household_month_and_asset_access_is_hidden(
        self, months_app, account_actor, db_engine
    ):
        foreign = make_actor(db_engine)
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor)
            reference = draft(client, account_actor, "2026-01")
            other_asset = add_asset(client, foreign)
            other_reference = draft(client, foreign, "2026-02")
            assert (
                client.get("/api/v1/asset-months/2026-01", headers=foreign.headers).status_code
                == 404
            )
            assert (
                client.get(
                    "/api/v1/asset-months/2026-01/revisions/1", headers=foreign.headers
                ).status_code
                == 404
            )
            for revision, asset_id in [
                (reference, other_asset["id"]),
                (other_reference, asset["id"]),
            ]:
                response = client.patch(
                    f"/api/v1/asset-months/2026-01/values/{asset_id}",
                    json={
                        "revision_id": revision["revision_id"],
                        "value_id": read_month(client, account_actor, "2026-01")["values"][0]["id"],
                        "input_amount_krw": "0",
                        "as_of_date": "2026-01-31",
                    },
                    headers={**account_actor.headers, "If-Match": '"1"'},
                )
                assert response.status_code in {404, 409}
        with Session(db_engine) as session:
            row = session.scalar(
                select(AssetMonthValue).where(AssetMonthValue.asset_id == UUID(asset["id"]))
            )
            session.add(
                AssetMonthValue(
                    household_id=row.household_id,
                    revision_id=row.revision_id,
                    asset_id=UUID(other_asset["id"]),
                    source_asset_version=1,
                    name="합성 외부 가계 자산",
                    kind=row.kind,
                    category=row.category,
                    ownership_kind=row.ownership_kind,
                    owner_member_id=row.owner_member_id,
                    household_share=row.household_share,
                    amount_basis=row.amount_basis,
                    inclusion_status=row.inclusion_status,
                    started_on=row.started_on,
                    verification_state="missing",
                    origin="manual",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()

    def test_confirmed_rows_are_immutable_even_through_direct_sql(
        self, months_app, account_actor, db_engine
    ):
        with TestClient(months_app) as client:
            asset = add_asset(client, account_actor)
            draft(client, account_actor, "2026-01")
            observe(client, account_actor, "2026-01", asset["id"], "100", "2026-01-31")
            assert confirm(client, account_actor, "2026-01").status_code == 200
            month = read_month(client, account_actor, "2026-01")
        for statement in (
            update(AssetMonthValue)
            .where(AssetMonthValue.id == UUID(month["values"][0]["id"]))
            .values(input_amount_krw=101, owned_amount_krw=101),
            update(AssetMonthRevision)
            .where(AssetMonthRevision.id == UUID(month["revision_id"]))
            .values(state="draft", confirmed_at=None, confirmed_by_member_id=None),
        ):
            with Session(db_engine) as session, pytest.raises(DBAPIError) as caught:
                session.execute(statement)
                session.commit()
            assert caught.value.orig.sqlstate == "55000"

    def test_month_end_acknowledgment_and_closing_month_eligibility(
        self, months_app, account_actor
    ):
        with TestClient(months_app) as client:
            closed = add_asset(client, account_actor, ended_on="2026-01-15")
            draft(client, account_actor, "2026-01")
            observe(client, account_actor, "2026-01", closed["id"], "0", "2026-01-15")
            assert (
                confirm(client, account_actor, "2026-01").json()["error"]["code"]
                == "AS_OF_DATE_ACK_REQUIRED"
            )
            assert (
                confirm(
                    client, account_actor, "2026-01", acknowledge_non_month_end_dates=True
                ).status_code
                == 200
            )
            draft(client, account_actor, "2026-02")
            assert read_month(client, account_actor, "2026-02")["values"] == []
            assert (
                confirm(client, account_actor, "2026-02").json()["error"]["code"]
                == "SCOPE_ACK_REQUIRED"
            )
            assert (
                confirm(client, account_actor, "2026-02", acknowledge_scope_change=True).status_code
                == 200
            )
