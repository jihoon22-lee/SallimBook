"""Asset metadata tests use synthetic accounts and the real migration fixture.

Monthly valuations/accounts are intentionally absent. A small FK probe tests
the deletion boundary that those later source tables must preserve; it does
not substitute metadata.create_all for the actual assets migration.
"""

import secrets
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sallimbook.assets.models import Asset
from sallimbook.assets.router import router
from sallimbook.assets.schemas import (
    AssetArchive,
    AssetCreate,
    AssetPatch,
    DateOnly,
    HouseholdShare,
)
from sallimbook.config import Settings
from sallimbook.core.audit import AuditEvent
from sallimbook.core.http import install_http_contract
from sallimbook.identity import service as identity_service
from sallimbook.identity.auth_models import HouseholdMember, User
from sallimbook.identity.models import Household
from sallimbook.identity.router import router as identity_router
from sallimbook.identity.schemas import LoginRequest

ORIGIN = "https://sallimbook-assets-test.invalid"


def joint_payload(**overrides):
    return {
        "name": "합성 공동 주택",
        "kind": "asset",
        "category": "real_estate",
        "ownership_kind": "joint",
        "household_share": "0.5",
        "amount_basis": "whole",
        "started_on": "2025-01-01",
        **overrides,
    }


def test_asset_schema_distinguishes_whole_and_owned_without_adding_a_valuation():
    payload = AssetCreate.model_validate(joint_payload())
    assert payload.household_share == "0.5"
    assert payload.amount_basis == "whole"
    assert payload.owner_member_id is None
    assert AssetCreate.model_validate(joint_payload(amount_basis="owned")).amount_basis == "owned"
    assert "amount_krw" not in payload.model_dump()
    assert "input_amount_krw" not in payload.model_dump()


@pytest.mark.parametrize("value", ["0", "1", "0.5", "0.000000000000000001", "1.000000000000000000"])
def test_share_accepts_exact_bounded_decimal_text(value):
    assert TypeAdapter(HouseholdShare).validate_python(value) == value


@pytest.mark.parametrize(
    "value",
    [
        0,
        0.5,
        True,
        Decimal("0.5"),
        "NaN",
        "Infinity",
        "-0.1",
        "1.1",
        "1e-1",
        "0.0000000000000000001",
        "+1",
        "01",
        " 0.5",
    ],
)
def test_share_rejects_float_nonfinite_out_of_range_and_unsupported_precision(value):
    with pytest.raises(ValidationError):
        TypeAdapter(HouseholdShare).validate_python(value)


@pytest.mark.parametrize(
    "value", [0, True, 1.5, "2025-1-1", "2025-01-01T00:00:00Z", datetime(2025, 1, 1)]
)
def test_asset_dates_are_dates_without_timestamp_coercion(value):
    with pytest.raises(ValidationError):
        TypeAdapter(DateOnly).validate_python(value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "   "},
        {"name": "합" * 121},
        {"kind": "appliance"},
        {"category": "future_pension"},
        {"ownership_kind": "individual"},
        {"owner_member_id": str(uuid4())},
        {"ended_on": "2024-12-31"},
        {"household_id": str(uuid4())},
        {"version": 1},
        {"created_by_member_id": str(uuid4())},
        {"archived_at": "2025-01-01T00:00:00Z"},
        {"amount_krw": "600000000"},
        {"purchase_price_krw": "300000"},
        {"future_pension_krw": "1000000"},
    ],
)
def test_asset_schema_rejects_invalid_relations_and_server_controlled_fields(overrides):
    with pytest.raises(ValidationError):
        AssetCreate.model_validate(joint_payload(**overrides))


def test_patch_distinguishes_omitted_fields_from_explicit_clear():
    patch = AssetPatch(note=None)
    assert patch.model_dump(exclude_unset=True) == {"note": None}

    assert AssetPatch(ended_on=None).model_dump(exclude_unset=True) == {"ended_on": None}
    assert AssetPatch(owner_member_id=None).model_dump(exclude_unset=True) == {
        "owner_member_id": None
    }
    for invalid in (
        {},
        {"name": None},
        {"started_on": None},
        {"household_share": None},
        {"id": str(uuid4())},
    ):
        with pytest.raises(ValidationError):
            AssetPatch.model_validate(invalid)
    assert AssetArchive(ended_on="2025-01-01").ended_on == date(2025, 1, 1)


def test_openapi_patch_nullability_matches_server_validation():
    app = FastAPI()
    app.include_router(router)
    contract = app.openapi()["components"]["schemas"]["AssetPatch"]
    clearable = {"owner_member_id", "ended_on", "note"}
    for name, schema in contract["properties"].items():
        assert name not in contract.get("required", [])
        nullable = any(item.get("type") == "null" for item in schema.get("anyOf", []))
        assert nullable == (name in clearable)
        if name in clearable:
            assert AssetPatch.model_validate({name: None}).model_dump(exclude_unset=True) == {
                name: None
            }
        else:
            assert "default" not in schema
            with pytest.raises(ValidationError):
                AssetPatch.model_validate({name: None})


def test_openapi_declares_required_versions_and_runtime_response_headers():
    app = FastAPI()
    app.include_router(router)
    paths = app.openapi()["paths"]
    base = "/api/v1/assets"
    for path, method in (
        (base + "/{asset_id}", "patch"),
        (base + "/{asset_id}", "delete"),
        (base + "/{asset_id}/archive", "post"),
    ):
        header = next(p for p in paths[path][method]["parameters"] if p["name"] == "If-Match")
        assert header["required"] is True
        assert header["schema"]["type"] == "string"
    for path, method, status, headers in (
        (base, "post", "201", {"ETag", "Location"}),
        (base + "/{asset_id}", "get", "200", {"ETag"}),
        (base + "/{asset_id}", "patch", "200", {"ETag"}),
        (base + "/{asset_id}/archive", "post", "200", {"ETag"}),
    ):
        assert paths[path][method]["responses"][status]["headers"].keys() == headers


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    member_id: UUID
    household_id: UUID
    login_name: str
    password: str = field(repr=False)
    token: str = field(repr=False)

    @property
    def headers(self):
        return {"Authorization": "Bearer " + self.token}


@pytest.fixture
def assets_app(db_engine):
    app = FastAPI()
    app.state.settings = Settings(environment="test", allowed_origins=[ORIGIN], database_url=None)
    app.state.engine = db_engine
    install_http_contract(app)
    app.include_router(identity_router)
    app.include_router(router)
    return app


@pytest.fixture
def asset_client(assets_app):
    with TestClient(assets_app, base_url="https://testserver") as client:
        yield client


@pytest.fixture
def asset_actors(db_engine):
    password = secrets.token_urlsafe(24)
    password_hash = identity_service.PASSWORD_HASHER.hash(password)
    actors = []
    with Session(db_engine) as session:
        h1, h2 = Household(name="합성 H1"), Household(name="합성 H2")
        session.add_all([h1, h2])
        session.flush()
        for label, household, slot in [("a", h1, 1), ("b", h1, 2), ("c", h2, 1)]:
            user = User(
                login_name="synthetic_asset_" + label,
                display_name="합성 " + label,
                password_hash=password_hash,
            )
            session.add(user)
            session.flush()
            member = HouseholdMember(
                household_id=household.id,
                user_id=user.id,
                slot=slot,
                role="owner" if slot == 1 else "member",
                status="active",
            )
            session.add(member)
            session.commit()
            login = identity_service.login(
                session,
                LoginRequest(
                    login_name=user.login_name, password=password, device_label="합성 자산 기기"
                ),
                "synthetic-asset-" + label,
                "native",
            )
            actors.append(
                Actor(user.id, member.id, household.id, user.login_name, password, login.token)
            )
    return actors


def create(client, actor, **overrides):
    response = client.post("/api/v1/assets", headers=actor.headers, json=joint_payload(**overrides))
    assert response.status_code == 201
    return response


@pytest.mark.database
class TestAssetsDatabase:
    def test_asset_audit_preserves_actor_and_versions_without_copying_entered_values(
        self, asset_client, asset_actors, db_engine
    ):
        a, b, _ = asset_actors
        created = create(asset_client, a, note="synthetic private note, never an audit value")
        updated = asset_client.patch(
            created.headers["location"],
            headers={**b.headers, "If-Match": '"1"'},
            json={"name": "합성 수정 주택", "note": None},
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2
        stale = asset_client.patch(
            created.headers["location"],
            headers={**a.headers, "If-Match": '"1"'},
            json={"name": "합성 저장되지 않을 이름"},
        )
        assert stale.status_code == 409
        with Session(db_engine) as session:
            events = session.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at)).all()
            assert len(events) == 2
            assert events[0].actor_id == a.user_id
            assert events[0].before_version is None and events[0].after_version == 1
            assert events[1].actor_id == b.user_id
            assert events[1].before_version == 1 and events[1].after_version == 2
            assert events[1].safe_diff == {"changed_fields": ["name", "note"]}
            assert all(event.household_id == a.household_id for event in events)
            assert all(event.entity_id == UUID(created.json()["id"]) for event in events)

    def test_audit_database_rejects_an_actor_from_another_household(self, asset_actors, db_engine):
        a, _, c = asset_actors
        with Session(db_engine) as session:
            session.add(
                AuditEvent(
                    household_id=a.household_id,
                    actor_id=c.user_id,
                    entity_type="asset",
                    entity_id=uuid4(),
                    action="create",
                    before_version=None,
                    after_version=1,
                    safe_diff={"changed_fields": []},
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()

    def test_couple_share_one_asset_and_server_assigns_household_and_actor(
        self, asset_client, asset_actors, db_engine
    ):
        a, b, _ = asset_actors
        created = create(asset_client, a)
        record = created.json()
        assert record["household_id"] == str(a.household_id)
        assert record["created_by_member_id"] == record["updated_by_member_id"] == str(a.member_id)
        assert record["household_share"] == "0.5"
        assert record["version"] == 1
        assert created.headers["etag"] == '"1"'
        url = created.headers["location"]
        partner_read = asset_client.get(url, headers=b.headers)
        assert partner_read.status_code == 200
        assert partner_read.json()["id"] == record["id"]
        assert partner_read.headers["etag"] == '"1"'
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(Asset)) == 1
            assert session.get(Asset, UUID(record["id"])).household_share == Decimal("0.5")

    def test_individual_asset_can_belong_to_partner_and_liabilities_are_supported(
        self, asset_client, asset_actors
    ):
        a, b, _ = asset_actors
        response = create(
            asset_client,
            a,
            name="합성 대출",
            kind="liability",
            category="loan",
            ownership_kind="individual",
            owner_member_id=str(b.member_id),
            household_share="1",
            amount_basis="owned",
        )
        row = response.json()
        assert row["owner_member_id"] == str(b.member_id)
        assert row["kind"] == "liability"
        filtered = asset_client.get(
            "/api/v1/assets",
            headers=b.headers,
            params={"kind": "liability", "owner_member_id": str(b.member_id)},
        )
        assert [r["id"] for r in filtered.json()["items"]] == [row["id"]]

    @pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE", "archive"])
    def test_other_household_cannot_read_mutate_archive_or_delete(
        self, asset_client, asset_actors, method
    ):
        a, _, c = asset_actors
        foreign = create(asset_client, c)
        url = foreign.headers["location"]
        if method == "archive":
            response = asset_client.post(
                url + "/archive",
                headers={**a.headers, "If-Match": '"1"'},
                json={"ended_on": "2025-10-01"},
            )
        else:
            response = asset_client.request(
                method,
                url,
                headers={**a.headers, "If-Match": '"1"'},
                json={"name": "합성 잘못된 변경"} if method == "PATCH" else None,
            )
        assert response.status_code == 404
        preserved = asset_client.get(url, headers=c.headers)
        assert preserved.status_code == 200
        assert preserved.json()["version"] == 1

    def test_foreign_owner_id_is_rejected_on_create_patch_and_list(
        self, asset_client, asset_actors
    ):
        a, _, c = asset_actors
        payload = joint_payload(ownership_kind="individual", owner_member_id=str(c.member_id))
        assert (
            asset_client.post("/api/v1/assets", headers=a.headers, json=payload).status_code == 404
        )
        created = create(asset_client, a)
        response = asset_client.patch(
            created.headers["location"],
            headers={**a.headers, "If-Match": '"1"'},
            json={"ownership_kind": "individual", "owner_member_id": str(c.member_id)},
        )
        assert response.status_code == 404
        assert (
            asset_client.get(
                "/api/v1/assets", headers=a.headers, params={"owner_member_id": str(c.member_id)}
            ).status_code
            == 404
        )
        assert (
            asset_client.get(created.headers["location"], headers=a.headers).json()[
                "ownership_kind"
            ]
            == "joint"
        )

    def test_owner_composite_fk_also_blocks_cross_household_database_write(
        self, db_engine, asset_actors
    ):
        a, _, c = asset_actors
        values = AssetCreate.model_validate(
            joint_payload(ownership_kind="individual", owner_member_id=str(c.member_id))
        ).model_dump()
        values["household_share"] = Decimal(values["household_share"])
        with Session(db_engine) as session:
            session.add(
                Asset(
                    **values,
                    household_id=a.household_id,
                    created_by_member_id=a.member_id,
                    updated_by_member_id=a.member_id,
                    archived_at=None,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()

    def test_revoked_owner_cannot_receive_new_asset(self, asset_client, asset_actors, db_engine):
        a, b, _ = asset_actors
        with Session(db_engine) as session:
            session.get(HouseholdMember, b.member_id).status = "revoked"
            session.commit()
        response = asset_client.post(
            "/api/v1/assets",
            headers=a.headers,
            json=joint_payload(ownership_kind="individual", owner_member_id=str(b.member_id)),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "OWNER_UNAVAILABLE"

    def test_partner_edit_uses_version_and_does_not_overwrite_newer_values(
        self, asset_client, asset_actors
    ):
        a, b, _ = asset_actors
        created = create(asset_client, a)
        url = created.headers["location"]
        changed = asset_client.patch(
            url,
            headers={**b.headers, "If-Match": '"1"'},
            json={"name": "합성 공동 주택 수정", "amount_basis": "owned"},
        )
        assert changed.status_code == 200
        assert changed.json()["version"] == 2
        assert changed.headers["etag"] == '"2"'
        assert changed.json()["created_by_member_id"] == str(a.member_id)
        assert changed.json()["updated_by_member_id"] == str(b.member_id)
        stale = asset_client.patch(
            url, headers={**a.headers, "If-Match": '"1"'}, json={"name": "합성 오래된 수정"}
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["current_version"] == 2
        for method in ["PATCH", "DELETE"]:
            missing = asset_client.request(
                method,
                url,
                headers=a.headers,
                json={"name": "합성 수정"} if method == "PATCH" else None,
            )
            assert missing.status_code == 400
        assert asset_client.get(url, headers=a.headers).json()["name"] == "합성 공동 주택 수정"

    def test_partial_edit_revalidates_merged_owner_and_date_state(self, asset_client, asset_actors):
        a = asset_actors[0]
        created = create(
            asset_client, a, ownership_kind="individual", owner_member_id=str(a.member_id)
        )
        url = created.headers["location"]
        for patch in [
            {"owner_member_id": None},
            {"ownership_kind": "joint"},
            {"ended_on": "2024-01-01"},
        ]:
            assert (
                asset_client.patch(
                    url, headers={**a.headers, "If-Match": '"1"'}, json=patch
                ).status_code
                == 422
            )
        changed = asset_client.patch(
            url,
            headers={**a.headers, "If-Match": '"1"'},
            json={"ownership_kind": "joint", "owner_member_id": None, "note": None},
        )
        assert changed.status_code == 200
        assert changed.json()["owner_member_id"] is None

    def test_list_pagination_filters_and_household_isolation(self, asset_client, asset_actors):
        a, _, c = asset_actors
        expected = {
            create(asset_client, a, name="합성 자산 " + str(i)).json()["id"] for i in range(3)
        }
        create(asset_client, c, name="합성 다른 가계 자산")
        create(asset_client, a, name="합성 제외 자산", inclusion_status="excluded")
        first = asset_client.get(
            "/api/v1/assets", headers=a.headers, params={"limit": 2, "inclusion_status": "included"}
        )
        assert first.status_code == 200
        assert len(first.json()["items"]) == 2
        second = asset_client.get(
            "/api/v1/assets",
            headers=a.headers,
            params={
                "limit": 2,
                "inclusion_status": "included",
                "cursor": first.json()["next_cursor"],
            },
        )
        rows = first.json()["items"] + second.json()["items"]
        assert {r["id"] for r in rows} == expected
        assert len(rows) == 3
        assert second.json()["next_cursor"] is None
        assert all(r["household_id"] == str(a.household_id) for r in rows)
        for limit in [0, 201]:
            assert (
                asset_client.get(
                    "/api/v1/assets", headers=a.headers, params={"limit": limit}
                ).status_code
                == 422
            )

    @pytest.mark.parametrize("delete_rule", ["RESTRICT", "NO ACTION"])
    def test_archive_preserves_referenced_asset_and_delete_only_removes_unreferenced(
        self, asset_client, asset_actors, db_engine, delete_rule
    ):
        a = asset_actors[0]
        created = create(asset_client, a)
        url = created.headers["location"]
        identity = UUID(created.json()["id"])
        with db_engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE asset_reference_probe (household_id uuid NOT NULL, "
                    "asset_id uuid NOT NULL, FOREIGN KEY (household_id, asset_id) "
                    f"REFERENCES assets(household_id, id) ON DELETE {delete_rule})"
                )
            )
            connection.execute(
                text("INSERT INTO asset_reference_probe VALUES (:household, :asset)"),
                {"household": a.household_id, "asset": identity},
            )
        blocked = asset_client.delete(url, headers={**a.headers, "If-Match": '"1"'})
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "ASSET_IN_USE"
        archived = asset_client.post(
            url + "/archive",
            headers={**a.headers, "If-Match": '"1"'},
            json={"ended_on": "2025-10-01"},
        )
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"
        assert archived.json()["ended_on"] == "2025-10-01"
        assert archived.json()["archived_at"] is not None
        assert archived.json()["household_share"] == "0.5"
        assert asset_client.get("/api/v1/assets", headers=a.headers).json()["items"] == []
        archive_list = asset_client.get(
            "/api/v1/assets", headers=a.headers, params={"status": "archived"}
        )
        assert [r["id"] for r in archive_list.json()["items"]] == [str(identity)]
        with db_engine.connect() as connection:
            assert connection.scalar(text("SELECT asset_id FROM asset_reference_probe")) == identity
        unreferenced = create(asset_client, a, name="합성 오등록")
        deleted = asset_client.delete(
            unreferenced.headers["location"], headers={**a.headers, "If-Match": '"1"'}
        )
        assert deleted.status_code == 204
        assert (
            asset_client.get(unreferenced.headers["location"], headers=a.headers).status_code == 404
        )

    def test_past_ended_create_and_explicit_reopen_preserve_asset_identity(
        self, asset_client, asset_actors
    ):
        a = asset_actors[0]
        created = create(asset_client, a, ended_on="2025-09-01")
        assert created.json()["status"] == "archived"
        reopened = asset_client.patch(
            created.headers["location"],
            headers={**a.headers, "If-Match": '"1"'},
            json={"ended_on": None},
        )
        assert reopened.status_code == 200
        assert reopened.json()["id"] == created.json()["id"]
        assert reopened.json()["status"] == "active"
        assert reopened.json()["archived_at"] is None

    def test_asset_routes_require_authentication_and_cookie_mutations_require_csrf(
        self, asset_client, asset_actors
    ):
        a = asset_actors[0]
        assert asset_client.get("/api/v1/assets").status_code == 401
        assert asset_client.post("/api/v1/assets", json=joint_payload()).status_code == 401
        login = asset_client.post(
            "/api/v1/auth/web/login",
            headers={"Origin": ORIGIN},
            json={"login_name": a.login_name, "password": a.password, "device_label": "합성 PC"},
        )
        assert login.status_code == 200
        blocked = asset_client.post(
            "/api/v1/assets", headers={"Origin": ORIGIN}, json=joint_payload()
        )
        assert blocked.status_code == 403
        saved = asset_client.post(
            "/api/v1/assets",
            headers={"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]},
            json=joint_payload(),
        )
        assert saved.status_code == 201

    def test_api_rejects_household_injection_and_numeric_share(self, asset_client, asset_actors):
        a, _, c = asset_actors
        for payload in [
            joint_payload(household_id=str(c.household_id)),
            joint_payload(household_share=0.5),
        ]:
            assert (
                asset_client.post("/api/v1/assets", headers=a.headers, json=payload).status_code
                == 422
            )
