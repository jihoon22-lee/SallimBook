"""Direct database checks for immutable actual facts and deferred source breakdowns."""

from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_accounts import make_actor

from sallimbook.cashflow import service as cash
from sallimbook.cashflow.models import CashRecord
from sallimbook.cashflow.schemas import CashInput
from sallimbook.core.errors import DomainError
from sallimbook.insurance import service as core
from sallimbook.insurance.event_models import (
    ClaimExpense,
    InsuranceClaim,
    InsurancePayout,
    InsuranceReturn,
    MedicalExpense,
    MedicalExpenseLine,
    MedicalRefund,
    PayoutAllocation,
)
from sallimbook.insurance.models import MedicalNode
from sallimbook.insurance.schemas import CaseInput, MedicalNodeInput, MedicalNodePatch, PolicyCreate

pytestmark = pytest.mark.database


def actors(actor):
    return dict(
        household_id=actor.household_id,
        created_by_member_id=actor.member_id,
        updated_by_member_id=actor.member_id,
    )


@pytest.fixture
def context(db_engine):
    actor = make_actor(db_engine)
    with Session(db_engine) as session:
        case = core.create_case(
            session,
            actor.principal,
            CaseInput(
                title="합성 DB 사건",
                patient_member_id=actor.member_id,
                start_on="2026-01-01",
            ),
        )
        node = core.create_node(
            session,
            actor.principal,
            case.id,
            MedicalNodeInput(
                kind="outpatient",
                label="합성 진료",
            ),
        )
    return actor, case.id, node.id


def fact(session, actor, kind, amount="100", reverses_id=None):
    return cash.prepare_cash_record(
        session,
        actor.principal,
        CashInput(
            amount_krw=amount,
            period_month="2026-01",
            date_precision="day",
            occurred_on="2026-01-01",
        ),
        kind=kind,
        reverses_id=reverses_id,
    )


def expense(session, context, lines=()):
    actor, case_id, node_id = context
    source = fact(session, actor, "medical_payment")
    row = MedicalExpense(
        case_id=case_id, node_id=node_id, cash_record_id=source.id, **actors(actor)
    )
    session.add(row)
    session.flush()
    for amount in lines:
        session.add(
            MedicalExpenseLine(
                household_id=actor.household_id,
                expense_id=row.id,
                label="합성 상세",
                detail_type="other",
                amount_krw=Decimal(amount),
            )
        )
    return row, source


def payout(session, context, amounts=("100",)):
    actor, case_id, _ = context
    source = fact(session, actor, "insurance_receipt")
    row = InsurancePayout(cash_record_id=source.id, **actors(actor))
    session.add(row)
    session.flush()
    allocations = []
    for amount in amounts:
        allocation = PayoutAllocation(
            payout_id=row.id,
            case_id=case_id,
            benefit_type="fixed",
            amount_krw=Decimal(amount),
            **actors(actor),
        )
        session.add(allocation)
        allocations.append(allocation)
    session.flush()
    return row, source, allocations


@pytest.mark.parametrize(
    "lines,valid", [((), True), (("25", "75"), True), (("0", "100"), True), (("25", "74"), False)]
)
def test_optional_receipt_lines_equal_actual_fact_at_commit(db_engine, context, lines, valid):
    with Session(db_engine) as session:
        expense(session, context, lines)
        if valid:
            session.commit()
            assert session.scalar(select(func.sum(CashRecord.amount_krw))) == 100
        else:
            with pytest.raises(DBAPIError) as rejected:
                session.commit()
            assert rejected.value.orig.sqlstate == "23514"
            session.rollback()
            assert session.scalar(select(func.count()).select_from(MedicalExpense)) == 0
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 0


@pytest.mark.parametrize(
    "amounts,valid", [(("40", "60"), True), ((), False), (("99",), False), (("101",), False)]
)
def test_payout_requires_exact_nonempty_allocations_at_commit(db_engine, context, amounts, valid):
    with Session(db_engine) as session:
        payout(session, context, amounts)
        if valid:
            session.commit()
        else:
            with pytest.raises(DBAPIError) as rejected:
                session.commit()
            assert rejected.value.orig.sqlstate == "23514"
            session.rollback()
            assert session.scalar(select(func.count()).select_from(CashRecord)) == 0


@pytest.mark.parametrize(
    "mutation", ["expense", "line", "cash_amount", "cash_reopen", "allocation", "delete"]
)
def test_actual_facts_and_allocations_reject_direct_overwrite(db_engine, context, mutation):
    actor = context[0]
    with Session(db_engine) as session:
        item, source = expense(session, context, ("100",))
        _, _, allocations = payout(session, context)
        session.commit()
        if mutation == "cash_reopen":
            cash.prepare_void_cash_record(
                session, actor.principal, source.id, kind="medical_payment", reason="합성 무효"
            )
            session.commit()
        statement = {
            "expense": update(MedicalExpense).values(provider_name="합성 덮어쓰기", version=2),
            "line": update(MedicalExpenseLine).values(amount_krw=1),
            "cash_amount": update(CashRecord)
            .where(CashRecord.id == source.id)
            .values(amount_krw=1),
            "cash_reopen": update(CashRecord)
            .where(CashRecord.id == source.id)
            .values(state="active", version=3),
            "allocation": update(PayoutAllocation)
            .where(PayoutAllocation.id == allocations[0].id)
            .values(amount_krw=1, version=2),
            "delete": delete(MedicalExpense).where(MedicalExpense.id == item.id),
        }[mutation]
        with pytest.raises(DBAPIError) as rejected:
            session.execute(statement)
        assert rejected.value.orig.sqlstate == "55000"
        session.rollback()


def test_expense_history_prevents_prescription_conversion_even_after_void(db_engine, context):
    actor, case_id, node_id = context
    with Session(db_engine) as session:
        _, source = expense(session, context)
        session.commit()
        cash.prepare_void_cash_record(
            session, actor.principal, source.id, kind="medical_payment", reason="합성 무효"
        )
        session.commit()
        with pytest.raises(DomainError) as rejected:
            core.update_node(
                session,
                actor.principal,
                case_id,
                node_id,
                MedicalNodePatch(kind="prescription"),
                '"1"',
            )
        assert rejected.value.code == "MEDICAL_NODE_IN_USE"
        session.rollback()
        with pytest.raises(DBAPIError) as rejected:
            session.execute(
                update(MedicalNode).where(MedicalNode.id == node_id).values(kind="prescription")
            )
        assert rejected.value.orig.sqlstate == "23514"
        session.rollback()


def test_prescription_rejects_direct_expense_creation(db_engine, context):
    _, _, node_id = context
    with Session(db_engine) as session:
        session.execute(
            update(MedicalNode).where(MedicalNode.id == node_id).values(kind="prescription")
        )
        session.commit()
        with pytest.raises(DBAPIError) as rejected:
            expense(session, context)
        assert rejected.value.orig.sqlstate == "23514"
        session.rollback()
        assert session.scalar(select(func.count()).select_from(CashRecord)) == 0


def test_linked_claim_blocks_expense_void_until_explicit_unlink(db_engine, context):
    actor, case_id, _ = context
    with Session(db_engine) as session:
        policy = core.create_policy(
            session,
            actor.principal,
            PolicyCreate(
                insurer="합성 보험사",
                product_name="합성 보험",
                coverage_start="2026-01-01",
            ),
            None,
        )
        item, source = expense(session, context)
        claim = InsuranceClaim(
            case_id=case_id, policy_id=policy.id, claim_state="draft", **actors(actor)
        )
        session.add(claim)
        session.flush()
        session.add(
            ClaimExpense(
                household_id=actor.household_id,
                case_id=case_id,
                claim_id=claim.id,
                expense_id=item.id,
            )
        )
        session.commit()
        with pytest.raises(DBAPIError) as rejected:
            cash.prepare_void_cash_record(
                session, actor.principal, source.id, kind="medical_payment", reason="합성 거절"
            )
        assert rejected.value.orig.sqlstate == "23514"
        session.rollback()
        session.execute(delete(ClaimExpense).where(ClaimExpense.expense_id == item.id))
        cash.prepare_void_cash_record(
            session,
            actor.principal,
            source.id,
            kind="medical_payment",
            reason="합성 연결 해제 후 무효",
        )
        session.commit()
        with pytest.raises(DBAPIError) as rejected:
            session.add(
                ClaimExpense(
                    household_id=actor.household_id,
                    case_id=case_id,
                    claim_id=claim.id,
                    expense_id=item.id,
                )
            )
            session.flush()
        assert rejected.value.orig.sqlstate == "23514"
        session.rollback()


def test_insurance_return_cannot_exceed_its_allocation(db_engine, context):
    actor = context[0]
    with Session(db_engine) as session:
        paid, source, allocations = payout(session, context, ("40", "60"))
        session.commit()
        returned = fact(session, actor, "insurance_return", "41", source.id)
        session.add(
            InsuranceReturn(
                payout_id=paid.id,
                original_allocation_id=allocations[0].id,
                cash_record_id=returned.id,
                reason="합성 초과 반환",
                **actors(actor),
            )
        )
        with pytest.raises(DBAPIError) as rejected:
            session.commit()
        assert rejected.value.orig.sqlstate == "23514"
        session.rollback()
        assert session.scalar(select(func.count()).select_from(InsuranceReturn)) == 0


def test_refund_requires_its_actual_original_expense(db_engine, context):
    actor = context[0]
    with Session(db_engine) as session:
        original, original_cash = expense(session, context)
        wrong, _ = expense(session, context)
        session.commit()
        returned = fact(session, actor, "medical_refund", "20", original_cash.id)
        session.add(
            MedicalRefund(
                expense_id=wrong.id,
                cash_record_id=returned.id,
                reason="합성 잘못된 원본",
                **actors(actor),
            )
        )
        with pytest.raises(DBAPIError) as rejected:
            session.flush()
        assert rejected.value.orig.sqlstate == "23514"
        session.rollback()
