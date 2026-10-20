"""Read registered payment links under the shared household writer barrier."""

import hashlib
import json
from datetime import date
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from sallimbook.accounts.models import FinancialAccount
from sallimbook.assets.locking import lock_asset_scope
from sallimbook.assets.models import Asset
from sallimbook.cards.models import Card
from sallimbook.cashflow.models import CashRecord
from sallimbook.cashflow.payment_link_schemas import (
    LinkedCard,
    LinkedCardPage,
    LinkedObligation,
    LinkedObligationPage,
    LinkedRule,
    LinkedRulePage,
    PaymentLinksResponse,
)
from sallimbook.cashflow.recurring_models import (
    FixedSettlement,
    RecurringRule,
    RecurringRuleVersion,
    ScheduledObligation,
)
from sallimbook.core.authorization import Principal, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.types import SEOUL
from sallimbook.identity.service import utcnow


def _page(rows, cursor, limit, model):
    visible = [row for row in rows if cursor is None or row.id < cursor]
    return model(
        items=visible[:limit],
        total_count=len(rows),
        next_cursor=visible[limit - 1].id if len(visible) > limit else None,
    )


def usage(
    session: Session,
    principal: Principal,
    kind: str,
    resource_id: UUID,
    *,
    as_of_date: date,
    rule_cursor=None,
    obligation_cursor=None,
    card_cursor=None,
    limit=50,
) -> PaymentLinksResponse:
    """Caller holds the household lock; this helper does not commit or change history."""
    household_id = principal.household_id
    asset_id = None
    related_cards = []
    if kind == "card":
        source = scoped_entity(session, Card, resource_id, principal)
        card_ids = [source.id]
    else:
        source = scoped_entity(session, FinancialAccount, resource_id, principal)
        asset = scoped_entity(session, Asset, source.asset_id, principal)
        asset_id = asset.id
        related_cards = list(
            session.scalars(
                select(Card)
                .where(
                    Card.household_id == household_id,
                    Card.settlement_account_id == source.id,
                )
                .order_by(Card.id.desc())
            )
        )
        card_ids = [card.id for card in related_cards]
    resource_version = source.version if kind == "card" else asset.version

    def linked(model):
        card_match = model.card_id.in_(card_ids)
        return card_match if kind == "card" else or_(model.account_id == resource_id, card_match)

    rule_rows = session.execute(
        select(RecurringRuleVersion, RecurringRule.version)
        .join(
            RecurringRule,
            (RecurringRule.id == RecurringRuleVersion.rule_id)
            & (RecurringRule.household_id == RecurringRuleVersion.household_id),
        )
        .where(
            RecurringRuleVersion.household_id == household_id,
            linked(RecurringRuleVersion),
            RecurringRuleVersion.revoked_at.is_(None),
            or_(
                RecurringRuleVersion.effective_until.is_(None),
                RecurringRuleVersion.effective_until > as_of_date,
            ),
        )
        .order_by(RecurringRuleVersion.id.desc())
    ).all()
    rules = [
        LinkedRule(
            **{
                name: getattr(row, name)
                for name in LinkedRule.model_fields
                if name not in {"rule_version", "payment_basis", "period", "expected_amount_krw"}
            },
            rule_version=version,
            expected_amount_krw=(
                str(row.expected_amount_krw) if row.expected_amount_krw is not None else None
            ),
            payment_basis="card_approval_plan" if row.card_id else "account_payment_plan",
            period="future" if row.effective_from > as_of_date else "current",
        )
        for row, version in rule_rows
    ]
    actuals = (
        select(
            FixedSettlement.obligation_id.label("obligation_id"),
            func.sum(CashRecord.amount_krw).label("paid"),
        )
        .join(
            CashRecord,
            (CashRecord.id == FixedSettlement.cash_record_id)
            & (CashRecord.household_id == FixedSettlement.household_id),
        )
        .where(FixedSettlement.household_id == household_id, CashRecord.state == "active")
        .group_by(
            FixedSettlement.obligation_id,
        )
        .subquery()
    )
    rows = session.execute(
        select(ScheduledObligation, func.coalesce(actuals.c.paid, 0))
        .outerjoin(
            actuals,
            actuals.c.obligation_id == ScheduledObligation.id,
        )
        .where(
            ScheduledObligation.household_id == household_id,
            linked(ScheduledObligation),
            ScheduledObligation.schedule_state == "active",
            ScheduledObligation.skipped.is_(False),
            ScheduledObligation.manually_completed.is_(False),
        )
        .order_by(ScheduledObligation.id.desc())
    ).all()
    obligations = []
    for row, paid in rows:
        if paid > 0 and row.expected_amount_krw is not None and paid >= row.expected_amount_krw:
            continue
        obligations.append(
            LinkedObligation(
                **{
                    name: getattr(row, name)
                    for name in LinkedObligation.model_fields
                    if name
                    not in {"actual_paid_krw", "expected_amount_krw", "status", "payment_basis"}
                },
                expected_amount_krw=(
                    str(row.expected_amount_krw) if row.expected_amount_krw is not None else None
                ),
                actual_paid_krw=str(paid),
                status="partial" if paid > 0 else "unpaid",
                payment_basis="card_approval_plan" if row.card_id else "account_payment_plan",
            )
        )
    cards = [
        LinkedCard(
            **{
                name: getattr(card, name)
                for name in LinkedCard.model_fields
                if name != "active_for_closure"
            },
            active_for_closure=card.ended_on is None or card.ended_on >= as_of_date,
        )
        for card in related_cards
    ]
    # The digest binds every result, including off-page rows and the selected end date.
    # It is a change detector, never an authorization credential.
    digest_data = dict(
        household_id=str(household_id),
        kind=kind,
        resource_id=str(resource_id),
        resource_version=resource_version,
        as_of_date=as_of_date.isoformat(),
        rules=[row.model_dump(mode="json") for row in rules],
        obligations=[row.model_dump(mode="json") for row in obligations],
        cards=[row.model_dump(mode="json") for row in cards],
    )
    digest = hashlib.sha256(
        json.dumps(
            digest_data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    return PaymentLinksResponse(
        resource_kind=kind,
        resource_id=resource_id,
        resource_version=resource_version,
        asset_id=asset_id,
        as_of_date=as_of_date,
        usage_digest=digest,
        requires_confirmation=bool(
            rules or obligations or any(c.active_for_closure for c in cards)
        ),
        rules=_page(rules, rule_cursor, limit, LinkedRulePage),
        obligations=_page(obligations, obligation_cursor, limit, LinkedObligationPage),
        cards=_page(cards, card_cursor, limit, LinkedCardPage),
    )


def get_usage(session, principal, kind, resource_id, *, as_of_date=None, **pages):
    lock_asset_scope(session, principal)
    result = usage(
        session,
        principal,
        kind,
        resource_id,
        as_of_date=as_of_date or utcnow().astimezone(SEOUL).date(),
        **pages,
    )
    session.commit()
    return result


def require_closure(session, principal, kind, resource_id, payload, ended_on):
    current = usage(session, principal, kind, resource_id, as_of_date=ended_on)
    if payload.closure_ack and payload.usage_digest != current.usage_digest:
        raise DomainError(
            "PAYMENT_LINKS_CHANGED", "연결 내역이 바뀌었습니다. 다시 확인해 주세요.", 409
        )
    if current.requires_confirmation and not payload.closure_ack:
        raise DomainError(
            "PAYMENT_LINK_CONFIRMATION_REQUIRED",
            "연결된 납부 내역을 확인한 뒤 종료해 주세요.",
            409,
        )
