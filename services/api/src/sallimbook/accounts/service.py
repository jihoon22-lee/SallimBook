"""Account metadata shares its asset's identity and lifecycle, never a second balance."""

from pathlib import Path
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sallimbook.accounts.crypto import KeyRing, SealedNumber, decrypt_number, encrypt_number
from sallimbook.accounts.models import FinancialAccount
from sallimbook.accounts.schemas import (
    AccountCreate,
    AccountListResponse,
    AccountPatch,
    AccountResponse,
    AccountRevealResponse,
    AccountType,
)
from sallimbook.assets.locking import lock_asset_scope
from sallimbook.assets.models import Asset
from sallimbook.assets.service import asset_response, prepare_asset
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import (
    Principal,
    require_version,
    scoped_entity,
)
from sallimbook.core.errors import DomainError
from sallimbook.core.pagination import keyset_page
from sallimbook.identity import service as identity
from sallimbook.identity.auth_models import HouseholdMember
from sallimbook.identity.passkeys.models import StepUpPurpose
from sallimbook.identity.passkeys.service import consume_step_up


def account_response(account: FinancialAccount, asset: Asset) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        household_id=account.household_id,
        asset_id=account.asset_id,
        asset=asset_response(asset),
        institution_name=account.institution_name,
        account_type=account.account_type,
        masked_number="**** " + account.last_four if account.last_four is not None else None,
        has_number=account.account_number_ciphertext is not None,
        purpose=account.purpose,
        opened_on=account.opened_on,
        closed_on=asset.ended_on,
        status="closed" if asset.ended_on is not None else "active",
        created_by_member_id=account.created_by_member_id,
        updated_by_member_id=account.updated_by_member_id,
        created_at=account.created_at,
        updated_at=account.updated_at,
        version=account.version,
    )


def _account_and_asset(
    session: Session, principal: Principal, account_id: UUID, *, lock: bool = False
):
    if not lock:
        row = session.execute(
            select(FinancialAccount, Asset)
            .join(
                Asset,
                (Asset.id == FinancialAccount.asset_id)
                & (Asset.household_id == FinancialAccount.household_id),
            )
            .where(
                FinancialAccount.id == account_id,
                FinancialAccount.household_id == principal.household_id,
            )
        ).one_or_none()
        if row is None:
            raise DomainError("NOT_FOUND", "요청한 항목을 찾을 수 없습니다.", 404)
        return row
    account = scoped_entity(session, FinancialAccount, account_id, principal)
    # Asset first, then account: closure/category guards in asset updates use the same order.
    asset = scoped_entity(session, Asset, account.asset_id, principal, for_update=lock)
    if lock:
        account = scoped_entity(session, FinancialAccount, account_id, principal, for_update=True)
    return account, asset


def _validate_dates(opened_on, asset: Asset) -> None:
    if opened_on is not None and asset.ended_on is not None and opened_on > asset.ended_on:
        raise DomainError(
            "INVALID_ACCOUNT_DATES", "개설일과 연결 자산의 종료일을 확인해 주세요.", 422
        )


def _write_number(account: FinancialAccount, number: SecretStr | None, key_file: Path | str | None):
    if number is None:
        account.account_number_ciphertext = None
        account.number_nonce = None
        account.number_key_version = None
        account.last_four = None
        return
    raw = number.get_secret_value()
    sealed = encrypt_number(KeyRing.load(key_file), account.household_id, account.id, raw)
    account.account_number_ciphertext = sealed.ciphertext
    account.number_nonce = sealed.nonce
    account.number_key_version = sealed.key_version
    account.last_four = raw.replace(" ", "").replace("-", "")[-4:]


def create_account(
    session: Session,
    principal: Principal,
    payload: AccountCreate,
    key_file: Path | str | None,
    *,
    request_id: str | None = None,
) -> AccountResponse:
    asset = (
        prepare_asset(session, principal, payload.asset)
        if payload.asset is not None
        else scoped_entity(session, Asset, payload.asset_id, principal, for_update=True)
    )
    if asset.kind != "asset" or asset.category != "financial":
        raise DomainError("FINANCIAL_ASSET_REQUIRED", "금융 자산을 선택해 주세요.", 422)
    if (
        session.scalar(
            select(FinancialAccount.id).where(
                FinancialAccount.asset_id == asset.id,
                FinancialAccount.household_id == principal.household_id,
            )
        )
        is not None
    ):
        raise DomainError("ASSET_ALREADY_LINKED", "이미 계좌와 연결된 자산입니다.", 409)
    if payload.asset_id is not None and asset.ended_on is not None:
        raise DomainError("ASSET_UNAVAILABLE", "사용 중인 금융 자산을 선택해 주세요.", 422)
    _validate_dates(payload.opened_on, asset)
    account = FinancialAccount(
        id=uuid4(),
        household_id=principal.household_id,
        asset_id=asset.id,
        institution_name=payload.institution_name,
        account_type=payload.account_type,
        purpose=payload.purpose,
        opened_on=payload.opened_on,
        created_by_member_id=principal.member_id,
        updated_by_member_id=principal.member_id,
    )
    _write_number(account, payload.account_number, key_file)
    session.add(account)
    try:
        session.flush()
        record_event(
            session,
            principal,
            entity_type="financial_account",
            entity_id=account.id,
            action="create",
            before_version=None,
            after_version=account.version,
            changed_fields=payload.model_fields_set,
            request_id=request_id,
        )
        result = account_response(account, asset)
        session.commit()
        return result
    except IntegrityError as failure:
        session.rollback()
        if (
            getattr(failure.orig, "sqlstate", None) == "23505"
            and getattr(getattr(failure.orig, "diag", None), "constraint_name", None)
            == "uq_financial_accounts_asset_id"
        ):
            raise DomainError(
                "ASSET_ALREADY_LINKED", "이미 계좌와 연결된 자산입니다.", 409
            ) from None
        raise


def get_account(session: Session, principal: Principal, account_id: UUID) -> AccountResponse:
    account, asset = _account_and_asset(session, principal, account_id)
    result = account_response(account, asset)
    session.commit()
    return result


def list_accounts(
    session: Session,
    principal: Principal,
    *,
    cursor: UUID | None = None,
    limit: int = 50,
    account_type: AccountType | None = None,
    owner_member_id: UUID | None = None,
    status: str = "active",
) -> AccountListResponse:
    if type(limit) is not int or not 1 <= limit <= 200:
        raise DomainError("INVALID_PAGE_SIZE", "조회 건수를 확인해 주세요.", 422)
    if status not in {"active", "closed", "all"}:
        raise DomainError("INVALID_STATUS", "조회 상태를 확인해 주세요.", 422)
    query = (
        select(FinancialAccount, Asset)
        .join(
            Asset,
            (Asset.id == FinancialAccount.asset_id)
            & (Asset.household_id == FinancialAccount.household_id),
        )
        .where(FinancialAccount.household_id == principal.household_id)
    )
    if owner_member_id is not None:
        scoped_entity(session, HouseholdMember, owner_member_id, principal)
        query = query.where(Asset.owner_member_id == owner_member_id)
    if account_type is not None:
        query = query.where(FinancialAccount.account_type == account_type)
    if status == "active":
        query = query.where(Asset.ended_on.is_(None))
    elif status == "closed":
        query = query.where(Asset.ended_on.is_not(None))
    rows, next_cursor = keyset_page(
        session,
        query,
        model=FinancialAccount,
        household_id=principal.household_id,
        keys=(FinancialAccount.created_at,),
        cursor=cursor,
        limit=limit,
        scalars=False,
        cursor_of=lambda row: row[0].id,
    )
    result = AccountListResponse(
        items=[account_response(account, asset) for account, asset in rows],
        next_cursor=next_cursor,
    )
    session.commit()
    return result


def update_account(
    session: Session,
    principal: Principal,
    account_id: UUID,
    payload: AccountPatch,
    if_match: str | None,
    key_file: Path | str | None,
    *,
    request_id: str | None = None,
) -> AccountResponse:
    account, asset = _account_and_asset(session, principal, account_id, lock=True)
    require_version(account, if_match)
    _validate_dates(
        payload.opened_on if "opened_on" in payload.model_fields_set else account.opened_on, asset
    )
    previous = account.version
    for name in payload.model_fields_set - {"account_number"}:
        setattr(account, name, getattr(payload, name))
    if "account_number" in payload.model_fields_set:
        _write_number(account, payload.account_number, key_file)
    account.updated_by_member_id = principal.member_id
    session.flush()
    record_event(
        session,
        principal,
        entity_type="financial_account",
        entity_id=account.id,
        action="update",
        before_version=previous,
        after_version=account.version,
        changed_fields=payload.model_fields_set,
        request_id=request_id,
    )
    result = account_response(account, asset)
    session.commit()
    return result


def delete_account(
    session: Session, principal: Principal, account_id: UUID, if_match: str | None
) -> None:
    """Delete a mistaken account and its asset together; any reference keeps both."""
    lock_asset_scope(session, principal)
    account, asset = _account_and_asset(session, principal, account_id, lock=True)
    require_version(account, if_match)
    for entity_type, row in (("financial_account", account), ("asset", asset)):
        record_event(
            session,
            principal,
            entity_type=entity_type,
            entity_id=row.id,
            action="delete",
            before_version=row.version,
            after_version=None,
        )
    try:
        # The account row goes first so financial_accounts.asset_id no longer blocks the asset.
        session.delete(account)
        session.flush()
        session.delete(asset)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if getattr(exc.orig, "sqlstate", None) in {"23001", "23503"}:
            raise DomainError(
                "ACCOUNT_IN_USE",
                "연결된 기록이 있어 삭제할 수 없습니다. 계좌 사용 종료를 선택해 주세요.",
                409,
            ) from None
        raise


def reveal_number(
    session: Session,
    principal: Principal,
    account_id: UUID,
    key_file: Path | str | None,
    *,
    step_up_token: str | None = None,
    request_id: str | None = None,
) -> AccountRevealResponse:
    # Hold the source identity before domain rows; grant verification locks follow them.
    auth, devices = identity.lock_session_devices(session, principal)
    account, _ = _account_and_asset(session, principal, account_id, lock=True)
    identity.validate_locked_session(
        principal, auth, devices[principal.device_id], recent_login=step_up_token is None
    )
    if account.account_number_ciphertext is None:
        raise DomainError("ACCOUNT_NUMBER_NOT_SET", "등록된 계좌번호가 없습니다.", 409)
    grant = None
    if step_up_token is not None:
        grant = consume_step_up(
            session, principal, step_up_token, StepUpPurpose.ACCOUNT_REVEAL, account.id
        )

    def validate_reveal() -> None:
        now = identity.validate_locked_session(
            principal, auth, devices[principal.device_id], recent_login=step_up_token is None
        )
        if grant is not None and grant.expires_at <= now:
            raise DomainError("STEP_UP_REQUIRED", "이 작업을 다시 인증해 주세요.", 403)

    validate_reveal()
    number = decrypt_number(
        KeyRing.load(key_file),
        account.household_id,
        account.id,
        SealedNumber(
            account.number_key_version, account.number_nonce, account.account_number_ciphertext
        ),
    )
    validate_reveal()
    record_event(
        session,
        principal,
        entity_type="financial_account",
        entity_id=account.id,
        action="reveal",
        before_version=account.version,
        after_version=account.version,
        request_id=request_id,
    )
    # Flush audit persistence while still holding every barrier, then check time again.
    session.flush()
    validate_reveal()
    session.commit()
    return AccountRevealResponse(id=account_id, account_number=number)
