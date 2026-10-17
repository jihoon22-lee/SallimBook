"""Independent SQL bypass checks for staged/active vault graphs; synthetic opaque bytes."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_vault import (
    accept,
    card,
    card_detail,
    finalize,
    initialize,
    member_wrap,
    prepare,
    share,
    stage,
    start_rotation,
    status,
    write_secret,
)
from test_vault import actors as actors
from test_vault import vault_app as vault_app

from sallimbook.vault.models import VaultMembership
from sallimbook.vault.schemas import MemberWrappingInput
from sallimbook.vault.storage import actor_fields, store_member_wrapping

pytestmark = pytest.mark.database


def reject(engine, statements, parameters):
    with Session(engine) as session, pytest.raises(DBAPIError):
        for statement in statements:
            session.execute(text(statement), parameters)
        session.commit()


@pytest.mark.parametrize(
    "kind", ["manifest_card", "manifest_member", "current_secret", "membership"]
)
def test_staging_freezes_direct_writes_and_retains_the_source_snapshot(vault_app, actors, kind):
    actor, partner, _ = actors
    with TestClient(vault_app) as client:
        initialize(client, actor)
        accept(client, partner, share(client, actor, partner))
        row = card(client, actor, archived=True)
        assert write_secret(client, actor, row).status_code == 200
        rotation = start_rotation(client, actor)
        statements = {
            "manifest_card": "UPDATE vault_rotation_cards SET source_revision=source_revision+1 "
            "WHERE household_id=:hh",
            "manifest_member": "UPDATE vault_rotation_members "
            "SET source_membership_version=source_membership_version+1 WHERE household_id=:hh",
            "current_secret": "UPDATE card_secret_envelopes SET ciphertext=NULL, purged_at=now(), "
            "is_current=false, version=version+1 WHERE household_id=:hh AND key_version=1",
            "membership": "UPDATE vault_memberships SET status='revoked', revoked_at=now(), "
            "version=version+1 WHERE household_id=:hh AND member_id=:member",
        }
        reject(
            vault_app.state.engine,
            [statements[kind]],
            {"hh": actor.household_id, "member": partner.member_id},
        )
        assert status(client, actor)["current_key_version"] == 1
        assert card_detail(client, actor, row["id"])["has_secret"]
        # Rejected bypass must not poison the normal complete atomic rotation.
        rotation = prepare(client, actor, rotation, [actor, partner])
        rotation = stage(client, actor, rotation, rotation["cards"][0])
        assert finalize(client, actor, rotation).status_code == 200


def test_database_rejects_partial_atomic_activation_even_if_api_is_bypassed(vault_app, actors):
    actor = actors[0]
    with TestClient(vault_app) as client:
        initialize(client, actor)
        row = card(client, actor)
        assert write_secret(client, actor, row).status_code == 200
        rotation = prepare(client, actor, start_rotation(client, actor), [actor])
        # A prepared bundle has no migrated card yet. Simulate all pointer writes,
        # then force the deferred transaction-wide checks at commit.
        reject(
            vault_app.state.engine,
            [
                "UPDATE vault_versions SET state='retired', retired_at=now(), version=version+1 "
                "WHERE household_id=:hh AND key_version=1",
                "UPDATE vault_versions SET state='current', activated_at=now(), version=version+1 "
                "WHERE household_id=:hh AND key_version=2",
                "UPDATE vault_states SET current_key_version=2, version=version+1 "
                "WHERE household_id=:hh",
            ],
            {"hh": actor.household_id},
        )
        assert status(client, actor)["current_key_version"] == 1
        response = client.get(f"/api/v1/cards/{row['id']}/secret-envelope", headers=actor.headers)
        assert response.status_code == 200 and response.json()["key_version"] == 1
        rotation = stage(client, actor, rotation, rotation["cards"][0])
        assert finalize(client, actor, rotation).status_code == 200


def test_member_cannot_be_directly_activated_with_a_forged_current_wrapping(vault_app, actors):
    actor, partner, _ = actors
    with TestClient(vault_app) as client:
        initialize(client, actor)
        with Session(vault_app.state.engine) as session, pytest.raises(DBAPIError):
            store_member_wrapping(
                session,
                actor.principal,
                MemberWrappingInput.model_validate(member_wrap(partner, seed=50)),
                state="current",
            )
            session.add(
                VaultMembership(
                    **actor_fields(actor.principal),
                    member_id=partner.member_id,
                    status="active",
                    joined_key_version=1,
                )
            )
            session.commit()
        assert status(client, partner)["own_membership"] == "not_enrolled"
        assert client.get("/api/v1/vault/wrappings/me", headers=partner.headers).status_code == 403
        accept(client, partner, share(client, actor, partner, seed=51))
        assert status(client, partner)["own_membership"] == "active"


def test_card_last_four_cannot_be_detached_from_current_ciphertext(vault_app, actors):
    actor = actors[0]
    with TestClient(vault_app) as client:
        initialize(client, actor)
        row = card(client, actor)
        assert write_secret(client, actor, row).status_code == 200
        reject(
            vault_app.state.engine,
            [
                "UPDATE cards SET last_four='9999', version=version+1 WHERE id=:id",
            ],
            {"id": row["id"]},
        )
        current = card_detail(client, actor, row["id"])
        assert current["last_four"] == "0000" and current["has_secret"]
