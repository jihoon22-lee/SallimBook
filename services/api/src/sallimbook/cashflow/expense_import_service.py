"""Household-serialized, all-or-nothing, replay-safe initial plan registration."""

import hashlib
import json

from sqlalchemy import select

from sallimbook.cashflow import recurring_service as recurring
from sallimbook.cashflow import service as cash
from sallimbook.cashflow.expense_import_models import ExpenseImportBatch, ExpenseImportRow
from sallimbook.cashflow.expense_import_schemas import ImportResult, ImportResultRow
from sallimbook.cashflow.expense_plan_service import _validate, create_plan_in_transaction
from sallimbook.cashflow.recurring_models import RecurringRule
from sallimbook.core.authorization import scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.identity.auth_models import HouseholdMember


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def manifest_digest(rows):
    return digest([r.model_dump(mode="json") for r in sorted(rows, key=lambda r: r.source_key)])


def rules_fingerprint(session, principal):
    rows = session.execute(
        select(RecurringRule.id, RecurringRule.version)
        .where(RecurringRule.household_id == principal.household_id)
        .order_by(RecurringRule.id)
    )
    return digest([[str(identity), version] for identity, version in rows])


def _authorize(session, principal, payload):
    if (
        payload.household_id != principal.household_id
        or payload.actor_member_id != principal.member_id
    ):
        raise DomainError("NOT_FOUND", "등록 대상을 찾을 수 없습니다.", 404)
    member = scoped_entity(session, HouseholdMember, principal.member_id, principal)
    if member.user_id != principal.user_id or member.status != "active":
        raise DomainError("FORBIDDEN", "등록 권한이 없습니다.", 403)
    if manifest_digest(payload.rows) != payload.manifest_hash:
        raise DomainError("IMPORT_HASH_MISMATCH", "입력 파일 식별값이 일치하지 않습니다.", 409)


def _existing(session, principal, payload):
    batch = session.scalar(
        select(ExpenseImportBatch).where(
            ExpenseImportBatch.household_id == principal.household_id,
            ExpenseImportBatch.source_id == payload.source_id,
        )
    )
    if batch is not None and batch.manifest_hash != payload.manifest_hash:
        raise DomainError(
            "IMPORT_SOURCE_CONFLICT", "같은 출처에 다른 자료가 등록되어 있습니다.", 409
        )
    return batch


def _result(session, principal, batch, created=0):
    rows = session.scalars(
        select(ExpenseImportRow)
        .where(
            ExpenseImportRow.household_id == principal.household_id,
            ExpenseImportRow.source_id == batch.source_id,
        )
        .order_by(ExpenseImportRow.source_key)
    )
    return ImportResult(
        status="created" if created else "replayed",
        baseline_date=batch.baseline_date,
        created_count=created,
        row_count=batch.row_count,
        rows=[
            ImportResultRow(
                source_key=r.source_key,
                created_rule_id=r.created_rule_id,
                rule_id=r.rule_id,
                state=r.state,
            )
            for r in rows
        ],
    )


def preview_import(session, principal, payload):
    _authorize(session, principal, payload)
    existing = _existing(session, principal, payload)
    if existing is not None:
        return _result(session, principal, existing)
    for row in payload.rows:
        _validate(session, principal, row.plan, for_update=False)
    return ImportResult(
        status="preview",
        rules_fingerprint=rules_fingerprint(session, principal),
        baseline_date=recurring.today(),
        created_count=0,
        row_count=len(payload.rows),
        rows=[],
    )


def apply_import(session, principal, payload):
    try:
        cash.lock_cash_household(session, principal)
        _authorize(session, principal, payload)
        existing = _existing(session, principal, payload)
        if existing is not None:
            result = _result(session, principal, existing)
        else:
            if payload.expected_rules_fingerprint is None:
                raise DomainError(
                    "IMPORT_BASELINE_REQUIRED", "등록 전 기준 상태가 필요합니다.", 409
                )
            if rules_fingerprint(session, principal) != payload.expected_rules_fingerprint:
                raise DomainError(
                    "IMPORT_BASELINE_CHANGED", "기존 계획이 변경되어 일괄 등록하지 않았습니다.", 409
                )
            baseline = recurring.today()
            batch = ExpenseImportBatch(
                household_id=principal.household_id,
                actor_member_id=principal.member_id,
                source_id=payload.source_id,
                manifest_hash=payload.manifest_hash,
                baseline_date=baseline,
                row_count=len(payload.rows),
            )
            session.add(batch)
            session.flush()
            for item in sorted(payload.rows, key=lambda r: r.source_key):
                rule = create_plan_in_transaction(session, principal, item.plan, baseline=baseline)
                session.add(
                    ExpenseImportRow(
                        household_id=principal.household_id,
                        source_id=payload.source_id,
                        source_key=item.source_key,
                        payload_hash=digest(item.plan.model_dump(mode="json")),
                        created_rule_id=rule.id,
                        rule_id=rule.id,
                        state="linked",
                    )
                )
            session.flush()
            result = _result(session, principal, batch, len(payload.rows))
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def detach_deleted_rule(session, principal, rule_id):
    row = session.scalar(
        select(ExpenseImportRow)
        .where(
            ExpenseImportRow.household_id == principal.household_id,
            ExpenseImportRow.rule_id == rule_id,
        )
        .with_for_update()
    )
    if row is not None:
        row.rule_id = None
        row.state = "user_deleted"
        session.flush()
