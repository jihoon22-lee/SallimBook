"""Home attention uses the same actual settlements and completion state as each original."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session
from test_income import headers
from test_recurring import actors as actors
from test_recurring import generate, post_rule, settle
from test_recurring import recurring_app as recurring_app

from sallimbook.cashflow import recurring_service as service
from sallimbook.cashflow.recurring_models import ScheduledObligation

BASE = "/api/v1/obligations/overdue"


def single(client, actor, title, day="2026-01-31", expected="100"):
    rule = post_rule(
        client,
        actor,
        title=title,
        frequency="annual",
        anchor_date=day,
        effective_from="2025-12-01",
        amount_mode="variable" if expected is None else "fixed",
        expected_amount_krw=expected,
    )
    created = generate(client, actor, rule["id"], start="2025-12-01", end="2026-02-28")
    assert len(created["items"]) == 1
    response = client.get(f"/api/v1/obligations/{created['items'][0]['id']}", headers=actor.headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.database
def test_overdue_uses_all_prior_months_and_excludes_every_resolved_state(
    recurring_app, actors, db_engine
):
    actor, spouse, foreign = actors
    with TestClient(recurring_app) as client:
        expected = []
        for title, day, amount, actual in [
            ("합성 전전월 미납", "2025-12-31", "100", None),
            ("합성 일부 납부", "2026-01-31", "100", "40"),
            ("합성 금액 미정 미납", "2026-01-31", None, None),
            ("합성 0원 확인", "2026-01-31", "0", None),
            ("합성 금액 미정 납부", "2026-01-31", None, "40"),
            ("합성 납부 완료", "2026-01-31", "100", "100"),
            ("합성 초과 납부", "2026-01-31", "100", "110"),
            ("합성 오늘 예정", "2026-02-01", "100", None),
            ("합성 미래 예정", "2026-02-02", "100", None),
        ]:
            row = single(client, actor, title, day, amount)
            if actual:
                settle(client, actor, row, amount=actual)
            if title in (
                "합성 전전월 미납",
                "합성 일부 납부",
                "합성 금액 미정 미납",
                "합성 0원 확인",
            ):
                expected.append(row["id"])
        for operation in ("skip", "complete"):
            row = single(client, actor, f"합성 {operation}")
            if operation == "complete":
                settle(client, actor, row, amount="40")
                row = client.get(f"/api/v1/obligations/{row['id']}", headers=actor.headers).json()
            done = client.post(
                f"/api/v1/obligations/{row['id']}/{operation}",
                headers=headers(actor, version=row["version"]),
                json={"reason": "합성 처리"},
            )
            assert done.status_code == 200, done.text
        replaced = single(client, actor, "합성 대체 회차")
        with Session(db_engine) as session:
            session.execute(
                update(ScheduledObligation)
                .where(ScheduledObligation.id == UUID(replaced["id"]))
                .values(schedule_state="superseded")
            )
            session.commit()
        other = single(client, foreign, "합성 다른 가계")
        page = client.get(BASE, headers=spouse.headers, params={"limit": 2})
        assert page.status_code == 200, page.text
        assert page.headers["cache-control"] == "no-store"
        result = page.json()
        assert result["as_of"] == "2026-02-01"
        seen = result["items"]
        while result["next_cursor"]:
            result = client.get(
                BASE, headers=actor.headers, params={"limit": 2, "cursor": result["next_cursor"]}
            ).json()
            seen.extend(result["items"])
        assert len(seen) == len(expected) and {row["id"] for row in seen} == set(expected)
        assert seen[0]["title"] == "합성 전전월 미납"
        assert all(row["status"] in ("unpaid", "partial") for row in seen)
        assert (
            next(row for row in seen if row["title"] == "합성 일부 납부")["actual_amount_krw"]
            == "40"
        )
        assert client.get(BASE).status_code == 401
        assert (
            client.get(BASE, headers=actor.headers, params={"cursor": other["id"]}).status_code
            == 404
        )
        assert client.get(BASE, headers=actor.headers, params={"limit": 201}).status_code == 422
        assert client.get(BASE, headers=foreign.headers).json()["items"][0]["id"] == other["id"]


@pytest.mark.database
def test_original_payment_and_reopen_control_the_attention_without_separate_done_flag(
    recurring_app, actors
):
    actor = actors[0]
    with TestClient(recurring_app) as client:
        row = single(client, actor, "합성 원본 처리")
        assert len(client.get(BASE, headers=actor.headers).json()["items"]) == 1
        settle(client, actor, row, amount="100")
        assert client.get(BASE, headers=actor.headers).json()["items"] == []
        unknown = single(client, actor, "합성 완료 확인")
        settle(client, actor, unknown, amount="40")
        for action, count in (("complete", 0), ("reopen", 1)):
            latest = client.get(
                f"/api/v1/obligations/{unknown['id']}", headers=actor.headers
            ).json()
            done = client.post(
                f"/api/v1/obligations/{unknown['id']}/{action}",
                headers=headers(actor, version=latest["version"]),
                json={"reason": "합성 원본 상태 변경"},
            )
            assert done.status_code == 200, done.text
            assert len(client.get(BASE, headers=actor.headers).json()["items"]) == count


@pytest.mark.database
def test_seoul_midnight_changes_due_status_and_page_as_of(recurring_app, actors, monkeypatch):
    actor = actors[0]
    with TestClient(recurring_app) as client:
        row = single(client, actor, "합성 서울 날짜", "2026-02-01")
        monkeypatch.setattr(service, "utcnow", lambda: datetime(2026, 2, 1, 14, 59, tzinfo=UTC))
        before = client.get(BASE, headers=actor.headers).json()
        assert before == {"items": [], "next_cursor": None, "as_of": "2026-02-01"}
        monkeypatch.setattr(service, "utcnow", lambda: datetime(2026, 2, 1, 15, 0, tzinfo=UTC))
        after = client.get(BASE, headers=actor.headers).json()
        assert after["as_of"] == "2026-02-02" and after["items"][0]["id"] == row["id"]
