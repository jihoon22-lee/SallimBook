"""Manual card metadata with household links and closure instead of history deletion."""

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sallimbook.accounts.models import FinancialAccount
from sallimbook.assets.locking import lock_asset_scope
from sallimbook.assets.models import Asset
from sallimbook.cards.models import Card, CardStoredDetails
from sallimbook.cards.schemas import CardCreate, CardListResponse, CardPatch, CardResponse
from sallimbook.cashflow.payment_link_schemas import CLOSURE_FIELDS
from sallimbook.cashflow.payment_links import require_closure
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import Principal, require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.name_search import search_names
from sallimbook.core.pagination import keyset_page
from sallimbook.core.types import SEOUL, decimal_krw, krw_string
from sallimbook.identity.auth_models import HouseholdMember
from sallimbook.identity.service import utcnow
from sallimbook.vault.models import CardSecretEnvelope, VaultState


def has_current_secret(session: Session, card: Card) -> bool:
    return (
        session.scalar(
            select(CardSecretEnvelope.id)
            .join(
                VaultState,
                (VaultState.household_id == CardSecretEnvelope.household_id)
                & (VaultState.current_key_version == CardSecretEnvelope.key_version),
            )
            .where(
                CardSecretEnvelope.household_id == card.household_id,
                CardSecretEnvelope.card_id == card.id,
                CardSecretEnvelope.is_current.is_(True),
                CardSecretEnvelope.ciphertext.is_not(None),
            )
        )
        is not None
    )


def has_stored_details(session: Session, card: Card) -> bool:
    return (
        session.scalar(
            select(CardStoredDetails.card_id).where(
                CardStoredDetails.household_id == card.household_id,
                CardStoredDetails.card_id == card.id,
            )
        )
        is not None
    )


def card_response(
    session: Session,
    card: Card,
    *,
    account_statuses: Mapping[UUID, str] | None = None,
    secret_card_ids: set[UUID] | None = None,
    stored_card_ids: set[UUID] | None = None,
) -> CardResponse:
    account_status = None
    if card.settlement_account_id is not None and account_statuses is not None:
        account_status = account_statuses[card.settlement_account_id]
    elif card.settlement_account_id is not None:
        ended_on = session.execute(
            select(Asset.ended_on)
            .join(
                FinancialAccount,
                (FinancialAccount.asset_id == Asset.id)
                & (FinancialAccount.household_id == Asset.household_id),
            )
            .where(
                FinancialAccount.id == card.settlement_account_id,
                FinancialAccount.household_id == card.household_id,
            )
        ).one()
        account_status = "closed" if ended_on[0] is not None else "active"
    return CardResponse(
        **{
            name: getattr(card, name)
            for name in CardResponse.model_fields
            if name
            not in {
                "masked_number",
                "status",
                "settlement_account_status",
                "has_secret",
                "has_stored_details",
                "annual_fee_krw",
            }
        },
        annual_fee_krw=krw_string(card.annual_fee_krw) if card.annual_fee_krw is not None else None,
        masked_number="**** " + card.last_four if card.last_four is not None else None,
        has_secret=(card.id in secret_card_ids)
        if secret_card_ids is not None
        else has_current_secret(session, card),
        has_stored_details=(card.id in stored_card_ids)
        if stored_card_ids is not None
        else has_stored_details(session, card),
        status="closed" if card.ended_on is not None else "active",
        settlement_account_status=account_status,
    )


def _validate_links(session: Session, principal: Principal, payload: CardCreate, previous=None):
    reactivating = (
        previous is not None and previous.ended_on is not None and payload.ended_on is None
    )
    if payload.ended_on is not None and payload.ended_on > utcnow().astimezone(SEOUL).date():
        raise DomainError("INVALID_CARD_DATES", "실제로 사용을 종료한 날짜를 입력해 주세요.", 422)
    if payload.settlement_account_id is not None:
        account = scoped_entity(session, FinancialAccount, payload.settlement_account_id, principal)
        asset = scoped_entity(session, Asset, account.asset_id, principal, for_update=True)
        scoped_entity(session, FinancialAccount, account.id, principal, for_update=True)
        new_link = previous is None or previous.settlement_account_id != account.id
        if asset.ended_on is not None and payload.ended_on is None and (new_link or reactivating):
            raise DomainError("ACCOUNT_UNAVAILABLE", "사용 중인 결제 계좌를 선택해 주세요.", 422)
    member = scoped_entity(
        session, HouseholdMember, payload.owner_member_id, principal, for_update=True
    )
    if (
        previous is None or previous.owner_member_id != member.id or reactivating
    ) and member.status != "active":
        raise DomainError("MEMBER_UNAVAILABLE", "현재 가계 구성원을 선택해 주세요.", 422)


def create_card(session: Session, principal: Principal, payload: CardCreate) -> CardResponse:
    lock_asset_scope(session, principal)
    _validate_links(session, principal, payload)
    card = Card(
        **(
            payload.model_dump()
            | {
                "annual_fee_krw": decimal_krw(payload.annual_fee_krw)
                if payload.annual_fee_krw is not None
                else None
            }
        ),
        household_id=principal.household_id,
        created_by_member_id=principal.member_id,
        updated_by_member_id=principal.member_id,
    )
    session.add(card)
    session.flush()
    record_event(
        session,
        principal,
        entity_type="card",
        entity_id=card.id,
        action="create",
        before_version=None,
        after_version=card.version,
        changed_fields=payload.model_fields_set - CLOSURE_FIELDS,
    )
    result = card_response(session, card)
    session.commit()
    return result


def update_card(
    session: Session,
    principal: Principal,
    card_id: UUID,
    payload: CardPatch,
    if_match: str,
    *,
    archive=False,
) -> CardResponse:
    lock_asset_scope(session, principal)
    card = scoped_entity(session, Card, card_id, principal, for_update=True)
    require_version(card, if_match)
    if "last_four" in payload.model_fields_set and (
        has_current_secret(session, card) or has_stored_details(session, card)
    ):
        raise DomainError(
            "CARD_SECRET_PROTECTED", "카드 끝자리는 보관함에서 함께 수정해 주세요.", 409
        )
    values = {name: getattr(card, name) for name in CardCreate.model_fields}
    if values["annual_fee_krw"] is not None:
        values["annual_fee_krw"] = krw_string(values["annual_fee_krw"])
    try:
        candidate = CardCreate.model_validate(
            values | payload.model_dump(exclude_unset=True, exclude=CLOSURE_FIELDS)
        )
    except ValidationError:
        raise DomainError(
            "INVALID_CARD", "카드 사용 기간과 입력 항목을 확인해 주세요.", 422
        ) from None
    _validate_links(session, principal, candidate, previous=card)
    if candidate.ended_on is not None and candidate.ended_on != card.ended_on:
        require_closure(session, principal, "card", card.id, payload, candidate.ended_on)
    previous_version = card.version
    for name in payload.model_fields_set - CLOSURE_FIELDS:
        value = getattr(candidate, name)
        if name == "annual_fee_krw" and value is not None:
            value = decimal_krw(value)
        setattr(card, name, value)
    card.version += 1
    card.updated_by_member_id = principal.member_id
    card.updated_at = datetime.now(UTC)
    session.flush()
    record_event(
        session,
        principal,
        entity_type="card",
        entity_id=card.id,
        action="archive" if archive else "update",
        before_version=previous_version,
        after_version=card.version,
        changed_fields=payload.model_fields_set - CLOSURE_FIELDS,
    )
    result = card_response(session, card)
    session.commit()
    return result


def delete_card(session: Session, principal: Principal, card_id: UUID, if_match: str) -> None:
    lock_asset_scope(session, principal)
    card = scoped_entity(session, Card, card_id, principal, for_update=True)
    require_version(card, if_match)
    record_event(
        session,
        principal,
        entity_type="card",
        entity_id=card.id,
        action="delete",
        before_version=card.version,
        after_version=None,
    )
    try:
        session.delete(card)
        session.flush()
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if getattr(exc.orig, "sqlstate", None) in {"23001", "23503"}:
            raise DomainError(
                "CARD_IN_USE", "기록에서 사용하는 카드입니다. 사용 종료로 보관해 주세요.", 409
            ) from None
        raise


def get_card(session: Session, principal: Principal, card_id: UUID) -> CardResponse:
    card = scoped_entity(session, Card, card_id, principal)
    result = card_response(session, card)
    session.commit()
    return result


def list_cards(
    session: Session,
    principal: Principal,
    *,
    q: str | None = None,
    owner_member_id=None,
    card_type=None,
    settlement_account_id=None,
    status="active",
    cursor=None,
    limit=50,
) -> CardListResponse:
    if owner_member_id is not None:
        scoped_entity(session, HouseholdMember, owner_member_id, principal)
    if settlement_account_id is not None:
        scoped_entity(session, FinancialAccount, settlement_account_id, principal)
    query = select(Card).where(Card.household_id == principal.household_id)
    for name, value in (
        ("owner_member_id", owner_member_id),
        ("card_type", card_type),
        ("settlement_account_id", settlement_account_id),
    ):
        if value is not None:
            query = query.where(getattr(Card, name) == value)
    if status != "all":
        query = query.where(
            Card.ended_on.is_(None) if status == "active" else Card.ended_on.is_not(None)
        )
    query = search_names(query, q, Card.alias, Card.product_name, Card.issuer_name)
    rows, next_cursor = keyset_page(
        session,
        query,
        model=Card,
        household_id=principal.household_id,
        keys=(Card.created_at,),
        cursor=cursor,
        limit=limit,
    )
    page_ids = {row.id for row in rows}
    secret_card_ids = (
        set(
            session.scalars(
                select(CardSecretEnvelope.card_id)
                .join(
                    VaultState,
                    (VaultState.household_id == CardSecretEnvelope.household_id)
                    & (VaultState.current_key_version == CardSecretEnvelope.key_version),
                )
                .where(
                    CardSecretEnvelope.household_id == principal.household_id,
                    CardSecretEnvelope.card_id.in_(page_ids),
                    CardSecretEnvelope.is_current.is_(True),
                    CardSecretEnvelope.ciphertext.is_not(None),
                )
            )
        )
        if page_ids
        else set()
    )
    stored_card_ids = (
        set(
            session.scalars(
                select(CardStoredDetails.card_id).where(
                    CardStoredDetails.household_id == principal.household_id,
                    CardStoredDetails.card_id.in_(page_ids),
                )
            )
        )
        if page_ids
        else set()
    )
    account_ids = {
        row.settlement_account_id for row in rows if row.settlement_account_id is not None
    }
    account_statuses = {}
    if account_ids:
        account_statuses = {
            account_id: "closed" if ended_on is not None else "active"
            for account_id, ended_on in session.execute(
                select(FinancialAccount.id, Asset.ended_on)
                .join(
                    Asset,
                    (Asset.id == FinancialAccount.asset_id)
                    & (Asset.household_id == FinancialAccount.household_id),
                )
                .where(
                    FinancialAccount.household_id == principal.household_id,
                    FinancialAccount.id.in_(account_ids),
                )
            )
        }
    result = CardListResponse(
        items=[
            card_response(
                session,
                row,
                account_statuses=account_statuses,
                secret_card_ids=secret_card_ids,
                stored_card_ids=stored_card_ids,
            )
            for row in rows
        ],
        next_cursor=next_cursor,
    )
    session.commit()
    return result
