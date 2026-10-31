"""Synthetic atomic bootstrap replay and user-owned edit/delete behavior."""

import hashlib
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_accounts import make_actor

from sallimbook.cashflow.expense_import_schemas import ImportRequest, ImportRow
from sallimbook.cashflow.expense_import_service import apply_import, manifest_digest, preview_import
from sallimbook.cashflow.expense_plan_schemas import PlanChange, PlanCreate
from sallimbook.cashflow.expense_plan_service import change_plan
from sallimbook.cashflow.recurring_models import RecurringRule
from sallimbook.cashflow.recurring_service import delete_rule
from sallimbook.core.errors import DomainError

pytestmark = pytest.mark.database


def request(actor, **kw):
    rows = [
        ImportRow(
            source_key=f"R{i}",
            plan=PlanCreate(
                title=f"합성 등록 {i}",
                category="합성",
                amount_mode="fixed",
                economic_type="expense",
                frequency="monthly",
                expected_amount_krw="12000",
            ),
        )
        for i in range(2)
    ]
    return ImportRequest(
        household_id=actor.household_id,
        actor_member_id=actor.member_id,
        source_id="synthetic-bootstrap",
        rows=rows,
        manifest_hash=manifest_digest(rows),
        expected_rules_fingerprint=hashlib.sha256(b"[]").hexdigest(),
        **kw,
    )


def count(engine):
    with Session(engine) as s:
        return s.scalar(select(func.count()).select_from(RecurringRule))


def test_preview_atomic_replay_preserves_edits_deleted_rows_and_baseline(db_engine, monkeypatch):
    from sallimbook.cashflow import recurring_service

    monkeypatch.setattr(recurring_service, "today", lambda: date(2026, 2, 1))
    actor = make_actor(db_engine)
    req = request(actor)
    with Session(db_engine) as s:
        assert preview_import(s, actor.principal, req).created_count == 0
    assert count(db_engine) == 0
    with Session(db_engine) as s:
        first = apply_import(s, actor.principal, req)
    assert first.created_count == 2 and count(db_engine) == 2
    with Session(db_engine) as s:
        change_plan(
            s,
            actor.principal,
            first.rows[0].created_rule_id,
            PlanChange(**(req.rows[0].plan.model_dump() | {"expected_amount_krw": "25000"})),
            '"1"',
            str(uuid4()),
        )
    with Session(db_engine) as s:
        delete_rule(
            s, actor.principal, first.rows[1].created_rule_id, '"1"', str(uuid4()), plan=True
        )
    mate = make_actor(db_engine, actor.household_id)
    monkeypatch.setattr(recurring_service, "today", lambda: date(2026, 2, 2))
    replay_request = req.model_copy(update={"actor_member_id": mate.member_id})
    with Session(db_engine) as s:
        again = apply_import(s, mate.principal, replay_request)
    assert again.created_count == 0 and again.baseline_date == first.baseline_date
    assert [r.created_rule_id for r in again.rows] == [r.created_rule_id for r in first.rows]
    assert again.rows[1].state == "user_deleted" and again.rows[1].rule_id is None
    assert count(db_engine) == 1
    from sallimbook.cashflow.expense_plan_service import get_plan

    with Session(db_engine) as s:
        assert (
            get_plan(s, actor.principal, first.rows[0].created_rule_id)
            .versions[0]
            .expected_amount_krw
            == "25000"
        )


def test_invalid_late_row_rolls_back_whole_batch_and_changed_hash_conflicts(db_engine):
    actor = make_actor(db_engine)
    req = request(actor)
    bad = req.rows[1].model_copy(
        update={"plan": req.rows[1].plan.model_copy(update={"card_id": uuid4()})}
    )
    rows = [req.rows[0], bad]
    invalid = req.model_copy(update={"rows": rows, "manifest_hash": manifest_digest(rows)})
    with Session(db_engine) as s, pytest.raises(DomainError):
        apply_import(s, actor.principal, invalid)
    assert count(db_engine) == 0
    with Session(db_engine) as s:
        apply_import(s, actor.principal, req)
    changed = req.rows[1].model_copy(
        update={"plan": req.rows[1].plan.model_copy(update={"title": "다른 합성"})}
    )
    rows = [req.rows[0], changed]
    with Session(db_engine) as s, pytest.raises(DomainError) as failure:
        apply_import(
            s,
            actor.principal,
            req.model_copy(update={"rows": rows, "manifest_hash": manifest_digest(rows)}),
        )
    assert failure.value.status == 409
    assert count(db_engine) == 2


def test_import_rejects_other_household_or_actor(db_engine):
    actor = make_actor(db_engine)
    other = make_actor(db_engine)
    req = request(actor)
    with Session(db_engine) as s, pytest.raises(DomainError):
        apply_import(s, other.principal, req)
    with Session(db_engine) as s, pytest.raises(DomainError):
        apply_import(
            s, actor.principal, req.model_copy(update={"actor_member_id": other.member_id})
        )
    assert count(db_engine) == 0


def test_concurrent_imports_share_one_batch(db_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    actor = make_actor(db_engine)
    req = request(actor)
    barrier = Barrier(2)

    def apply():
        with Session(db_engine) as s:
            barrier.wait(timeout=10)
            return apply_import(s, actor.principal, req)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(apply), pool.submit(apply)]
        results = [f.result(timeout=30) for f in futures]
    assert sorted(r.created_count for r in results) == [0, 2]
    assert [r.created_rule_id for r in results[0].rows] == [
        r.created_rule_id for r in results[1].rows
    ]
    assert count(db_engine) == 2


def test_preview_works_in_database_read_only_transaction(db_engine):
    from sqlalchemy import text

    actor = make_actor(db_engine)
    req = request(actor)
    with Session(db_engine) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        result = preview_import(session, actor.principal, req)
        assert result.status == "preview" and result.row_count == 2
    assert count(db_engine) == 0


def test_initial_import_rejects_user_creation_after_preview(db_engine):
    from sallimbook.cashflow.expense_plan_service import create_plan

    actor = make_actor(db_engine)
    req = request(actor)
    with Session(db_engine) as s:
        preview_import(s, actor.principal, req)
    with Session(db_engine) as s:
        create_plan(s, actor.principal, req.rows[0].plan, str(uuid4()))
    with Session(db_engine) as s, pytest.raises(DomainError) as failure:
        apply_import(s, actor.principal, req)
    assert failure.value.code == "IMPORT_BASELINE_CHANGED"
    assert count(db_engine) == 1


def test_first_apply_requires_explicit_preview_baseline(db_engine):
    actor = make_actor(db_engine)
    req = request(actor).model_copy(update={"expected_rules_fingerprint": None})
    with Session(db_engine) as s:
        preview = preview_import(s, actor.principal, req)
    assert preview.rules_fingerprint == hashlib.sha256(b"[]").hexdigest()
    with Session(db_engine) as s, pytest.raises(DomainError) as failure:
        apply_import(s, actor.principal, req)
    assert failure.value.code == "IMPORT_BASELINE_REQUIRED"
    assert count(db_engine) == 0
    with Session(db_engine) as s:
        result = apply_import(
            s,
            actor.principal,
            req.model_copy(update={"expected_rules_fingerprint": preview.rules_fingerprint}),
        )
    assert result.created_count == 2


def test_first_import_rejects_changed_existing_rule_without_overwrite(db_engine):
    from sallimbook.cashflow.expense_plan_service import create_plan

    actor = make_actor(db_engine)
    req = request(actor)
    with Session(db_engine) as s:
        existing = create_plan(s, actor.principal, req.rows[0].plan, str(uuid4()))
        preview = preview_import(s, actor.principal, req)
    req = req.model_copy(update={"expected_rules_fingerprint": preview.rules_fingerprint})
    with Session(db_engine) as s:
        change_plan(
            s,
            actor.principal,
            existing.id,
            PlanChange(**(req.rows[0].plan.model_dump() | {"expected_amount_krw": "25000"})),
            '"1"',
            str(uuid4()),
        )
    with Session(db_engine) as s, pytest.raises(DomainError) as failure:
        apply_import(s, actor.principal, req)
    assert failure.value.code == "IMPORT_BASELINE_CHANGED"
    assert count(db_engine) == 1
