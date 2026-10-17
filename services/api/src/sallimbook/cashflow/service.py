"""Manual income and shared cash facts, serialized without changing any snapshot."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from sallimbook.accounts.models import FinancialAccount
from sallimbook.assets.models import Asset
from sallimbook.cashflow.calculations import IncomeValue, income_totals
from sallimbook.cashflow.models import (
    FLOWS,
    INCOME_KINDS,
    PROJECTED_INCOME_KINDS,
    REVERSED_KINDS,
    CashRecord,
    CashRecordRevision,
    IncomeConversion,
)
from sallimbook.cashflow.schemas import (
    CashInput,
    CashResponse,
    ConversionResponse,
    DuplicateResponse,
    IncomeConvert,
    IncomeCreate,
    IncomeHistoryResponse,
    IncomeInput,
    IncomeListResponse,
    IncomePatch,
    IncomeReturn,
    IncomeSummaryResponse,
    IncomeTotalsResponse,
    IncomeVoid,
    MemberIncomeSummary,
)
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import Principal, require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.idempotency import IdempotentResult, run_idempotent
from sallimbook.core.types import decimal_krw, krw_string, month_start
from sallimbook.identity.auth_models import HouseholdMember
from sallimbook.identity.models import Household

_VALUES = (
    "household_id",
    "kind",
    "flow",
    "amount_krw",
    "period_month",
    "occurred_on",
    "date_precision",
    "member_id",
    "account_id",
    "reverses_id",
    "state",
    "note",
    "created_by_member_id",
    "updated_by_member_id",
    "created_at",
    "updated_at",
)


def lock_cash_household(session: Session, principal: Principal) -> None:
    """Shared mutation order: household -> idempotency/source rows -> account validation.

    Future medical/insurance/fixed-payment services acquire this before their own
    resource locks and create the subtype with the cash fact in one transaction.
    """
    if (
        session.scalar(
            select(Household.id).where(Household.id == principal.household_id).with_for_update()
        )
        is None
    ):
        raise DomainError("NOT_FOUND", "요청한 가계를 찾을 수 없습니다.", 404)


def _response(row: CashRecordRevision) -> CashResponse:
    values = {name: getattr(row, name) for name in _VALUES}
    values["amount_krw"] = krw_string(row.amount_krw)
    values["period_month"] = row.period_month.strftime("%Y-%m")
    return CashResponse(
        **values,
        id=row.cash_record_id,
        version=row.version,
        action=row.action,
        reason=row.reason,
        conversion_id=row.conversion_id,
        editable=row.kind in (*INCOME_KINDS, "income_return") and row.state == "active",
    )


def _revision(session: Session, principal: Principal, record_id: UUID, version: int):
    row = session.scalar(
        select(CashRecordRevision).where(
            CashRecordRevision.household_id == principal.household_id,
            CashRecordRevision.cash_record_id == record_id,
            CashRecordRevision.version == version,
        )
    )
    if row is None:
        raise DomainError("NOT_FOUND", "요청한 기록을 찾을 수 없습니다.", 404)
    return row


def _remember(
    session: Session,
    principal: Principal,
    row: CashRecord,
    *,
    action: str,
    reason: str | None = None,
    conversion_id: UUID | None = None,
    changed_fields=(),
    before_version: int | None = None,
) -> None:
    session.flush()
    session.add(
        CashRecordRevision(
            **{name: getattr(row, name) for name in _VALUES},
            cash_record_id=row.id,
            version=row.version,
            action=action,
            reason=reason,
            conversion_id=conversion_id,
        )
    )
    record_event(
        session,
        principal,
        entity_type="cash_record",
        entity_id=row.id,
        action="convert" if action.startswith("convert_") else action,
        before_version=before_version,
        after_version=row.version,
        changed_fields=changed_fields,
    )
    session.flush()


def _validate_links(
    session: Session,
    principal: Principal,
    payload: CashInput,
    *,
    previous: CashRecord | None = None,
) -> None:
    # Match existing asset/account writers: Asset -> Account -> Member. IDs cannot be retargeted.
    if payload.account_id is not None:
        account = scoped_entity(session, FinancialAccount, payload.account_id, principal)
        asset = scoped_entity(session, Asset, account.asset_id, principal, for_update=True)
        account = scoped_entity(
            session, FinancialAccount, payload.account_id, principal, for_update=True
        )
        if (previous is None or previous.account_id != account.id) and asset.ended_on is not None:
            raise DomainError("ACCOUNT_UNAVAILABLE", "사용 중인 입금 계좌를 선택해 주세요.", 422)
    if payload.member_id is not None:
        member = scoped_entity(
            session, HouseholdMember, payload.member_id, principal, for_update=True
        )
        if (previous is None or previous.member_id != member.id) and member.status != "active":
            raise DomainError("MEMBER_UNAVAILABLE", "현재 가계 구성원을 선택해 주세요.", 422)


def _active_returns(session: Session, principal: Principal, row: CashRecord) -> list[CashRecord]:
    return list(
        session.scalars(
            select(CashRecord)
            .where(
                CashRecord.household_id == principal.household_id,
                CashRecord.reverses_id == row.id,
                CashRecord.state == "active",
            )
            .order_by(CashRecord.id)
        )
    )


def _no_returns(session: Session, principal: Principal, row: CashRecord) -> None:
    if _active_returns(session, principal, row):
        raise DomainError(
            "INCOME_HAS_RETURNS", "반환 기록을 먼저 확인한 뒤 원본을 정정해 주세요.", 409
        )


def prepare_cash_record(
    session: Session,
    principal: Principal,
    payload: CashInput,
    *,
    kind: str,
    reverses_id: UUID | None = None,
    reason: str | None = None,
    conversion_id: UUID | None = None,
) -> CashRecord:
    """Flush-only cash fact + typed version + metadata audit, with household validation.

    No generic HTTP endpoint exposes non-income kinds. Subtype callers must create exactly
    one subtype referencing this ID (unique household-scoped FK) in this same transaction,
    and use their operation's idempotency reservation. This helper never commits, changes
    account balances, or writes monthly snapshots. Card links require a later real schema.
    """
    lock_cash_household(session, principal)
    if kind not in FLOWS or (kind in REVERSED_KINDS) != (reverses_id is not None):
        raise DomainError("INVALID_CASH_KIND", "금전 기록의 종류와 원본을 확인해 주세요.", 422)
    if kind in (*INCOME_KINDS, "income_return") and payload.member_id is None:
        raise DomainError("MEMBER_REQUIRED", "수입 구성원을 선택해 주세요.", 422)
    if reverses_id is not None:
        original = scoped_entity(session, CashRecord, reverses_id, principal, for_update=True)
        if original.kind not in REVERSED_KINDS[kind] or original.state != "active":
            raise DomainError("INVALID_REVERSAL", "반환할 원본을 확인해 주세요.", 409)
        if original.member_id != payload.member_id:
            raise DomainError("INVALID_REVERSAL", "반환과 원본의 구성원을 확인해 주세요.", 422)
        returned = sum(int(row.amount_krw) for row in _active_returns(session, principal, original))
        if returned + int(payload.amount_krw) > int(original.amount_krw):
            raise DomainError("RETURN_EXCEEDS_ORIGINAL", "반환 합계가 원본 금액을 초과합니다.", 409)
    _validate_links(session, principal, payload)
    values = payload.model_dump(include=set(CashInput.model_fields))
    values["amount_krw"] = decimal_krw(payload.amount_krw)
    values["period_month"] = month_start(payload.period_month)
    row = CashRecord(
        **values,
        household_id=principal.household_id,
        kind=kind,
        flow=FLOWS[kind],
        reverses_id=reverses_id,
        state="active",
        created_by_member_id=principal.member_id,
        updated_by_member_id=principal.member_id,
    )
    session.add(row)
    _remember(
        session,
        principal,
        row,
        action="convert_result" if conversion_id else "create",
        reason=reason,
        conversion_id=conversion_id,
        changed_fields=payload.model_fields_set,
    )
    return row


def _income_record(session: Session, principal: Principal, record_id: UUID, *, lock=False):
    row = scoped_entity(session, CashRecord, record_id, principal, for_update=lock)
    if row.kind not in PROJECTED_INCOME_KINDS:
        raise DomainError("NOT_FOUND", "요청한 수입 기록을 찾을 수 없습니다.", 404)
    return row


def _manual_active(row: CashRecord, *, allow_return=False):
    kinds = (*INCOME_KINDS, "income_return") if allow_return else INCOME_KINDS
    if row.kind not in kinds:
        raise DomainError("SOURCE_DOMAIN_REQUIRED", "원본을 등록한 영역에서 수정해 주세요.", 409)
    if row.state != "active":
        raise DomainError("INCOME_VOID", "무효 처리된 기록은 수정할 수 없습니다.", 409)


def _scope(payload: IncomeInput):
    return (payload.period_month, payload.kind, payload.member_id)


def _duplicate_rows(
    session: Session,
    principal: Principal,
    *,
    month,
    kind,
    member_id,
    date_precision,
    exclude_id=None,
):
    query = select(CashRecord).where(
        CashRecord.household_id == principal.household_id,
        CashRecord.period_month == month_start(month),
        CashRecord.kind == kind,
        CashRecord.member_id == member_id,
        CashRecord.state == "active",
        CashRecord.date_precision != date_precision,
    )
    if exclude_id is not None:
        query = query.where(CashRecord.id != exclude_id)
    return list(session.scalars(query.order_by(CashRecord.id).limit(21)))


def _check_duplicate(session, principal, payload, acknowledged, exclude_id=None):
    if not acknowledged and _duplicate_rows(
        session,
        principal,
        month=payload.period_month,
        kind=payload.kind,
        member_id=payload.member_id,
        date_precision=payload.date_precision,
        exclude_id=exclude_id,
    ):
        raise DomainError(
            "INCOME_DUPLICATE_SUSPECTED", "같은 월의 일별·월합계 수입을 확인해 주세요.", 409
        )


def _finish(session: Session, principal: Principal, result: IdempotentResult) -> CashResponse:
    response = _response(_revision(session, principal, result.resource_id, result.resource_version))
    session.commit()
    return response


def create_income(session: Session, principal: Principal, payload: IncomeCreate, key: str | None):
    lock_cash_household(session, principal)

    def execute():
        _check_duplicate(session, principal, payload, payload.duplicate_acknowledged)
        row = prepare_cash_record(session, principal, payload, kind=payload.kind)
        return IdempotentResult(row.id, "cash_record", row.version)

    return _finish(
        session,
        principal,
        run_idempotent(
            session,
            principal,
            "income.create",
            key,
            payload.model_dump(mode="json"),
            execute,
        ),
    )


def correct_income(session, principal, record_id, payload: IncomePatch, if_match, key):
    lock_cash_household(session, principal)
    supplied = payload.model_dump(exclude_unset=True, exclude={"reason", "duplicate_acknowledged"})

    def execute():
        row = _income_record(session, principal, record_id, lock=True)
        require_version(row, if_match)
        _manual_active(row)
        _no_returns(session, principal, row)
        values = {name: getattr(row, name) for name in IncomeInput.model_fields}
        values.update(
            amount_krw=krw_string(row.amount_krw), period_month=row.period_month.strftime("%Y-%m")
        )
        try:
            candidate = IncomeInput.model_validate(values | supplied)
        except ValidationError:
            raise DomainError(
                "INVALID_INCOME", "수입 날짜·정밀도와 입력 항목을 확인해 주세요.", 422
            ) from None
        _check_duplicate(session, principal, candidate, payload.duplicate_acknowledged, row.id)
        _validate_links(session, principal, candidate, previous=row)
        previous = row.version
        values = candidate.model_dump()
        values.update(
            amount_krw=decimal_krw(candidate.amount_krw),
            period_month=month_start(candidate.period_month),
        )
        for name, value in values.items():
            setattr(row, name, value)
        row.version += 1
        row.updated_by_member_id = principal.member_id
        row.updated_at = datetime.now(UTC)
        _remember(
            session,
            principal,
            row,
            action="correct",
            reason=payload.reason,
            changed_fields=supplied,
            before_version=previous,
        )
        return IdempotentResult(row.id, "cash_record", row.version, 200)

    return _finish(
        session,
        principal,
        run_idempotent(
            session,
            principal,
            "income.correct",
            key,
            {
                "id": str(record_id),
                "if_match": if_match,
                "body": payload.model_dump(mode="json", exclude_unset=True),
            },
            execute,
        ),
    )


def _void(session, principal, row, reason, *, conversion_id=None):
    previous = row.version
    row.state = "void"
    row.version += 1
    row.updated_by_member_id = principal.member_id
    row.updated_at = datetime.now(UTC)
    _remember(
        session,
        principal,
        row,
        action="convert_source" if conversion_id else "void",
        reason=reason,
        conversion_id=conversion_id,
        changed_fields=("state",),
        before_version=previous,
    )


def void_income(session, principal, record_id, payload: IncomeVoid, if_match, key):
    lock_cash_household(session, principal)

    def execute():
        row = _income_record(session, principal, record_id, lock=True)
        require_version(row, if_match)
        _manual_active(row, allow_return=True)
        _no_returns(session, principal, row)
        _void(session, principal, row, payload.reason)
        return IdempotentResult(row.id, "cash_record", row.version, 200)

    return _finish(
        session,
        principal,
        run_idempotent(
            session,
            principal,
            "income.void",
            key,
            {"id": str(record_id), "if_match": if_match, "body": payload.model_dump(mode="json")},
            execute,
        ),
    )


def return_income(session, principal, record_id, payload: IncomeReturn, if_match, key):
    lock_cash_household(session, principal)

    def execute():
        original = _income_record(session, principal, record_id, lock=True)
        require_version(original, if_match)
        _manual_active(original)
        cash = CashInput.model_validate(
            payload.model_dump(exclude={"reason"}) | {"member_id": original.member_id}
        )
        row = prepare_cash_record(
            session,
            principal,
            cash,
            kind="income_return",
            reverses_id=original.id,
            reason=payload.reason,
        )
        return IdempotentResult(row.id, "cash_record", row.version)

    return _finish(
        session,
        principal,
        run_idempotent(
            session,
            principal,
            "income.return",
            key,
            {"id": str(record_id), "if_match": if_match, "body": payload.model_dump(mode="json")},
            execute,
        ),
    )


def convert_income(session, principal, payload: IncomeConvert, key):
    lock_cash_household(session, principal)

    def execute():
        versions = {source.id: source.version for source in payload.sources}
        sources = [
            _income_record(session, principal, record_id, lock=True)
            for record_id in sorted(versions)
        ]
        for row in sources:
            require_version(row, f'"{versions[row.id]}"')
            _manual_active(row)
            _no_returns(session, principal, row)
        first = sources[0]
        scope = (first.period_month.strftime("%Y-%m"), first.kind, first.member_id)
        if any(
            (row.period_month.strftime("%Y-%m"), row.kind, row.member_id) != scope
            or row.date_precision != first.date_precision
            for row in sources
        ):
            raise DomainError(
                "INVALID_CONVERSION", "같은 월·구성원·종류·정밀도의 원본을 선택해 주세요.", 422
            )
        if any(
            _scope(item) != scope or item.date_precision == first.date_precision
            for item in payload.replacements
        ):
            raise DomainError(
                "INVALID_CONVERSION", "전환할 월·구성원·종류와 반대 정밀도를 확인해 주세요.", 422
            )
        if sum(int(row.amount_krw) for row in sources) != sum(
            int(item.amount_krw) for item in payload.replacements
        ):
            raise DomainError(
                "CONVERSION_TOTAL_MISMATCH", "전환 전후의 수입 합계가 같아야 합니다.", 422
            )
        scope_ids = set(
            session.scalars(
                select(CashRecord.id).where(
                    CashRecord.household_id == principal.household_id,
                    CashRecord.period_month == first.period_month,
                    CashRecord.kind == first.kind,
                    CashRecord.member_id == first.member_id,
                    CashRecord.state == "active",
                )
            )
        )
        if scope_ids != set(versions):
            raise DomainError(
                "INCOMPLETE_CONVERSION", "같은 범위의 활성 수입을 모두 확인해 주세요.", 409
            )
        conversion = IncomeConversion(
            household_id=principal.household_id,
            created_by_member_id=principal.member_id,
            reason=payload.reason,
        )
        session.add(conversion)
        session.flush()
        for row in sources:
            _void(session, principal, row, payload.reason, conversion_id=conversion.id)
        for item in payload.replacements:
            prepare_cash_record(
                session,
                principal,
                item,
                kind=item.kind,
                reason=payload.reason,
                conversion_id=conversion.id,
            )
        record_event(
            session,
            principal,
            entity_type="income_conversion",
            entity_id=conversion.id,
            action="convert",
            before_version=None,
            after_version=1,
            changed_fields=("sources", "replacements"),
        )
        return IdempotentResult(conversion.id, "income_conversion", 1)

    result = run_idempotent(
        session, principal, "income.convert", key, payload.model_dump(mode="json"), execute
    )
    conversion = scoped_entity(session, IncomeConversion, result.resource_id, principal)
    rows = list(
        session.scalars(
            select(CashRecordRevision)
            .where(
                CashRecordRevision.household_id == principal.household_id,
                CashRecordRevision.conversion_id == conversion.id,
            )
            .order_by(CashRecordRevision.cash_record_id)
        )
    )
    response = ConversionResponse(
        id=conversion.id,
        version=1,
        reason=conversion.reason,
        created_at=conversion.created_at,
        sources=[_response(row) for row in rows if row.action == "convert_source"],
        replacements=[_response(row) for row in rows if row.action == "convert_result"],
    )
    session.commit()
    return response


def get_income(session, principal, record_id):
    row = _income_record(session, principal, record_id)
    response = _response(_revision(session, principal, row.id, row.version))
    session.commit()
    return response


def list_income(
    session, principal, month, *, member_id=None, kind=None, state="active", cursor=None, limit=50
):
    if member_id is not None:
        scoped_entity(session, HouseholdMember, member_id, principal)
    query = (
        select(CashRecordRevision)
        .join(
            CashRecord,
            (
                (CashRecordRevision.household_id == CashRecord.household_id)
                & (CashRecordRevision.cash_record_id == CashRecord.id)
                & (CashRecordRevision.version == CashRecord.version)
            ),
        )
        .where(
            CashRecord.household_id == principal.household_id,
            CashRecord.period_month == month_start(month),
            CashRecord.kind.in_(PROJECTED_INCOME_KINDS),
        )
    )
    if member_id is not None:
        query = query.where(CashRecord.member_id == member_id)
    if kind is not None:
        query = query.where(CashRecord.kind == kind)
    if state != "all":
        query = query.where(CashRecord.state == state)
    if cursor is not None:
        query = query.where(CashRecord.id < cursor)
    rows = list(session.scalars(query.order_by(CashRecord.id.desc()).limit(limit + 1)))
    response = IncomeListResponse(
        items=[_response(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].cash_record_id if len(rows) > limit else None,
    )
    session.commit()
    return response


def history(session, principal, record_id, *, cursor=None, limit=50):
    _income_record(session, principal, record_id)
    query = select(CashRecordRevision).where(
        CashRecordRevision.household_id == principal.household_id,
        CashRecordRevision.cash_record_id == record_id,
    )
    if cursor is not None:
        query = query.where(CashRecordRevision.version < cursor)
    rows = list(session.scalars(query.order_by(CashRecordRevision.version.desc()).limit(limit + 1)))
    response = IncomeHistoryResponse(
        items=[_response(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].version if len(rows) > limit else None,
    )
    session.commit()
    return response


def duplicates(session, principal, *, month, kind, member_id, date_precision):
    scoped_entity(session, HouseholdMember, member_id, principal)
    rows = _duplicate_rows(
        session,
        principal,
        month=month,
        kind=kind,
        member_id=member_id,
        date_precision=date_precision,
    )
    response = DuplicateResponse(
        suspected=bool(rows),
        truncated=len(rows) > 20,
        items=[_response(_revision(session, principal, row.id, row.version)) for row in rows[:20]],
    )
    session.commit()
    return response


def summary(session, principal, month):
    rows = list(
        session.scalars(
            select(CashRecord).where(
                CashRecord.household_id == principal.household_id,
                CashRecord.period_month == month_start(month),
                CashRecord.kind.in_(PROJECTED_INCOME_KINDS),
                CashRecord.state == "active",
            )
        )
    )

    def totals(records):
        try:
            return IncomeTotalsResponse(
                **income_totals(
                    IncomeValue(str(row.id), row.kind, row.amount_krw, row.state) for row in records
                )
            )
        except ValueError:
            raise DomainError(
                "AMOUNT_OUT_OF_RANGE", "집계 금액이 지원 범위를 초과합니다.", 422
            ) from None

    members = sorted({row.member_id for row in rows}, key=lambda value: str(value or ""))
    response = IncomeSummaryResponse(
        period_month=month,
        totals=totals(rows),
        members=[
            MemberIncomeSummary(
                member_id=member, totals=totals(row for row in rows if row.member_id == member)
            )
            for member in members
        ],
    )
    session.commit()
    return response
