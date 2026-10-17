"""Synthetic insurance metadata, identifier disclosure and case-tree regressions."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier, Event
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from test_accounts import key_file as key_file
from test_accounts import make_actor
from test_income import headers, make_account
from test_recurring import generate, obligation_for, post_rule, rule_payload, settle

from sallimbook.assets.models import Asset
from sallimbook.cashflow.recurring_models import RecurringRuleVersion, ScheduledObligation
from sallimbook.cashflow.recurring_router import router as recurring_router
from sallimbook.config import Settings
from sallimbook.core.audit import AuditEvent
from sallimbook.core.errors import DomainError
from sallimbook.core.http import install_http_contract
from sallimbook.core.types import SEOUL
from sallimbook.identity import service as identity
from sallimbook.identity.auth_models import AuthSession, HouseholdMember, RegisteredDevice
from sallimbook.identity.models import Household
from sallimbook.insurance import service
from sallimbook.insurance.models import (
    InsuranceCaseRevision,
    InsurancePolicy,
    MedicalNode,
    PolicyPremiumLink,
)
from sallimbook.insurance.router import router
from sallimbook.insurance.schemas import (
    CaseInput,
    MedicalNodeInput,
    MedicalNodePatch,
    PolicyCreate,
    PremiumLinkCreate,
)

SYNTHETIC_NUMBER = "SYNTHETIC-POLICY-0001"
BASE = "/api/v1/insurance"


def policy_payload(**changes):
    return {
        "insurer": "합성 보험사",
        "product_name": "합성 보험상품",
        "contract_start": "2025-01-01",
        "contract_end": "2050-12-31",
        "coverage_start": "2025-02-01",
        "coverage_end": "2060-12-31",
        "payment_start": "2025-01-10",
        "payment_end": "2035-01-10",
        **changes,
    }


def case_payload(actor, **changes):
    return {
        "title": "합성 사건",
        "patient_member_id": str(actor.member_id),
        "start_on": "2026-01-01",
        "diagnosis_note": "합성 진료 설명",
        "diagnosis_code": "SYNTHETIC",
        **changes,
    }


def vheaders(actor, value=1):
    return {**actor.headers, "If-Match": f'"{value}"'}


def create(client, actor, resource, payload):
    result = client.post(BASE + resource, headers=actor.headers, json=payload)
    assert result.status_code == 201, result.text
    assert result.headers["etag"] == '"1"'
    assert result.headers["cache-control"] == "no-store"
    return result.json()


def test_insurance_openapi_versions_and_list_privacy():
    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    assert sum(len(v) for v in schema["paths"].values()) == 21
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method in {"patch", "delete"}:
                assert any(
                    p["in"] == "header" and p["name"] == "If-Match" and p["required"]
                    for p in operation["parameters"]
                )
            if method == "post" and not path.endswith("/reveal"):
                assert {"ETag", "Location"} <= operation["responses"]["201"]["headers"].keys()
            assert not any(p["name"] == "Idempotency-Key" for p in operation.get("parameters", []))
    models = schema["components"]["schemas"]
    assert (
        not {"policy_number", "policy_number_ciphertext", "number_nonce", "number_key_version"}
        & models["PolicyResponse"]["properties"].keys()
    )
    assert not {"diagnosis_note", "diagnosis_code"} & models["CaseListItem"]["properties"].keys()
    assert "diagnosis_note" in models["CaseResponse"]["properties"]
    assert "policy_id" not in models["CaseInput"]["properties"]
    assert not any(
        "amount" in key or "cash" in key for key in models["MedicalNodeInput"]["properties"]
    )


@pytest.fixture
def actors(db_engine):
    first = make_actor(db_engine)
    return first, make_actor(db_engine, first.household_id), make_actor(db_engine)


@pytest.fixture
def app(db_engine, key_file):
    app = FastAPI()
    app.state.engine = db_engine
    app.state.settings = Settings(
        environment="test", field_encryption_key_file=key_file, _env_file=None
    )
    install_http_contract(app)
    app.include_router(router)
    app.include_router(recurring_router)
    return app


@pytest.mark.database
class TestInsurancePolicy:
    def test_policy_periods_mask_envelope_reveal_update_clear_and_safe_audit(
        self, app, actors, db_engine, caplog
    ):
        actor, spouse, _ = actors
        with TestClient(app) as client:
            policy = create(
                client,
                actor,
                "/policies",
                policy_payload(
                    policy_number=SYNTHETIC_NUMBER,
                    policyholder_member_id=str(actor.member_id),
                    insured_member_id=str(spouse.member_id),
                ),
            )
            path = f"{BASE}/policies/{policy['id']}"
            assert policy["masked_number"] == "**** 0001" and policy["has_number"] is True
            assert policy["contract_end"] != policy["coverage_end"] != policy["payment_end"]
            for response in (
                client.get(path, headers=spouse.headers),
                client.get(BASE + "/policies", headers=actor.headers),
            ):
                assert response.status_code == 200 and SYNTHETIC_NUMBER not in response.text
                assert "ciphertext" not in response.text and "nonce" not in response.text
            revealed = client.post(path + "/reveal", headers=actor.headers)
            assert (
                revealed.status_code == 200 and revealed.json()["policy_number"] == SYNTHETIC_NUMBER
            )
            assert revealed.json()["display_for_seconds"] == 30
            assert revealed.headers["cache-control"] == "no-store"
            changed = client.patch(path, headers=vheaders(spouse), json={"status": "ended"})
            assert changed.status_code == 200 and changed.json()["version"] == 2
            assert (
                client.patch(
                    path, headers=vheaders(actor), json={"product_name": "충돌"}
                ).status_code
                == 409
            )
            app.state.settings.field_encryption_key_file = None
            failed = client.patch(
                path, headers=vheaders(actor, 2), json={"policy_number": "SYNTHETIC-NEW-0002"}
            )
            assert failed.status_code == 503
            assert client.get(path, headers=actor.headers).json()["version"] == 2
            cleared = client.patch(path, headers=vheaders(actor, 2), json={"policy_number": None})
            assert cleared.status_code == 200 and cleared.json()["has_number"] is False
            assert client.post(path + "/reveal", headers=actor.headers).status_code == 409
        assert SYNTHETIC_NUMBER not in caplog.text
        with Session(db_engine) as session:
            row = session.get(InsurancePolicy, UUID(policy["id"]))
            assert (
                row.policy_number_ciphertext
                is row.number_nonce
                is row.number_key_version
                is row.last_four
                is None
            )
            events = list(session.scalars(select(AuditEvent).where(AuditEvent.entity_id == row.id)))
            assert len([r for r in events if r.action == "reveal"]) == 1
            assert SYNTHETIC_NUMBER not in str([r.safe_diff for r in events])
            assert all(set(r.safe_diff) == {"changed_fields"} for r in events)

    def test_ciphertext_is_authenticated_to_policy_and_bad_key_has_no_plaintext(
        self, app, actors, db_engine, caplog
    ):
        actor = actors[0]
        with TestClient(app) as client:
            first = create(
                client, actor, "/policies", policy_payload(policy_number=SYNTHETIC_NUMBER)
            )
            second = create(
                client, actor, "/policies", policy_payload(policy_number="SYNTHETIC-OTHER-0002")
            )
            with Session(db_engine) as session:
                a, b = [session.get(InsurancePolicy, UUID(r["id"])) for r in (first, second)]
                assert SYNTHETIC_NUMBER.encode() not in a.policy_number_ciphertext
                assert a.number_nonce != b.number_nonce
                b.policy_number_ciphertext, b.number_nonce, b.number_key_version = (
                    a.policy_number_ciphertext,
                    a.number_nonce,
                    a.number_key_version,
                )
                session.commit()
            bad = client.post(f"{BASE}/policies/{second['id']}/reveal", headers=actor.headers)
            assert (
                bad.status_code == 503
                and bad.json()["error"]["code"] == "POLICY_NUMBER_UNAVAILABLE"
            )
            assert SYNTHETIC_NUMBER not in bad.text and SYNTHETIC_NUMBER not in caplog.text

    def test_foreign_policy_links_members_and_inactive_valuation_are_rejected(
        self, app, actors, db_engine
    ):
        actor, spouse, foreign = actors
        account = make_account(db_engine, actor)
        with TestClient(app) as client:
            other = create(client, foreign, "/policies", policy_payload())
            for suffix, method, body in (
                ("", "get", None),
                ("", "patch", {"status": "ended"}),
                ("/reveal", "post", None),
                ("/coverages", "get", None),
                ("/premium-links", "get", None),
            ):
                response = client.request(
                    method,
                    f"{BASE}/policies/{other['id']}{suffix}",
                    headers=vheaders(actor),
                    **({"json": body} if body else {}),
                )
                assert response.status_code == 404
            assert (
                client.post(
                    BASE + "/policies",
                    headers=actor.headers,
                    json=policy_payload(insured_member_id=str(foreign.member_id)),
                ).status_code
                == 404
            )
            policy = create(
                client,
                actor,
                "/policies",
                policy_payload(
                    valuation_asset_id=str(account.asset_id),
                    insured_member_id=str(spouse.member_id),
                ),
            )
            with Session(db_engine) as session:
                asset = session.get(Asset, account.asset_id)
                asset.ended_on = date(2026, 1, 1)
                asset.archived_at = identity.utcnow()
                session.get(HouseholdMember, spouse.member_id).status = "revoked"
                session.commit()
            assert (
                client.post(
                    BASE + "/policies",
                    headers=actor.headers,
                    json=policy_payload(valuation_asset_id=str(account.asset_id)),
                ).status_code
                == 422
            )
            assert (
                client.post(
                    BASE + "/policies",
                    headers=actor.headers,
                    json=policy_payload(insured_member_id=str(spouse.member_id)),
                ).status_code
                == 422
            )
            changed = client.patch(
                f"{BASE}/policies/{policy['id']}",
                headers=vheaders(actor),
                json={"note": "과거 연결 유지", "status": "ended"},
            )
            assert changed.status_code == 200
            assert (
                client.patch(
                    f"{BASE}/policies/{policy['id']}",
                    headers=vheaders(actor, 2),
                    json={"status": "active"},
                ).status_code
                == 422
            )

    def test_coverages_zero_unknown_period_patch_parent_scope(self, app, actors):
        actor = actors[0]
        with TestClient(app) as client:
            policy = create(client, actor, "/policies", policy_payload())
            other = create(client, actor, "/policies", policy_payload())
            path = f"/policies/{policy['id']}/coverages"
            zero = create(
                client,
                actor,
                path,
                {
                    "name": "합성 정액",
                    "benefit_type": "fixed",
                    "insured_amount_krw": "0",
                    "coverage_start": "2025-03-01",
                },
            )
            unknown = create(
                client, actor, path, {"name": "합성 실손", "benefit_type": "reimbursement"}
            )
            assert zero["insured_amount_krw"] == "0" and unknown["insured_amount_krw"] is None
            response = client.patch(
                BASE + path + "/" + zero["id"],
                headers=vheaders(actor),
                json={"coverage_end": "2025-01-01"},
            )
            assert response.status_code == 422
            assert (
                client.patch(
                    f"{BASE}/policies/{other['id']}/coverages/{zero['id']}",
                    headers=vheaders(actor),
                    json={"active": False},
                ).status_code
                == 404
            )
            ended = client.patch(
                BASE + path + "/" + zero["id"], headers=vheaders(actor), json={"active": False}
            )
            assert ended.status_code == 200 and ended.json()["version"] == 2
            visible = client.get(BASE + path + "?active=true", headers=actor.headers).json()
            assert [r["id"] for r in visible["items"]] == [unknown["id"]]

    def test_premium_single_source_past_payment_and_unlink_preserved(self, app, actors, db_engine):
        actor = actors[0]
        with TestClient(app) as client:
            policy = create(client, actor, "/policies", policy_payload())
            other = create(client, actor, "/policies", policy_payload())
            rule = post_rule(client, actor, category="insurance")
            generate(client, actor, rule["id"], end="2026-01-31")
            obligation = obligation_for(client, actor, "2026-01")
            settle(client, actor, obligation, amount="33000")
            path = f"/policies/{policy['id']}/premium-links"
            link = create(client, actor, path, {"rule_id": rule["id"]})
            assert link["rule"]["versions"][0]["expected_amount_krw"] == "33000"
            changed = client.patch(
                f"/api/v1/recurring-rules/{rule['id']}",
                headers=headers(actor, version=1),
                json=rule_payload()
                | {
                    "effective_from": (
                        identity.utcnow().astimezone(SEOUL).date() + timedelta(days=1)
                    ).isoformat(),
                    "expected_amount_krw": "44000",
                    "reason": "합성 보험료 변경",
                },
            )
            assert changed.status_code == 200, changed.text
            listed = client.get(BASE + path, headers=actor.headers).json()["items"][0]
            assert [r["expected_amount_krw"] for r in listed["rule"]["versions"]] == [
                "33000",
                "44000",
            ]
            assert obligation_for(client, actor, "2026-01")["actual_amount_krw"] == "33000"
            unlinked = client.patch(
                BASE + path + "/" + link["id"], headers=vheaders(actor), json={"active": False}
            )
            assert unlinked.status_code == 200 and unlinked.json()["ended_at"] is not None
            duplicate = client.post(
                f"{BASE}/policies/{other['id']}/premium-links",
                headers=actor.headers,
                json={"rule_id": rule["id"]},
            )
            assert (
                duplicate.status_code == 409
                and duplicate.json()["error"]["code"] == "PREMIUM_RULE_ALREADY_LINKED"
            )
            assert (
                client.patch(
                    BASE + path + "/" + link["id"],
                    headers=vheaders(actor, 2),
                    json={"active": True},
                ).status_code
                == 200
            )
        with Session(db_engine) as session:
            assert session.scalar(select(func.count()).select_from(PolicyPremiumLink)) == 1
            assert session.scalar(select(func.count()).select_from(RecurringRuleVersion)) == 2
            assert session.scalar(select(func.count()).select_from(ScheduledObligation)) == 1

    def test_premium_scope_availability_and_batch_query_count(self, app, actors, db_engine):
        actor, _, foreign = actors
        with TestClient(app) as client:
            policy = create(client, actor, "/policies", policy_payload())
            path = f"/policies/{policy['id']}/premium-links"
            foreign_rule = post_rule(client, foreign)
            assert (
                client.post(
                    BASE + path, headers=actor.headers, json={"rule_id": foreign_rule["id"]}
                ).status_code
                == 404
            )
            ended = post_rule(
                client,
                actor,
                effective_from="2025-01-01",
                effective_until="2025-03-01",
                end_reason="합성 종료",
            )
            assert (
                client.post(
                    BASE + path, headers=actor.headers, json={"rule_id": ended["id"]}
                ).status_code
                == 422
            )
            counts = []
            for additional in (1, 3):
                for _ in range(additional):
                    rule = post_rule(client, actor)
                    create(client, actor, path, {"rule_id": rule["id"]})
                statements = []

                def captured(
                    conn, cursor, statement, parameters, context, executemany, statements=statements
                ):
                    if statement.startswith("SELECT"):
                        statements.append(statement)

                event.listen(db_engine, "before_cursor_execute", captured)
                try:
                    response = client.get(BASE + path, headers=actor.headers)
                    assert response.status_code == 200
                finally:
                    event.remove(db_engine, "before_cursor_execute", captured)
                counts.append(len(statements))
            assert counts[0] == counts[1]
            link = response.json()["items"][0]
            assert (
                client.patch(
                    f"{BASE}/policies/{policy['id']}",
                    headers=vheaders(actor),
                    json={"status": "lapsed"},
                ).status_code
                == 200
            )
            assert (
                client.patch(
                    BASE + path + "/" + link["id"], headers=vheaders(actor), json={"active": False}
                ).status_code
                == 200
            )
            assert (
                client.patch(
                    BASE + path + "/" + link["id"],
                    headers=vheaders(actor, 2),
                    json={"active": True},
                ).status_code
                == 422
            )

    def test_concurrent_premium_links_choose_one_policy(self, app, actors, db_engine):
        actor = actors[0]
        with TestClient(app) as client:
            policies = [create(client, actor, "/policies", policy_payload()) for _ in range(2)]
            rule = post_rule(client, actor)
        barrier = Barrier(2)

        def link(policy):
            with Session(db_engine) as session:
                barrier.wait(timeout=10)
                try:
                    service.create_premium_link(
                        session,
                        actor.principal,
                        UUID(policy["id"]),
                        PremiumLinkCreate(rule_id=rule["id"]),
                    )
                    return "created"
                except DomainError as error:
                    return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(link, policies)) == ["PREMIUM_RULE_ALREADY_LINKED", "created"]


@pytest.mark.database
class TestInsuranceCase:
    def test_independent_states_reopening_history_and_list_privacy(self, app, actors, db_engine):
        actor, spouse, _ = actors
        with TestClient(app) as client:
            item = create(client, actor, "/cases", case_payload(actor))
            path = f"{BASE}/cases/{item['id']}"
            listed = client.get(BASE + "/cases", headers=spouse.headers)
            assert "diagnosis_note" not in listed.text and "diagnosis_code" not in listed.text
            assert "합성 진료 설명" not in listed.text
            ended = client.patch(
                path,
                headers=vheaders(spouse),
                json={
                    "treatment_state": "ended",
                    "end_on": "2026-01-10",
                    "reason": "합성 치료 종료",
                },
            )
            assert ended.status_code == 200 and ended.json()["financial_state"] == "open"
            settled = client.patch(
                path,
                headers=vheaders(actor, 2),
                json={"financial_state": "settled", "reason": "합성 정산 종료"},
            )
            assert settled.status_code == 200
            reopen = client.patch(
                path,
                headers=vheaders(spouse, 3),
                json={"treatment_state": "ongoing", "end_on": None, "reason": "합성 재진"},
            )
            assert reopen.status_code == 200 and reopen.json()["financial_state"] == "settled"
            assert (
                client.patch(
                    path, headers=vheaders(actor, 3), json={"title": "충돌", "reason": "합성"}
                ).status_code
                == 409
            )
            first = client.get(path + "/history?limit=2", headers=actor.headers).json()
            second = client.get(
                path + f"/history?limit=2&cursor={first['next_cursor']}", headers=actor.headers
            ).json()
            assert [r["version"] for r in first["items"] + second["items"]] == [4, 3, 2, 1]
            assert first["items"][0]["diagnosis_note"] == "합성 진료 설명"
            assert second["items"][1]["treatment_state"] == "ongoing"
            assert client.delete(path, headers=vheaders(actor, 4)).status_code == 405
        with Session(db_engine) as session:
            for command in (
                update(InsuranceCaseRevision).values(title="합성 변조"),
                delete(InsuranceCaseRevision),
            ):
                with pytest.raises(DBAPIError):
                    session.execute(command)
                    session.flush()
                session.rollback()
            logs = list(
                session.scalars(select(AuditEvent).where(AuditEvent.entity_id == UUID(item["id"])))
            )
            assert any(row.action == "reopen" for row in logs)
            assert "합성 진료 설명" not in str([row.safe_diff for row in logs])

    def test_case_scope_actual_dates_and_patient_validation(self, app, actors):
        actor, _, foreign = actors
        with TestClient(app) as client:
            other = create(client, foreign, "/cases", case_payload(foreign))
            for suffix in ("", "/history", "/nodes"):
                assert (
                    client.get(
                        f"{BASE}/cases/{other['id']}{suffix}", headers=actor.headers
                    ).status_code
                    == 404
                )
            assert (
                client.post(
                    BASE + "/cases", headers=actor.headers, json=case_payload(foreign)
                ).status_code
                == 404
            )
            tomorrow = (identity.utcnow().astimezone(SEOUL).date() + timedelta(days=1)).isoformat()
            assert (
                client.post(
                    BASE + "/cases",
                    headers=actor.headers,
                    json=case_payload(actor, start_on=tomorrow),
                ).status_code
                == 422
            )
            item = create(client, actor, "/cases", case_payload(actor))
            path = f"{BASE}/cases/{item['id']}"
            assert (
                client.patch(path, headers=vheaders(actor), json={"reason": "합성"}).status_code
                == 422
            )
            assert (
                client.patch(
                    path, headers=vheaders(actor), json={"end_on": "2026-01-02", "reason": "합성"}
                ).status_code
                == 422
            )
            assert (
                client.patch(
                    path, headers=actor.headers, json={"title": "합성", "reason": "합성"}
                ).status_code
                == 400
            )

    def test_prescription_tree_parent_cycle_scope_leaf_delete_and_order(self, app, actors):
        actor, _, foreign = actors
        with TestClient(app) as client:
            case = create(client, actor, "/cases", case_payload(actor))
            other = create(client, actor, "/cases", case_payload(actor))
            foreign_case = create(client, foreign, "/cases", case_payload(foreign))
            path = f"/cases/{case['id']}/nodes"
            root = create(client, actor, path, {"kind": "outpatient", "label": "합성 외래"})
            prescription = create(
                client,
                actor,
                path,
                {"kind": "prescription", "label": "합성 처방", "parent_id": root["id"]},
            )
            pharmacy = create(
                client,
                actor,
                path,
                {
                    "kind": "pharmacy",
                    "label": "합성 약국",
                    "parent_id": prescription["id"],
                    "sort_order": 2,
                },
            )
            assert not any("amount" in name or "cash" in name for name in prescription)
            assert (
                client.patch(
                    BASE + path + "/" + root["id"],
                    headers=vheaders(actor),
                    json={"parent_id": pharmacy["id"]},
                ).json()["error"]["code"]
                == "MEDICAL_NODE_CYCLE"
            )
            for wrong_case, owner in ((other, actor), (foreign_case, foreign)):
                foreign_node = create(
                    client,
                    owner,
                    f"/cases/{wrong_case['id']}/nodes",
                    {"kind": "group", "label": "합성 그룹"},
                )
                assert (
                    client.patch(
                        BASE + path + "/" + pharmacy["id"],
                        headers=vheaders(actor),
                        json={"parent_id": foreign_node["id"]},
                    ).status_code
                    == 404
                )
                assert (
                    client.get(
                        f"{BASE}/cases/{wrong_case['id']}/nodes/{root['id']}", headers=actor.headers
                    ).status_code
                    == 404
                )
            assert (
                client.delete(BASE + path + "/" + root["id"], headers=vheaders(actor)).status_code
                == 409
            )
            page = client.get(BASE + path + "?limit=2", headers=actor.headers).json()
            next_page = client.get(
                BASE + path + f"?limit=2&cursor={page['next_cursor']}", headers=actor.headers
            ).json()
            assert {r["id"] for r in page["items"] + next_page["items"]} == {
                root["id"],
                prescription["id"],
                pharmacy["id"],
            }
            assert (
                client.delete(
                    BASE + path + "/" + pharmacy["id"], headers=vheaders(actor)
                ).status_code
                == 204
            )
            assert (
                client.get(BASE + path + "/" + pharmacy["id"], headers=actor.headers).status_code
                == 404
            )
            assert (
                client.delete(
                    BASE + path + "/" + prescription["id"], headers=vheaders(actor)
                ).status_code
                == 204
            )

    @pytest.mark.parametrize("limit", [1, 2, 3])
    def test_node_pages_follow_tree_order_with_uuid_ties(self, app, actors, limit):
        actor = actors[0]
        with TestClient(app) as client:
            case = create(client, actor, "/cases", case_payload(actor))
            path = f"/cases/{case['id']}/nodes"

            def node(order, parent=None):
                return create(
                    client,
                    actor,
                    path,
                    {
                        "kind": "group",
                        "label": "합성 정렬 항목",
                        "sort_order": order,
                        "parent_id": parent,
                    },
                )

            last = node(1000000)
            first = node(0)
            child_last = node(100, first["id"])
            ties = sorted([node(2, first["id"]), node(2, first["id"])], key=lambda r: r["id"])
            deep = node(1000000, ties[0]["id"])
            expected = [first, ties[0], deep, ties[1], child_last, last]
            actual, cursor = [], None
            for _ in range(len(expected) + 1):
                query = {"limit": limit, **({"cursor": cursor} if cursor else {})}
                response = client.get(BASE + path, params=query, headers=actor.headers)
                assert response.status_code == 200, response.text
                page = response.json()
                assert [r["id"] for r in page["items"]] == [
                    r["id"] for r in expected[len(actual) : len(actual) + limit]
                ]
                actual.extend(page["items"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
                assert cursor == actual[-1]["id"]
            assert [r["id"] for r in actual] == [r["id"] for r in expected]
            assert cursor is None
            assert client.get(
                BASE + path, params={"cursor": last["id"]}, headers=actor.headers
            ).json() == {"items": [], "next_cursor": None}

    def test_node_cursor_is_scoped_and_order_changes_on_reload(self, app, actors):
        actor, _, foreign = actors
        with TestClient(app) as client:
            case = create(client, actor, "/cases", case_payload(actor))
            path = f"/cases/{case['id']}/nodes"
            first = create(client, actor, path, {"kind": "group", "label": "첫 항목"})
            last = create(
                client, actor, path, {"kind": "group", "label": "끝 항목", "sort_order": 10}
            )
            for owner in (actor, foreign):
                other = create(client, owner, "/cases", case_payload(owner))
                wrong = create(
                    client,
                    owner,
                    f"/cases/{other['id']}/nodes",
                    {"kind": "group", "label": "다른 사건"},
                )
                assert (
                    client.get(
                        BASE + path, params={"cursor": wrong["id"]}, headers=actor.headers
                    ).status_code
                    == 404
                )
            changed = client.patch(
                BASE + path + "/" + first["id"],
                headers=vheaders(actor),
                json={"parent_id": last["id"]},
            )
            assert changed.status_code == 200
            page = client.get(BASE + path, params={"limit": 1}, headers=actor.headers).json()
            assert page["items"][0]["id"] == last["id"]
            assert page["next_cursor"] == last["id"]

    def test_deep_tree_single_topology_read_and_concurrent_cross_move(self, actors, db_engine):
        actor = actors[0]
        with Session(db_engine) as session:
            case = service.create_case(session, actor.principal, CaseInput(**case_payload(actor)))
            nodes = []
            parent = None
            for index in range(40):
                row = service.create_node(
                    session,
                    actor.principal,
                    case.id,
                    MedicalNodeInput(kind="group", label=f"합성 {index}", parent_id=parent),
                )
                nodes.append(row)
                parent = row.id
            statements = []

            def captured(conn, cursor, statement, parameters, context, executemany):
                if (
                    statement.startswith("SELECT")
                    and "medical_nodes.parent_id" in statement
                    and "medical_nodes.id," in statement
                ):
                    statements.append(statement)

            event.listen(db_engine, "before_cursor_execute", captured)
            try:
                with pytest.raises(DomainError) as error:
                    service.update_node(
                        session,
                        actor.principal,
                        case.id,
                        nodes[0].id,
                        MedicalNodePatch(parent_id=nodes[-1].id),
                        '"1"',
                    )
                assert error.value.code == "MEDICAL_NODE_CYCLE"
            finally:
                event.remove(db_engine, "before_cursor_execute", captured)
                session.rollback()
            assert (
                len(statements) <= 2
            )  # One node lookup and one whole topology read, not 40 ancestors.
            left = service.create_node(
                session, actor.principal, case.id, MedicalNodeInput(kind="group", label="합성 왼쪽")
            )
            right = service.create_node(
                session,
                actor.principal,
                case.id,
                MedicalNodeInput(kind="group", label="합성 오른쪽"),
            )
        barrier = Barrier(2)

        def move(pair):
            with Session(db_engine) as session:
                barrier.wait(timeout=10)
                try:
                    service.update_node(
                        session,
                        actor.principal,
                        case.id,
                        pair[0],
                        MedicalNodePatch(parent_id=pair[1]),
                        '"1"',
                    )
                    return "moved"
                except DomainError as error:
                    return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(move, [(left.id, right.id), (right.id, left.id)])) == [
                "MEDICAL_NODE_CYCLE",
                "moved",
            ]

    def test_database_same_case_household_fks_and_self_parent(self, actors, db_engine):
        actor, _, foreign = actors
        with Session(db_engine) as session:
            own = service.create_case(session, actor.principal, CaseInput(**case_payload(actor)))
            other = service.create_case(session, actor.principal, CaseInput(**case_payload(actor)))
            alien = service.create_case(
                session, foreign.principal, CaseInput(**case_payload(foreign))
            )
            node = service.create_node(
                session, actor.principal, own.id, MedicalNodeInput(kind="group", label="합성")
            )
            for case_id, parent_id in ((other.id, node.id), (alien.id, None)):
                session.add(
                    MedicalNode(
                        household_id=actor.household_id,
                        case_id=case_id,
                        parent_id=parent_id,
                        kind="group",
                        label="합성 무효",
                        start_on=None,
                        end_on=None,
                        sort_order=0,
                        created_by_member_id=actor.member_id,
                        updated_by_member_id=actor.member_id,
                    )
                )
                with pytest.raises(IntegrityError):
                    session.flush()
                session.rollback()
            with pytest.raises(IntegrityError):
                session.execute(
                    update(MedicalNode).where(MedicalNode.id == node.id).values(parent_id=node.id)
                )
            session.rollback()


@pytest.mark.database
class TestPolicyDisclosure:
    @pytest.mark.parametrize("target", ["session", "device"])
    def test_stale_principal_revocation_fails_before_decryption(
        self, actors, db_engine, key_file, monkeypatch, target
    ):
        actor = actors[0]
        with Session(db_engine) as session:
            policy = service.create_policy(
                session,
                actor.principal,
                PolicyCreate(**policy_payload(policy_number=SYNTHETIC_NUMBER)),
                key_file,
            )
            if target == "session":
                session.get(AuthSession, actor.principal.session_id).revoked_at = identity.utcnow()
            else:
                device = session.get(RegisteredDevice, actor.principal.device_id)
                device.status, device.revoked_at = "revoked", identity.utcnow()
            session.commit()

        def forbidden(*args):
            pytest.fail("A revoked identity must not decrypt")

        monkeypatch.setattr(service, "decrypt_number", forbidden)
        with Session(db_engine) as session:
            with pytest.raises(DomainError) as error:
                service.reveal_policy_number(session, actor.principal, policy.id, key_file)
            assert error.value.code == "UNAUTHENTICATED"

    @pytest.mark.parametrize(
        "blocked_on,change,expected",
        [
            ("device", "revoke", "UNAUTHENTICATED"),
            ("household", "recent", "REAUTHENTICATION_REQUIRED"),
            ("policy", "access", "UNAUTHENTICATED"),
        ],
    )
    def test_real_lock_wait_revalidates_live_identity(
        self, actors, db_engine, key_file, monkeypatch, blocked_on, change, expected
    ):
        actor = actors[0]
        with Session(db_engine) as session:
            policy = service.create_policy(
                session,
                actor.principal,
                PolicyCreate(**policy_payload(policy_number=SYNTHETIC_NUMBER)),
                key_file,
            )
            auth = session.get(AuthSession, actor.principal.session_id)
            recent, access = auth.authenticated_at, auth.access_expires_at

        def forbidden(*args):
            pytest.fail("Rejected requests must not decrypt")

        monkeypatch.setattr(service, "decrypt_number", forbidden)
        ready, proceed = Event(), Event()
        pids = []

        def reveal():
            with Session(db_engine) as session:
                cached_device = session.get(RegisteredDevice, actor.principal.device_id)
                pids.append(session.scalar(select(func.pg_backend_pid())))
                ready.set()
                assert proceed.wait(10)
                try:
                    service.reveal_policy_number(session, actor.principal, policy.id, key_file)
                    return "unexpected"
                except DomainError as error:
                    assert cached_device is not None
                    return error.code

        targets = {
            "device": (RegisteredDevice, actor.principal.device_id),
            "household": (Household, actor.household_id),
            "policy": (InsurancePolicy, policy.id),
        }
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(reveal)
            try:
                assert ready.wait(10)
                with Session(db_engine) as blocker:
                    model, identifier = targets[blocked_on]
                    row = blocker.scalar(
                        select(model).where(model.id == identifier).with_for_update()
                    )
                    blocker_pid = blocker.scalar(select(func.pg_backend_pid()))
                    proceed.set()
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        blockers = blocker.scalar(select(func.pg_blocking_pids(pids[0])))
                        if blocker_pid in blockers or future.done():
                            break
                        time.sleep(0.01)
                    assert blocker_pid in blockers
                    if change == "revoke":
                        row.revoked_at, row.status = identity.utcnow(), "revoked"
                    else:
                        after = (
                            recent + timedelta(minutes=5) if change == "recent" else access
                        ) + timedelta(seconds=1)
                        monkeypatch.setattr(identity, "utcnow", lambda: after)
                    blocker.commit()
                assert future.result(timeout=10) == expected
            finally:
                proceed.set()
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "reveal")
                )
                == 0
            )

    @pytest.mark.parametrize("phase", ["decryption", "audit_flush"])
    @pytest.mark.parametrize("expiry", ["recent", "access"])
    def test_expiry_after_work_never_returns_plaintext_or_commits_audit(
        self, app, actors, db_engine, monkeypatch, caplog, phase, expiry
    ):
        actor = actors[0]
        with TestClient(app) as client:
            policy = create(
                client, actor, "/policies", policy_payload(policy_number=SYNTHETIC_NUMBER)
            )
            with Session(db_engine) as session:
                auth = session.get(AuthSession, actor.principal.session_id)
                after = (
                    auth.authenticated_at + timedelta(minutes=5)
                    if expiry == "recent"
                    else auth.access_expires_at
                ) + timedelta(seconds=1)
            original = service.decrypt_number

            def advance(*args):
                result = original(*args)
                monkeypatch.setattr(identity, "utcnow", lambda: after)
                return result

            def flushed(session, context):
                if any(
                    isinstance(row, AuditEvent) and row.action == "reveal" for row in session.new
                ):
                    monkeypatch.setattr(identity, "utcnow", lambda: after)

            if phase == "decryption":
                monkeypatch.setattr(service, "decrypt_number", advance)
            else:
                event.listen(Session, "after_flush", flushed)
            try:
                response = client.post(
                    f"{BASE}/policies/{policy['id']}/reveal", headers=actor.headers
                )
            finally:
                if phase == "audit_flush":
                    event.remove(Session, "after_flush", flushed)
            assert response.status_code == (403 if expiry == "recent" else 401)
            assert SYNTHETIC_NUMBER not in response.text and SYNTHETIC_NUMBER not in caplog.text
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "reveal")
                )
                == 0
            )

    def test_audit_failure_no_plaintext_response(self, app, actors, db_engine, monkeypatch, caplog):
        actor = actors[0]
        with TestClient(app, raise_server_exceptions=False) as client:
            policy = create(
                client, actor, "/policies", policy_payload(policy_number=SYNTHETIC_NUMBER)
            )

            def failed(*args, **kwargs):
                raise RuntimeError("Synthetic audit failure")

            monkeypatch.setattr(service, "record_event", failed)
            response = client.post(f"{BASE}/policies/{policy['id']}/reveal", headers=actor.headers)
            assert response.status_code == 500
            assert SYNTHETIC_NUMBER not in response.text and SYNTHETIC_NUMBER not in caplog.text
        with Session(db_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "reveal")
                )
                == 0
            )
