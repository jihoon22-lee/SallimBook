"""Synthetic family identity boundaries and legacy-client preservation."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_insurance_core import actors as actors
from test_insurance_core import app as app
from test_insurance_core import case_payload, policy_payload, vheaders
from test_insurance_core import key_file as key_file

from sallimbook.audit.router import router as audit_router
from sallimbook.identity.auth_models import HouseholdMember
from sallimbook.identity.people_models import HouseholdPerson
from sallimbook.identity.people_router import router
from sallimbook.insurance.models import InsuranceCaseRevision

BASE = "/api/v1/household/people"
INS = "/api/v1/insurance"


def current(actor):
    return {**actor.headers, "X-SallimBook-People": "1"}


def family(client, actor, name="합성 자녀"):
    payload = {"display_name": name, "relation": "child"}
    headers = {**current(actor), "Idempotency-Key": str(uuid4())}
    result = client.post(BASE, json=payload, headers=headers)
    assert result.status_code == 201, result.text
    assert client.post(BASE, json=payload, headers=headers).json() == result.json()
    assert (
        client.post(BASE, json={**payload, "display_name": "변경"}, headers=headers).status_code
        == 409
    )
    return result.json()["id"]


@pytest.mark.database
def test_family_scope_versions_archive_and_identity_boundaries(app, actors, db_engine):
    app.include_router(router)
    first, spouse, foreign = actors
    with TestClient(app) as client:
        person = family(client, first)
        same_name = family(client, first)
        assert person != same_name
        page = client.get(BASE, headers=spouse.headers).json()
        assert len(page["items"]) == 4
        assert {p["id"] for p in page["items"] if p["member_id"]} == {
            str(first.member_id),
            str(spouse.member_id),
        }
        assert (
            client.patch(
                BASE + "/" + person, json={"active": False}, headers=vheaders(foreign)
            ).status_code
            == 404
        )
        assert (
            client.get(BASE, params={"cursor": person}, headers=foreign.headers).status_code == 404
        )
        assert (
            client.patch(
                BASE + "/" + str(first.member_id),
                json={"display_name": "바꾸기"},
                headers=vheaders(first),
            ).status_code
            == 422
        )
        changed = client.patch(
            BASE + "/" + person, json={"active": False}, headers=vheaders(spouse)
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["active"] is False
        assert (
            client.patch(
                BASE + "/" + person, json={"display_name": "수정"}, headers=vheaders(first)
            ).status_code
            == 409
        )
        restored = client.patch(
            BASE + "/" + person, json={"active": True}, headers=vheaders(first, 2)
        )
        assert restored.json()["active"] is True
        assert (
            client.post(
                BASE,
                json={
                    "display_name": "위조",
                    "relation": "child",
                    "member_id": str(first.member_id),
                },
                headers={**first.headers, "Idempotency-Key": str(uuid4())},
            ).status_code
            == 422
        )
    with Session(db_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(HouseholdMember)
                .where(HouseholdMember.household_id == first.household_id)
            )
            == 2
        )
        assert session.get(HouseholdPerson, person).member_id is None
        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(
                update(HouseholdPerson)
                .where(HouseholdPerson.id == person)
                .values(created_by_member_id=person)
            )


@pytest.mark.database
def test_family_insurance_legacy_guard_and_archived_history(app, actors, db_engine):
    app.include_router(router)
    first, spouse, foreign = actors
    with TestClient(app) as client:
        person = family(client, first)
        payload = case_payload(first, patient_member_id=person)
        assert client.post(INS + "/cases", json=payload, headers=first.headers).status_code == 422
        case = client.post(INS + "/cases", json=payload, headers=current(first))
        assert case.status_code == 201, case.text
        path = INS + "/cases/" + case.json()["id"]
        for target in (str(first.member_id), str(spouse.member_id)):
            assert (
                client.patch(
                    path,
                    json={"patient_member_id": target, "reason": "합성 정정"},
                    headers=vheaders(first),
                ).status_code
                == 422
            )
        assert (
            client.patch(
                path,
                json={"title": "가족 사건 유지", "reason": "합성 정정"},
                headers=vheaders(first),
            ).status_code
            == 200
        )
        client.patch(BASE + "/" + person, json={"active": False}, headers=vheaders(first))
        assert client.post(INS + "/cases", json=payload, headers=current(first)).status_code == 422
        assert (
            client.patch(
                path,
                json={"financial_state": "settled", "reason": "합성 정산"},
                headers=vheaders(first, 2),
            ).status_code
            == 200
        )
        assert (
            client.patch(
                path,
                json={"financial_state": "open", "reason": "합성 재개방"},
                headers=vheaders(first, 3),
            ).status_code
            == 200
        )
        assert len(client.get(path + "/history", headers=spouse.headers).json()["items"]) == 4
        assert (
            client.get(
                INS + "/cases", params={"patient_member_id": person}, headers=foreign.headers
            ).status_code
            == 404
        )
        client.patch(BASE + "/" + person, json={"active": True}, headers=vheaders(first, 2))
        policy = client.post(
            INS + "/policies",
            json=policy_payload(
                insured_member_id=person, policyholder_member_id=str(first.member_id)
            ),
            headers=current(first),
        )
        assert policy.status_code == 201, policy.text
        policy_path = INS + "/policies/" + policy.json()["id"]
        assert (
            client.patch(
                policy_path, json={"insured_member_id": None}, headers=vheaders(first)
            ).status_code
            == 422
        )
        assert (
            client.patch(
                policy_path, json={"note": "기존 가족 유지"}, headers=vheaders(first)
            ).status_code
            == 200
        )
        assert (
            client.post(
                INS + "/policies",
                json=policy_payload(policyholder_member_id=person),
                headers=current(first),
            ).status_code
            == 404
        )
    with Session(db_engine) as session:
        assert {
            str(r.patient_member_id) for r in session.scalars(select(InsuranceCaseRevision))
        } == {person}


@pytest.mark.database
def test_legacy_audit_filters_before_pagination_and_binds_cursor(app, actors):
    app.include_router(router)
    app.include_router(audit_router)
    first, _, _ = actors
    with TestClient(app) as client:
        for _ in range(3):
            family(client, first)
            result = client.post(INS + "/cases", json=case_payload(first), headers=current(first))
            assert result.status_code == 201
        page = client.get("/api/v1/audit-events?limit=2", headers=first.headers)
        assert page.status_code == 200, page.text
        data = page.json()
        assert len(data["items"]) == 2 and data["next_cursor"]
        assert all(row["entity_type"] != "household_person" for row in data["items"])
        assert (
            client.get(
                "/api/v1/audit-events",
                params={"cursor": data["next_cursor"]},
                headers=current(first),
            ).status_code
            == 400
        )
        complete = client.get("/api/v1/audit-events", headers=current(first)).json()
        assert sum(row["entity_type"] == "household_person" for row in complete["items"]) == 3


@pytest.mark.database
def test_replay_after_edit_returns_original_reference(app, actors):
    app.include_router(router)
    first, _, _ = actors
    with TestClient(app) as client:
        headers = {**current(first), "Idempotency-Key": str(uuid4())}
        payload = {"display_name": "합성 부모", "relation": "parent"}
        created = client.post(BASE, json=payload, headers=headers).json()
        renamed = client.patch(
            BASE + "/" + created["id"],
            json={"display_name": "합성 보호자"},
            headers=vheaders(first),
        )
        assert renamed.status_code == 200
        assert renamed.json()["version"] == 2
        assert client.post(BASE, json=payload, headers=headers).json() == created


@pytest.mark.database
def test_migration_preserves_immutable_revisions_backfills_revoked_and_refuses_family_downgrade(
    app, actors, db_engine
):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    first, spouse, _ = actors
    app.include_router(router)

    def migrate(direction, revision):
        with db_engine.connect() as connection:
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            getattr(command, direction)(config, revision)

    with TestClient(app) as client:
        case = client.post(INS + "/cases", json=case_payload(first), headers=first.headers)
        assert case.status_code == 201
        path = INS + "/cases/" + case.json()["id"]
        assert (
            client.patch(
                path, json={"title": "합성 수정", "reason": "합성 사유"}, headers=vheaders(first)
            ).status_code
            == 200
        )
        with db_engine.connect() as connection:
            before = (
                connection.execute(
                    text(
                        "SELECT row_to_json(r)::text FROM insurance_case_revisions r "
                        "ORDER BY version"
                    )
                )
                .scalars()
                .all()
            )
        migrate("downgrade", "0018_install_device")
        with db_engine.begin() as connection:
            connection.execute(
                text("UPDATE household_members SET status='revoked' WHERE id=:id"),
                {"id": spouse.member_id},
            )
        migrate("upgrade", "head")
        with Session(db_engine) as session:
            assert session.get(HouseholdPerson, spouse.member_id).member_id == spouse.member_id
            assert (
                session.execute(
                    text(
                        "SELECT row_to_json(r)::text FROM insurance_case_revisions r "
                        "ORDER BY version"
                    )
                )
                .scalars()
                .all()
                == before
            )
        people = client.get(BASE, headers=first.headers).json()["items"]
        assert not next(p for p in people if p["id"] == str(spouse.member_id))["active"]
        family(client, first)
        with db_engine.connect() as connection:
            before_failed_downgrade = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        with pytest.raises(DBAPIError, match="Household family data exists"):
            migrate("downgrade", "0018_install_device")
        with db_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == before_failed_downgrade
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM household_people WHERE member_id IS NULL")
                )
                == 1
            )
