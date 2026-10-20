"""Synthetic PostgreSQL snapshots, live authorization and complete archive boundaries."""

import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from test_accounts import (
    NATIVE_ORIGIN,
    NATIVE_POLICY,
    SyntheticAuthenticator,
    create_account,
    make_actor,
)
from test_cards import payload as card_payload
from test_documents import CONTENT, document_app, pending, upload  # noqa: F401 -- fixture
from test_homecare_database import post_appliance, post_consumable, post_link
from test_income import headers, income_payload
from test_insurance_core import policy_payload
from test_insurance_events import allocation, new_case, new_expense, new_node, new_payout
from test_recurring import generate, obligation_for, post_rule, settle
from webauthn.helpers import base64url_to_bytes

from sallimbook.accounts.models import FinancialAccount
from sallimbook.accounts.router import router as accounts_router
from sallimbook.assets.models import Asset
from sallimbook.assets.month_router import router as months_router
from sallimbook.audit.router import router as audit_router
from sallimbook.cards.router import router as cards_router
from sallimbook.cashflow.recurring_router import router as recurring_router
from sallimbook.cashflow.router import router as income_router
from sallimbook.core.audit import AuditEvent
from sallimbook.core.database import Base
from sallimbook.documents import service as documents
from sallimbook.documents.schemas import DocumentReason
from sallimbook.exports import router as export_routes
from sallimbook.exports.archive import ArchiveBuilder, Budget, Limits
from sallimbook.exports.catalog import PUBLIC_COLUMNS
from sallimbook.exports.router import router
from sallimbook.identity import service as identity
from sallimbook.identity.auth_models import AuthSession, HouseholdMember, RegisteredDevice
from sallimbook.identity.passkeys import service as passkeys
from sallimbook.identity.passkeys.models import StepUpGrant, StepUpPurpose
from sallimbook.identity.passkeys.schemas import (
    AssertionVerification,
    RegisterOptionsRequest,
    RegisterVerification,
    StepUpOptionsRequest,
)
from sallimbook.insurance.event_router import router as events_router
from sallimbook.insurance.router import router as insurance_router

pytestmark = pytest.mark.database


@pytest.fixture
def actors(db_engine):
    first = make_actor(db_engine)
    return first, make_actor(db_engine, first.household_id), make_actor(db_engine)


@pytest.fixture
def export_app(document_app):  # noqa: F811 -- imported pytest fixture
    for item in (
        accounts_router,
        months_router,
        audit_router,
        cards_router,
        income_router,
        recurring_router,
        events_router,
        insurance_router,
        router,
    ):
        document_app.include_router(item)
    return document_app


def export(client, actor, **payload):
    return client.post("/api/v1/exports", headers=actor.headers, json=payload)


def decoded(response):
    assert response.status_code == 200, response.text[:500] if response.status_code != 200 else ""
    assert response.headers["content-type"] == "application/zip"
    assert hashlib.sha256(response.content).hexdigest() == response.headers["x-export-sha256"]
    assert response.headers["cache-control"] == "no-store"
    assert int(response.headers["content-length"]) == len(response.content)
    with ZipFile(io.BytesIO(response.content)) as archive:
        return {
            name: json.loads(archive.read(name))
            for name in archive.namelist()
            if name.endswith(".json")
        }


def grant(engine, actor):
    with Session(engine) as session:
        authenticator = SyntheticAuthenticator.create()
        options = passkeys.registration_options(
            session,
            actor.principal,
            RegisterOptionsRequest(label="합성 내보내기 패스키"),
            NATIVE_POLICY,
        )
        passkeys.register_credential(
            session,
            actor.principal,
            RegisterVerification(
                challenge_id=options.challenge_id,
                credential=authenticator.registration(
                    base64url_to_bytes(options.public_key["challenge"]), origin=NATIVE_ORIGIN
                ),
            ),
            NATIVE_POLICY,
        )
        options = passkeys.step_up_options(
            session,
            actor.principal,
            StepUpOptionsRequest(
                purpose=StepUpPurpose.DATA_EXPORT,
                target_id=actor.household_id,
            ),
            NATIVE_POLICY,
        )
        result = passkeys.verify_step_up(
            session,
            actor.principal,
            AssertionVerification(
                challenge_id=options.challenge_id,
                credential=authenticator.assertion(
                    base64url_to_bytes(options.public_key["challenge"]),
                    actor.user_id,
                    origin=NATIVE_ORIGIN,
                ),
            ),
            NATIVE_POLICY,
        )
        session.execute(
            update(AuthSession)
            .where(AuthSession.id == actor.principal.session_id)
            .values(authenticated_at=identity.utcnow() - timedelta(minutes=6))
        )
        session.commit()
        return result.grant_token


def test_all_seven_domains_exact_manual_records_versions_and_secret_omissions(
    export_app, actors, db_engine
):
    actor, partner, foreign = actors
    with TestClient(export_app) as client:
        account = create_account(client, actor)
        create_account(client, foreign, institution_name="FOREIGN-HOUSEHOLD-CANARY")
        card = client.post(
            "/api/v1/cards",
            headers=actor.headers,
            json=card_payload(actor, settlement_account_id=account["id"]),
        )
        assert card.status_code == 201, card.text
        income = client.post("/api/v1/income", headers=headers(actor), json=income_payload(actor))
        assert income.status_code == 201, income.text
        changed = client.patch(
            f"/api/v1/income/{income.json()['id']}",
            headers=headers(actor, version=1),
            json={"amount_krw": "3100000", "reason": "합성 정정"},
        )
        assert changed.status_code == 200, changed.text
        rule = post_rule(client, actor)
        generate(client, actor, rule["id"])
        settle(client, actor, obligation_for(client, actor, "2026-01"))
        policy = client.post(
            "/api/v1/insurance/policies",
            headers=actor.headers,
            json=policy_payload(policy_number="SYNTHETIC-SECRET-POLICY"),
        )
        assert policy.status_code == 201, policy.text
        case = new_case(client, actor)
        node = new_node(client, actor, case)
        expense = new_expense(client, actor, case, node, "100")
        new_payout(client, actor, [allocation(case["id"], "30")])
        appliance = post_appliance(client, actor, purchase_price_krw="0")
        stock = post_consumable(client, actor)
        post_link(client, actor, appliance, stock)
        month = client.post(
            "/api/v1/asset-months/2026-01/draft",
            headers=headers(actor),
            json={"copy_previous": False},
        )
        assert month.status_code == 201, month.text
        document = pending(client, actor)
        assert upload(client, actor, document).status_code == 200
        response = export(client, partner, document_ids=[document["id"]])
        data = decoded(response)
        for private in (
            actor.token.encode(),
            actor.password.encode(),
            actor.login_name.encode(),
            b"000123-4567890",
            b"SYNTHETIC-SECRET-POLICY",
            b"FOREIGN-HOUSEHOLD-CANARY",
        ):
            assert private not in response.content
        assert len(data["json/member_names.json"]) == 2
        assert data["json/financial_accounts.json"][0]["asset_id"] == account["asset_id"]
        assert data["json/asset_values.json"][0]["input_amount_krw"] is None
        assert data["json/appliances.json"][0]["purchase_price_krw"] == "0"
        assert len(data["json/cash_record_revisions.json"]) >= 2
        assert data["json/medical_expenses.json"][0]["cash_record_id"] == expense["cash"]["id"]
        cash_ids = [row["id"] for row in data["json/cash_records.json"]]
        assert len(cash_ids) == len(set(cash_ids))
        with Session(db_engine) as session:
            for name in PUBLIC_COLUMNS:
                table = Base.metadata.tables[name]
                scope = table.c.id if name == "households" else table.c.household_id
                count = session.scalar(
                    select(func.count()).select_from(table).where(scope == actor.household_id)
                )
                assert len(data[f"json/{name}.json"]) == count, name
            issued = session.scalars(
                select(AuditEvent).where(AuditEvent.entity_type == "user_export")
            ).all()
            assert len(issued) == 1 and issued[0].actor_id == partner.user_id
            assert issued[0].request_id == response.headers["x-request-id"]
        with ZipFile(io.BytesIO(response.content)) as archive:
            assert archive.read(f"documents/{document['id']}.pdf") == CONTENT
            for entry in data["manifest.json"]["entries"]:
                assert hashlib.sha256(archive.read(entry["path"])).hexdigest() == entry["sha256"]


def test_all_rows_not_ui_pagination_and_repeated_requests_are_fresh(export_app, actors, db_engine):
    actor = actors[0]
    with Session(db_engine) as session:
        for index in range(205):
            session.add(
                Asset(
                    household_id=actor.household_id,
                    kind="asset",
                    category="financial",
                    name=f"합성 {index}",
                    ownership_kind="joint",
                    household_share=1,
                    amount_basis="owned",
                    inclusion_status="included",
                    started_on=datetime(2025, 1, 1).date(),
                    created_by_member_id=actor.member_id,
                    updated_by_member_id=actor.member_id,
                )
            )
        session.commit()
    with TestClient(export_app) as client:
        first = decoded(export(client, actor, formats=["json"]))
        second = decoded(export(client, actor, formats=["json"]))
    assert len(first["json/assets.json"]) == 205
    assert first["manifest.json"]["export_id"] != second["manifest.json"]["export_id"]
    # Fixture sign-ins are audited; the only new event is the first export itself.
    before = first["json/audit_events.json"]
    assert {row["entity_type"] for row in before} <= {"registered_device"}
    assert len(second["json/audit_events.json"]) == len(before) + 1


def test_repeatable_read_is_consistent_across_concurrent_account_asset_change(
    export_app, actors, db_engine, monkeypatch
):
    actor = actors[0]
    with TestClient(export_app) as client:
        account = create_account(client, actor)
        original = ArchiveBuilder.table
        changed = False

        def interleave(builder, name, *args):
            nonlocal changed
            result = original(builder, name, *args)
            if name == "assets" and not changed:
                changed = True
                with Session(db_engine) as writer:
                    writer.execute(
                        update(Asset)
                        .where(Asset.id == UUID(account["asset_id"]))
                        .values(name="new asset")
                    )
                    writer.execute(
                        update(FinancialAccount)
                        .where(FinancialAccount.id == UUID(account["id"]))
                        .values(institution_name="new institution")
                    )
                    writer.commit()
            return result

        monkeypatch.setattr(ArchiveBuilder, "table", interleave)
        data = decoded(export(client, actor))
    assert changed
    assert data["json/assets.json"][0]["name"] == "합성 금융 자산"
    assert data["json/financial_accounts.json"][0]["institution_name"] == "합성 은행"
    with Session(db_engine) as session:
        assert (
            session.get(FinancialAccount, UUID(account["id"])).institution_name == "new institution"
        )


@pytest.mark.parametrize("target", ["session", "device", "member", "recent_login"])
def test_revocation_during_build_returns_no_archive_and_no_issuance_audit(
    export_app, actors, db_engine, monkeypatch, target
):
    actor = actors[0]
    original = ArchiveBuilder.finish

    def finish(builder):
        artifact = original(builder)
        with Session(db_engine) as writer:
            if target == "session":
                writer.execute(
                    update(AuthSession)
                    .where(AuthSession.id == actor.principal.session_id)
                    .values(revoked_at=identity.utcnow())
                )
            elif target == "device":
                writer.execute(
                    update(RegisteredDevice)
                    .where(RegisteredDevice.id == actor.principal.device_id)
                    .values(status="revoked", revoked_at=identity.utcnow())
                )
            elif target == "member":
                writer.execute(
                    update(HouseholdMember)
                    .where(HouseholdMember.id == actor.member_id)
                    .values(status="revoked")
                )
            else:
                writer.execute(
                    update(AuthSession)
                    .where(AuthSession.id == actor.principal.session_id)
                    .values(authenticated_at=identity.utcnow() - timedelta(minutes=6))
                )
            writer.commit()
        return artifact

    monkeypatch.setattr(ArchiveBuilder, "finish", finish)
    with TestClient(export_app) as client:
        response = export(client, actor)
    assert response.status_code in (401, 403), response.text
    assert not response.content.startswith(b"PK")
    with Session(db_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_type == "user_export")
            )
            == 0
        )


def test_selected_document_foreign_pending_and_late_mutation_fail_closed(
    export_app, actors, db_engine, monkeypatch
):
    actor, _, foreign = actors
    with TestClient(export_app) as client:
        document = pending(client, actor)
        assert export(client, foreign, document_ids=[document["id"]]).status_code == 404
        assert export(client, actor, document_ids=[document["id"]]).status_code == 409
        assert upload(client, actor, document).status_code == 200
        original = ArchiveBuilder.finish

        def finish(builder):
            artifact = original(builder)
            with Session(db_engine) as session:
                documents.delete_document(
                    session,
                    actor.principal,
                    UUID(document["id"]),
                    DocumentReason(reason="합성 삭제"),
                    '"2"',
                    str(uuid4()),
                )
            return artifact

        monkeypatch.setattr(ArchiveBuilder, "finish", finish)
        response = export(client, actor, document_ids=[document["id"]])
        assert response.status_code == 409 and not response.content.startswith(b"PK"), response.text


def test_step_up_is_scoped_one_use_and_not_consumed_on_failed_build(
    export_app, actors, db_engine, monkeypatch
):
    actor = actors[0]
    token = grant(db_engine, actor)
    request_headers = actor.headers | {"X-Step-Up-Token": token}
    with TestClient(export_app) as client:
        assert export(client, actor).status_code == 403
        monkeypatch.setattr(
            export_routes, "Budget", lambda: Budget(limits=Limits(metadata_bytes=1))
        )
        failed = client.post("/api/v1/exports", headers=request_headers, json={})
        assert failed.status_code == 413, failed.text
        with Session(db_engine) as session:
            record = session.scalar(
                select(StepUpGrant).where(
                    StepUpGrant.grant_hash == identity.token_hash("step-up-grant", token)
                )
            )
            assert record.consumed_at is None
        monkeypatch.setattr(export_routes, "Budget", Budget)
        success = client.post("/api/v1/exports", headers=request_headers, json={})
        decoded(success)
        assert client.post("/api/v1/exports", headers=request_headers, json={}).status_code == 403
        assert token.encode() not in success.content


@pytest.mark.parametrize("change", ["purpose", "target", "expiry", "credential"])
def test_step_up_binding_and_live_expiry_before_issuance(
    export_app, actors, db_engine, monkeypatch, change
):
    actor = actors[0]
    token = grant(db_engine, actor)
    if change in ("purpose", "target"):
        with Session(db_engine) as session:
            row = session.scalar(select(StepUpGrant))
            if change == "purpose":
                row.purpose = StepUpPurpose.ACCOUNT_REVEAL.value
            else:
                row.target_id = uuid4()
            session.commit()
    else:
        original = ArchiveBuilder.finish

        def finish(builder):
            artifact = original(builder)
            with Session(db_engine) as session:
                row = session.scalar(select(StepUpGrant))
                if change == "expiry":
                    row.expires_at = identity.utcnow() - timedelta(seconds=1)
                else:
                    from sallimbook.identity.passkeys.models import AuthCredential

                    session.get(
                        AuthCredential, row.credential_record_id
                    ).revoked_at = identity.utcnow()
                session.commit()
            return artifact

        monkeypatch.setattr(ArchiveBuilder, "finish", finish)
    with TestClient(export_app) as client:
        response = client.post(
            "/api/v1/exports", headers=actor.headers | {"X-Step-Up-Token": token}, json={}
        )
    assert response.status_code == 403, response.text
    with Session(db_engine) as session:
        assert session.scalar(select(StepUpGrant)).consumed_at is None


def test_audit_keyset_ties_filters_cross_household_and_no_raw_diff(export_app, actors, db_engine):
    actor, _, foreign = actors
    timestamp = datetime.now(UTC)
    identifiers = sorted([uuid4() for _ in range(5)], reverse=True)
    with Session(db_engine) as session:
        for identifier in identifiers:
            session.add(
                AuditEvent(
                    id=identifier,
                    household_id=actor.household_id,
                    actor_id=actor.user_id,
                    entity_type="asset",
                    entity_id=uuid4(),
                    action="delete",
                    request_id=None,
                    before_version=1,
                    after_version=None,
                    safe_diff={"changed_fields": ["name"]},
                    occurred_at=timestamp,
                )
            )
        session.commit()
    with TestClient(export_app) as client:
        path = "/api/v1/audit-events"
        # Fixture sign-ins are audited too; page only the synthetic asset events.
        query = {"limit": 2, "entity_type": "asset"}
        first = client.get(path, headers=actor.headers, params=query).json()
        second = client.get(
            path, headers=actor.headers, params=query | {"cursor": first["next_cursor"]}
        ).json()
        third = client.get(
            path, headers=actor.headers, params=query | {"cursor": second["next_cursor"]}
        ).json()
        items = first["items"] + second["items"] + third["items"]
        assert [row["id"] for row in items] == [str(value) for value in identifiers]
        assert all(
            row["actor_member_id"] == str(actor.member_id) and "safe_diff" not in row
            for row in items
        )
        assert third["next_cursor"] is None
        foreign_assets = {"entity_type": "asset"}
        assert (
            client.get(path, headers=foreign.headers, params=foreign_assets).json()["items"] == []
        )
        assert (
            client.get(
                path, headers=foreign.headers, params=query | {"cursor": first["next_cursor"]}
            ).status_code
            == 400
        )
        assert (
            client.get(
                path,
                headers=actor.headers,
                params={"action": "create", "cursor": first["next_cursor"]},
            ).status_code
            == 400
        )
        assert (
            client.get(
                path, headers=actor.headers, params={"actor_member_id": str(foreign.member_id)}
            ).status_code
            == 404
        )
        assert (
            client.get(
                path, headers=actor.headers, params={"entity_type": "unregistered"}
            ).status_code
            == 422
        )
        assert (
            client.get(
                path, headers=actor.headers, params={"since": "2026-01-01T00:00:00"}
            ).status_code
            == 422
        )
        assert (
            client.get(
                path, headers=actor.headers, params={"entity_id": items[0]["entity_id"]}
            ).json()["items"][0]["id"]
            == items[0]["id"]
        )


def test_malformed_audit_fails_without_returning_values(export_app, actors, db_engine):
    actor = actors[0]
    with Session(db_engine) as session:
        session.add(
            AuditEvent(
                household_id=actor.household_id,
                actor_id=actor.user_id,
                entity_type="asset",
                entity_id=uuid4(),
                action="update",
                request_id=None,
                before_version=1,
                after_version=2,
                safe_diff={"changed_fields": ["name"], "before": "SYNTHETIC-PRIVATE-CANARY"},
            )
        )
        session.commit()
    with TestClient(export_app) as client:
        for response in (
            client.get("/api/v1/audit-events", headers=actor.headers),
            export(client, actor),
        ):
            assert response.status_code == 503, response.text
            assert b"SYNTHETIC-PRIVATE-CANARY" not in response.content


def test_no_unauthenticated_access_and_export_auth_metadata_not_body_fields(export_app, actors):
    with TestClient(export_app) as client:
        assert client.post("/api/v1/exports", json={}).status_code == 401
        assert client.get("/api/v1/audit-events").status_code == 401
        assert (
            export(client, actors[0], household_id=str(actors[2].household_id)).status_code == 422
        )


def test_web_cookie_export_requires_origin_and_csrf(export_app, actors, db_engine):
    from sallimbook.identity.dependencies import SESSION_COOKIE
    from sallimbook.identity.schemas import LoginRequest

    actor = actors[0]
    origin = "https://synthetic-export.invalid"
    export_app.state.settings.allowed_origins = [origin]
    with Session(db_engine) as session:
        logged_in = identity.login(
            session,
            LoginRequest(
                login_name=actor.login_name,
                password=actor.password,
                device_label="합성 웹",
            ),
            "synthetic-export",
            "web",
        )
    with TestClient(export_app, base_url=origin) as client:
        client.cookies.set(SESSION_COOKIE, logged_in.token)
        assert client.post("/api/v1/exports", json={}).status_code == 403
        assert (
            client.post("/api/v1/exports", json={}, headers={"Origin": origin}).status_code == 403
        )
        decoded(
            client.post(
                "/api/v1/exports",
                json={"formats": ["json"]},
                headers={
                    "Origin": origin,
                    "X-CSRF-Token": logged_in.csrf_token,
                },
            )
        )
