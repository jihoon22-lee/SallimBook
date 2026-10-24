"""Actual PostgreSQL household snapshots rendered as offline readable reports."""

import io
import json
from pathlib import Path
from uuid import UUID
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_accounts import create_account
from test_asset_months import add_asset, confirm, draft, observe, read_month
from test_consumable_orders import command as order_command
from test_consumable_orders import create as create_order
from test_consumable_orders import get as get_order
from test_consumable_orders import submit as submit_order
from test_documents import document_app as document_app
from test_exports import actors as actors
from test_exports import export
from test_exports import export_app as export_app
from test_homecare_database import TODAY, post_consumable, stock_at
from test_household_people import family
from test_income import headers, income_payload
from test_insurance_core import case_payload, policy_payload
from test_insurance_events import (
    actual,
    allocation,
    money,
    new_case,
    new_expense,
    new_node,
    new_payout,
)
from test_recurring import generate, post_rule, settle

from sallimbook.cashflow.schemas import CashInput
from sallimbook.cashflow.service import prepare_cash_record
from sallimbook.exports import router as export_routes
from sallimbook.exports.annual import annual_summary
from sallimbook.exports.archive import ArchiveBuilder, Budget, Limits
from sallimbook.exports.readable import DOMAINS
from sallimbook.identity import service as identity
from sallimbook.identity.auth_models import AuthSession
from sallimbook.identity.people_router import router as people_router

pytestmark = pytest.mark.database


def files(response):
    assert response.status_code == 200, response.text[:1000]
    with ZipFile(io.BytesIO(response.content)) as archive:
        return {name: archive.read(name).decode() for name in archive.namelist()}


def test_all_domains_empty_snapshot_and_html_only_have_explicit_scope(export_app, actors):
    with TestClient(export_app) as client:
        data = files(
            export(
                client,
                actors[0],
                formats=[],
                readable={"domains": list(DOMAINS), "annual_year": 9999},
            )
        )
        assert set(data) == {"readable/index.html", "readable/annual.html", "manifest.json"}
        assert "9999-01-01" in data["readable/annual.html"]
        assert "0원" in data["readable/annual.html"]
        assert "default-src &#x27;none&#x27;" not in data["readable/index.html"]
        manifest = json.loads(data["manifest.json"])
        assert manifest["readable"]["domains"] == list(DOMAINS)
        assert all(entry["sha256"] for entry in manifest["entries"])


def test_names_relationships_seoul_null_and_zero_are_readable_and_raw_unchanged(export_app, actors):
    actor, _, foreign = actors
    with TestClient(export_app) as client:
        create_account(client, actor, institution_name="<script>합성 기관</script>")
        create_account(client, foreign, institution_name="FOREIGN-NAME-CANARY")
        case = new_case(client, actor)
        node = new_node(client, actor, case, label="합성 진료 이름")
        new_expense(
            client,
            actor,
            case,
            node,
            "9007199254740993",
            gross_medical_krw="9007199254740993",
            public_coverage_krw="0",
        )
        original = files(export(client, actor, formats=["json", "csv"]))
        result = files(
            export(client, actor, formats=["json", "csv"], readable={"domains": list(DOMAINS)})
        )
        for path, value in original.items():
            if path not in {"manifest.json", "json/audit_events.json", "csv/audit_events.csv"}:
                assert result[path] == value
        html = result["readable/index.html"]
        assert "&lt;script&gt;합성 기관&lt;/script&gt;" in html
        assert "<script>" not in html and "FOREIGN-NAME-CANARY" not in html
        assert "합성 진료 이름" in html and "로그인 구성원" in html
        assert "9,007,199,254,740,993원" in html and ">0원<" in html and ">미입력<" in html
        assert "+09:00" in html
        assert str(actor.member_id) not in html and case["id"] not in html
        assert "number_ciphertext" not in html


def test_scope_is_inclusive_month_precision_overlaps_and_raw_stays_full(export_app, actors):
    actor = actors[0]
    with TestClient(export_app) as client:
        for fields in [
            {"note": "JAN-MONTH", "amount_krw": "11"},
            {
                "note": "JAN-DAY-BEFORE",
                "amount_krw": "12",
                "occurred_on": "2026-01-01",
                "date_precision": "day",
            },
            {
                "note": "JAN-DAY-INSIDE",
                "amount_krw": "13",
                "occurred_on": "2026-01-31",
                "date_precision": "day",
            },
            {"note": "FEB-MONTH-OUTSIDE", "amount_krw": "14", "period_month": "2026-02"},
        ]:
            response = client.post(
                "/api/v1/income",
                headers=headers(actor),
                json=income_payload(actor, duplicate_acknowledged=True, **fields),
            )
            assert response.status_code == 201, response.text
        data = files(
            export(
                client,
                actor,
                formats=["json"],
                readable={
                    "domains": ["income"],
                    "from_date": "2026-01-31",
                    "through_date": "2026-01-31",
                },
            )
        )
        html = data["readable/index.html"]
        assert "JAN-MONTH" in html and "JAN-DAY-INSIDE" in html
        assert "JAN-DAY-BEFORE" not in html and "FEB-MONTH-OUTSIDE" not in html
        assert "자산 기본정보" not in html
        assert len(json.loads(data["json/cash_records.json"])) == 4


def test_annual_family_cash_year_multiple_claims_returns_void_and_fixed_classification(
    export_app, actors, db_engine
):
    actor, partner, foreign = actors
    export_app.include_router(people_router)
    with TestClient(export_app) as client:
        child = family(client, actor, "합성 자녀 <한결>")
        response = client.post(
            "/api/v1/insurance/cases",
            headers={**actor.headers, "X-SallimBook-People": "1"},
            json=case_payload(actor) | {"patient_member_id": child},
        )
        assert response.status_code == 201, response.text
        case = response.json()
        node = new_node(client, actor, case)
        old = new_expense(client, actor, case, node, "1000", occurred_on="2025-12-31")
        current = new_expense(client, actor, case, node, "600")
        money(
            client,
            actor,
            f"/medical-expenses/{old['id']}/refunds",
            actual("100", reason="합성 이전연도 환불"),
            version=1,
        )
        invalid = new_expense(client, actor, case, node, "900")
        money(
            client,
            actor,
            f"/medical-expenses/{invalid['id']}/void",
            {"reason": "합성 오등록"},
            version=1,
            status=200,
        )
        other_case = new_case(client, partner)
        other_node = new_node(client, partner, other_case)
        new_expense(client, partner, other_case, other_node, "300")
        new_payout(
            client,
            actor,
            [allocation(case["id"], "200"), allocation(other_case["id"], "100")],
        )
        old_payout = new_payout(
            client, actor, [allocation(case["id"], "150")], occurred_on="2025-12-31"
        )
        money(
            client,
            actor,
            f"/payouts/{old_payout['id']}/returns",
            actual(
                "50",
                original_allocation_id=old_payout["allocations"][0]["id"],
                reason="합성 이전연도 반환",
            ),
            version=1,
        )
        for _ in range(2):
            policy = client.post(
                "/api/v1/insurance/policies", headers=actor.headers, json=policy_payload()
            )
            assert policy.status_code == 201, policy.text
            claim = client.post(
                "/api/v1/insurance/claims",
                headers=headers(actor),
                json={
                    "case_id": case["id"],
                    "policy_id": policy.json()["id"],
                    "expense_ids": [current["id"]],
                    "requested_krw": "999999",
                    "decided_krw": "999999",
                },
            )
            assert claim.status_code == 201, claim.text
        for category, economic, amount in [
            ("보험료", "expense", "70"),
            ("연금", "asset_transfer", "80"),
            ("기타 이동", "asset_transfer", "90"),
            ("기타", "expense", "20"),
        ]:
            rule = post_rule(client, actor, category=category, economic_type=economic)
            generate(client, actor, rule["id"])
            obligations = client.get(
                "/api/v1/obligations?month=2026-01", headers=actor.headers
            ).json()["items"]
            obligation = next(row for row in obligations if row["rule_id"] == rule["id"])
            settle(client, actor, obligation, amount=amount)
        foreign_case = new_case(client, foreign)
        new_expense(
            client, foreign, foreign_case, new_node(client, foreign, foreign_case), "777777"
        )
        with Session(db_engine) as session:
            prepare_cash_record(
                session,
                actor.principal,
                CashInput(amount_krw="50", period_month="2026-01", date_precision="month"),
                kind="insurance_receipt",
            )
            session.commit()
            summary = annual_summary(session, actor.household_id, 2026, Budget())
            before = annual_summary(session, actor.household_id, 2025, Budget())
        assert summary["people"][UUID(child)] == {
            "medical_paid": 600,
            "medical_refunded": 100,
            "insurance_received": 200,
            "insurance_returned": 50,
            "net_medical": 500,
            "net_insurance": 150,
            "net_burden": 350,
        }
        assert summary["people"][partner.member_id]["net_burden"] == 200
        assert summary["people"][None]["insurance_received"] == 50
        assert summary["total"]["net_burden"] == 500
        assert summary["fixed"] == {
            "premium": 70,
            "pension": 80,
            "other_transfer": 90,
            "other_consumption": 20,
            "principal": 0,
        }
        assert before["people"][UUID(child)]["net_burden"] == 850
        archived = client.patch(
            f"/api/v1/household/people/{child}",
            headers=headers(actor, version=1),
            json={"active": False},
        )
        assert archived.status_code == 200, archived.text
        data = files(
            export(
                client,
                actor,
                formats=[],
                readable={
                    "domains": ["insurance"],
                    "annual_year": 2026,
                    "from_date": "2026-02-01",
                    "through_date": "2026-02-28",
                },
            )
        )
        html = data["readable/annual.html"]
        assert "합성 자녀 &lt;한결&gt; (자녀 · 종료)" in html and "350원" in html
        assert "2026-01-01 ~ 2026-12-31" in html
        assert "가족 미지정 보험금" in html and "777,777" not in html and "999,999" not in html
        assert "2026-02-01 ~ 2026-02-28" in data["readable/index.html"]


def test_only_prior_year_refunds_make_negative_annual_totals(export_app, actors, db_engine):
    actor = actors[0]
    fixture = json.loads(
        (Path(__file__).resolve().parents[3] / "packages/test-fixtures/catalog.json").read_text()
    )["edge_cases"]["annual_family_cash_year"]
    with TestClient(export_app) as client:
        case = new_case(client, actor)
        expense = new_expense(
            client, actor, case, new_node(client, actor, case), "100", occurred_on="2024-12-31"
        )
        payout = new_payout(
            client, actor, [allocation(case["id"], "100")], occurred_on="2024-12-31"
        )
        money(
            client,
            actor,
            f"/medical-expenses/{expense['id']}/refunds",
            actual("70", occurred_on="2025-01-01", reason="합성 연도경계 환불"),
            version=1,
        )
        money(
            client,
            actor,
            f"/payouts/{payout['id']}/returns",
            actual(
                "80",
                occurred_on="2025-01-01",
                original_allocation_id=payout["allocations"][0]["id"],
                reason="합성 연도경계 반환",
            ),
            version=1,
        )
        with Session(db_engine) as session:
            summary = annual_summary(session, actor.household_id, 2025, Budget())
        assert {
            key: str(summary["total"][key.removesuffix("_krw")])
            for key in fixture["prior_year_refund_expected"]
        } == fixture["prior_year_refund_expected"]
        html = files(
            export(
                client, actor, formats=[], readable={"domains": ["insurance"], "annual_year": 2025}
            )
        )["readable/annual.html"]
        assert ">-70원<" in html and ">-80원<" in html and ">10원<" in html


def test_readable_only_limits_and_late_revocation_never_issue_partial_files(
    export_app, actors, db_engine, monkeypatch
):
    payload = {"formats": [], "readable": {"domains": ["insurance"], "annual_year": 2026}}
    actor = actors[0]
    with TestClient(export_app) as client:
        assert client.post("/api/v1/exports", json=payload).status_code == 401
        monkeypatch.setattr(
            export_routes, "Budget", lambda: Budget(limits=Limits(metadata_bytes=100))
        )
        response = export(client, actor, **payload)
        assert response.status_code == 413 and not response.content.startswith(b"PK")
        monkeypatch.setattr(export_routes, "Budget", Budget)
        original = ArchiveBuilder.finish

        def revoked(builder):
            artifact = original(builder)
            with Session(db_engine) as session:
                session.get(AuthSession, actor.principal.session_id).revoked_at = identity.utcnow()
                session.commit()
            return artifact

        monkeypatch.setattr(ArchiveBuilder, "finish", revoked)
        response = export(client, actor, **payload)
        assert response.status_code == 401 and not response.content.startswith(b"PK")


def test_asset_period_keeps_only_current_revision_and_its_recorded_name(export_app, actors):
    actor = actors[0]
    with TestClient(export_app) as client:
        asset = add_asset(client, actor, name="합성 월 원본 이름")
        draft(client, actor, "2026-01", copy=False)
        observe(client, actor, "2026-01", asset["id"], "0", "2026-01-31")
        confirmed = confirm(client, actor, "2026-01")
        assert confirmed.status_code == 200, confirmed.text
        current = read_month(client, actor, "2026-01")
        reopened = client.post(
            "/api/v1/asset-months/2026-01/reopen",
            headers=headers(actor, version=current["version"]),
            json={"revision_id": current["revision_id"], "reason": "합성 월 정정"},
        )
        assert reopened.status_code == 201, reopened.text
        observe(
            client, actor, "2026-01", asset["id"], "99", "2026-01-31", change_reason="합성 값 정정"
        )
        draft(client, actor, "2026-02", copy=False)
        data = files(
            export(
                client,
                actor,
                formats=["json"],
                readable={
                    "domains": ["assets"],
                    "from_date": "2026-01-31",
                    "through_date": "2026-01-31",
                },
            )
        )
        html = data["readable/index.html"]
        table = html.split("<h2>월별 자산값 (현재 리비전)</h2>", 1)[1]
        assert table.count("<tr>") == 2
        assert ">99원<" in table and ">0원<" not in table
        assert "합성 월 원본 이름" in table and "2026-01" in table
        assert "2026-02" not in table and "합계포함" in table
        assert len(json.loads(data["json/asset_values.json"])) == 3


def test_received_order_and_stock_history_expose_reversed_receipt(export_app, actors):
    actor = actors[0]
    with TestClient(export_app) as client:
        stock = post_consumable(client, actor)
        order = create_order(client, actor, stock)
        ordered = submit_order(client, actor, order)
        received = order_command(
            client,
            actor,
            ordered,
            "receive",
            {"received_on": TODAY, "stock_version": stock["version"]},
        )
        assert received.status_code == 200, received.text
        current = get_order(client, actor, order)
        cancelled = client.post(
            f"/api/v1/consumables/{stock['id']}/stock-movements/{current['stock_movement_id']}/cancel",
            headers=headers(actor, version=stock_at(client, actor, stock["id"])["version"]),
            json={"occurred_on": TODAY, "reason": "합성 입고 취소"},
        )
        assert cancelled.status_code == 200, cancelled.text
        html = files(export(client, actor, formats=[], readable={"domains": ["homecare"]}))[
            "readable/index.html"
        ]
        orders = html.split("<h2>구매계획·주문·입고 현황</h2>", 1)[1]
        assert "원입고·교체취소여부" in orders and ">예<" in orders
        assert "입고완료" in orders and "합성 공용 필터" in orders
        assert "합성 입고 취소" in html
