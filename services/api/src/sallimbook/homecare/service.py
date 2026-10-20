"""Atomic shared inventory and per-device schedules; no cash or asset writes."""

from datetime import UTC, date, datetime
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from sallimbook.assets.locking import lock_asset_scope
from sallimbook.core.audit import record_event
from sallimbook.core.authorization import require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.idempotency import IdempotentResult, run_idempotent
from sallimbook.core.types import SEOUL, krw_string
from sallimbook.homecare.calculations import MAX_QUANTITY, consumable_status, next_check_on
from sallimbook.homecare.models import (
    Appliance,
    ApplianceConsumable,
    Consumable,
    ConsumableReplacement,
    StockMovement,
)
from sallimbook.homecare.schemas import (
    ApplianceConsumableFields,
    ApplianceConsumableListResponse,
    ApplianceConsumableResponse,
    ApplianceInput,
    ApplianceListResponse,
    ApplianceResponse,
    ConsumableInput,
    ConsumableListResponse,
    ConsumableResponse,
    HomecareStatusItem,
    HomecareStatusResponse,
    ReplacementListResponse,
    ReplacementResponse,
    StockMovementListResponse,
    StockMovementResponse,
    StockMutationReference,
)
from sallimbook.identity.service import utcnow


def today() -> date:
    return utcnow().astimezone(SEOUL).date()


def _finish(session, result):
    session.commit()
    return result


def _actors(principal):
    return dict(
        household_id=principal.household_id,
        created_by_member_id=principal.member_id,
        updated_by_member_id=principal.member_id,
    )


def delete_metadata(session, principal, model, entity_id, if_match):
    entity, code = {
        Appliance: ("appliance", "APPLIANCE_IN_USE"),
        Consumable: ("consumable", "CONSUMABLE_IN_USE"),
        ApplianceConsumable: ("appliance_consumable", "APPLIANCE_CONSUMABLE_IN_USE"),
    }[model]
    lock_asset_scope(session, principal)
    row = scoped_entity(session, model, entity_id, principal, for_update=True)
    require_version(row, if_match)
    record_event(
        session,
        principal,
        entity_type=entity,
        entity_id=row.id,
        action="delete",
        before_version=row.version,
        after_version=None,
    )
    try:
        session.delete(row)
        session.flush()
        session.commit()
    except IntegrityError as error:
        session.rollback()
        if getattr(error.orig, "sqlstate", None) in {"23001", "23503"}:
            raise DomainError(
                code, "연결 또는 사용 이력이 있습니다. 사용 종료로 보관해 주세요.", 409
            ) from None
        raise


def _touch(row, principal):
    before = row.version
    row.version += 1
    row.updated_by_member_id = principal.member_id
    row.updated_at = datetime.now(UTC)
    return before


def _audit(session, principal, row, entity, action, fields=(), before=None, after=None):
    record_event(
        session,
        principal,
        entity_type=entity,
        entity_id=row.id,
        action=action,
        before_version=before,
        after_version=after if after is not None else getattr(row, "version", 1),
        changed_fields=fields,
    )


def _actual_dates(*dates):
    current = today()
    if any(value is not None and value > current for value in dates):
        raise DomainError("INVALID_HOMECARE_DATE", "실제 날짜는 오늘 이후일 수 없습니다.", 422)


def _values(row, schema):
    result = {name: getattr(row, name) for name in schema.model_fields}
    for name in ("purchase_price_krw", "unit_cost_krw"):
        if name in result and result[name] is not None:
            result[name] = krw_string(result[name])
    return result


def _candidate(row, schema, payload):
    try:
        return schema.model_validate(_values(row, schema) | payload.model_dump(exclude_unset=True))
    except ValidationError:
        raise DomainError(
            "INVALID_HOMECARE_INPUT", "입력 항목과 날짜·주기를 확인해 주세요.", 422
        ) from None


def _assign(row, values):
    for name, value in values.items():
        if name in {"purchase_price_krw", "unit_cost_krw"} and value is not None:
            value = Decimal(value)
        setattr(row, name, value)


def _active(row, kind):
    if (isinstance(row, ApplianceConsumable) and not row.active) or getattr(
        row, "ended_on", None
    ) is not None:
        code, message = {
            "appliance": ("APPLIANCE_UNAVAILABLE", "사용 중인 가전을 선택해 주세요."),
            "consumable": ("CONSUMABLE_UNAVAILABLE", "사용 중인 소모품을 선택해 주세요."),
            "link": (
                "APPLIANCE_CONSUMABLE_UNAVAILABLE",
                "사용 중인 기기별 소모품 연결을 선택해 주세요.",
            ),
        }[kind]
        raise DomainError(code, message, 422)


def _page(session, query, model, cursor, limit):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise DomainError("INVALID_PAGE_SIZE", "목록 크기를 확인해 주세요.", 422)
    if cursor is not None:
        query = query.where(model.id < cursor)
    rows = list(session.scalars(query.order_by(model.id.desc()).limit(limit + 1)))
    return rows[:limit], rows[limit - 1].id if len(rows) > limit else None


def _status_filter(query, model, status):
    if status not in {"active", "ended", "all"}:
        raise DomainError("INVALID_HOMECARE_INPUT", "조회 상태를 확인해 주세요.", 422)
    if status == "active":
        return query.where(model.ended_on.is_(None))
    if status == "ended":
        return query.where(model.ended_on.is_not(None))
    return query


def _appliance_response(row, as_of):
    warranty = (
        "unknown"
        if row.warranty_until is None
        else "active"
        if row.warranty_until >= as_of
        else "expired"
    )
    return ApplianceResponse(
        **_values(row, ApplianceInput),
        **{
            name: getattr(row, name)
            for name in (
                "id",
                "household_id",
                "version",
                "created_by_member_id",
                "updated_by_member_id",
                "created_at",
                "updated_at",
            )
        },
        status="active" if row.ended_on is None else "ended",
        as_of=as_of,
        warranty_status=warranty,
    )


def _consumable_response(row):
    return ConsumableResponse(
        **_values(row, ConsumableInput),
        **{
            name: getattr(row, name)
            for name in (
                "id",
                "household_id",
                "version",
                "created_by_member_id",
                "updated_by_member_id",
                "created_at",
                "updated_at",
            )
        },
        status="active" if row.ended_on is None else "ended",
        stock_quantity=row.stock_quantity,
        low_stock=row.stock_quantity <= row.low_stock_threshold,
    )


def create_appliance(session, principal, payload):
    lock_asset_scope(session, principal)
    _actual_dates(payload.purchased_on, payload.ended_on)
    row = Appliance(**_actors(principal))
    _assign(row, payload.model_dump())
    session.add(row)
    session.flush()
    _audit(session, principal, row, "appliance", "create", payload.model_fields_set)
    return _finish(session, _appliance_response(row, today()))


def get_appliance(session, principal, appliance_id):
    row = scoped_entity(session, Appliance, appliance_id, principal)
    return _finish(session, _appliance_response(row, today()))


def list_appliances(session, principal, *, status="active", cursor=None, limit=50):
    query = _status_filter(
        select(Appliance).where(Appliance.household_id == principal.household_id), Appliance, status
    )
    rows, next_cursor = _page(session, query, Appliance, cursor, limit)
    current = today()
    return _finish(
        session,
        ApplianceListResponse(
            items=[_appliance_response(row, current) for row in rows], next_cursor=next_cursor
        ),
    )


def update_appliance(session, principal, appliance_id, payload, if_match):
    lock_asset_scope(session, principal)
    row = scoped_entity(session, Appliance, appliance_id, principal, for_update=True)
    require_version(row, if_match)
    candidate = _candidate(row, ApplianceInput, payload)
    _actual_dates(candidate.purchased_on, candidate.ended_on)
    before = _touch(row, principal)
    _assign(row, candidate.model_dump())
    session.flush()
    _audit(session, principal, row, "appliance", "update", payload.model_fields_set, before)
    return _finish(session, _appliance_response(row, today()))


def _unique_sku(session, principal, sku, excluding=None):
    if sku is None:
        return
    query = select(Consumable.id).where(
        Consumable.household_id == principal.household_id, Consumable.sku_or_model == sku
    )
    if excluding is not None:
        query = query.where(Consumable.id != excluding)
    if session.scalar(query) is not None:
        raise DomainError(
            "CONSUMABLE_SKU_EXISTS", "이미 등록된 규격입니다. 공용 재고를 확인해 주세요.", 409
        )


def create_consumable(session, principal, payload):
    lock_asset_scope(session, principal)
    _actual_dates(payload.ended_on)
    _unique_sku(session, principal, payload.sku_or_model)
    row = Consumable(**payload.model_dump(), **_actors(principal), stock_quantity=0)
    session.add(row)
    session.flush()
    _audit(session, principal, row, "consumable", "create", payload.model_fields_set)
    return _finish(session, _consumable_response(row))


def get_consumable(session, principal, consumable_id):
    row = scoped_entity(session, Consumable, consumable_id, principal)
    return _finish(session, _consumable_response(row))


def list_consumables(session, principal, *, status="active", cursor=None, limit=50):
    query = _status_filter(
        select(Consumable).where(Consumable.household_id == principal.household_id),
        Consumable,
        status,
    )
    rows, next_cursor = _page(session, query, Consumable, cursor, limit)
    return _finish(
        session,
        ConsumableListResponse(
            items=[_consumable_response(row) for row in rows], next_cursor=next_cursor
        ),
    )


def update_consumable(session, principal, consumable_id, payload, if_match):
    lock_asset_scope(session, principal)
    row = scoped_entity(session, Consumable, consumable_id, principal, for_update=True)
    require_version(row, if_match)
    candidate = _candidate(row, ConsumableInput, payload)
    _actual_dates(candidate.ended_on)
    _unique_sku(session, principal, candidate.sku_or_model, row.id)
    if (
        candidate.unit != row.unit
        and session.scalar(
            select(StockMovement.id)
            .where(
                StockMovement.household_id == principal.household_id,
                StockMovement.consumable_id == row.id,
            )
            .limit(1)
        )
        is not None
    ):
        raise DomainError(
            "CONSUMABLE_UNIT_IN_USE", "재고 이력이 있어 단위를 바꿀 수 없습니다.", 409
        )
    before = _touch(row, principal)
    _assign(row, candidate.model_dump())
    session.flush()
    _audit(session, principal, row, "consumable", "update", payload.model_fields_set, before)
    return _finish(session, _consumable_response(row))


def _latest_replacements(session, principal, link_ids):
    if not link_ids:
        return {}
    reversed_movement = aliased(StockMovement)
    query = (
        select(ConsumableReplacement)
        .where(
            ConsumableReplacement.household_id == principal.household_id,
            ConsumableReplacement.appliance_consumable_id.in_(link_ids),
            ~exists(
                select(reversed_movement.id).where(
                    reversed_movement.household_id == principal.household_id,
                    reversed_movement.reversal_of == ConsumableReplacement.stock_movement_id,
                )
            ),
        )
        .ext(distinct_on(ConsumableReplacement.appliance_consumable_id))
        .order_by(
            ConsumableReplacement.appliance_consumable_id,
            ConsumableReplacement.replaced_on.desc(),
            ConsumableReplacement.id.desc(),
        )
    )
    return {row.appliance_consumable_id: row for row in session.scalars(query)}


def _link_response(row, consumable, latest, as_of):
    last = latest.replaced_on if latest is not None else None
    if row.next_check_override is not None:
        next_check, source = row.next_check_override, "override"
    elif last is None or row.interval_unit == "manual":
        next_check, source = None, "unknown"
    else:
        try:
            next_check = next_check_on(
                last, interval_unit=row.interval_unit, interval_count=row.interval_count
            )
        except ValueError, OverflowError:
            raise DomainError(
                "INVALID_HOMECARE_INPUT", "계산 가능한 교체 주기를 선택해 주세요.", 422
            ) from None
        source = "replacement"
    status = consumable_status(
        today=as_of,
        stock=consumable.stock_quantity,
        next_check=next_check,
        required_quantity=row.quantity_per_replacement,
    )
    return ApplianceConsumableResponse(
        **_values(row, ApplianceConsumableFields),
        **{
            name: getattr(row, name)
            for name in (
                "id",
                "household_id",
                "version",
                "created_by_member_id",
                "updated_by_member_id",
                "created_at",
                "updated_at",
                "appliance_id",
                "consumable_id",
            )
        },
        last_replacement_id=None if latest is None else latest.id,
        last_replaced_on=last,
        next_check_on=next_check,
        next_check_source=source,
        stock_quantity=consumable.stock_quantity,
        stock_version=consumable.version,
        as_of=as_of,
        replacement_due=status.replacement_due,
        purchase_needed=status.purchase_needed,
        low_stock=consumable.stock_quantity <= consumable.low_stock_threshold,
    )


def _get_link_response(session, principal, row):
    stock = scoped_entity(session, Consumable, row.consumable_id, principal)
    latest = _latest_replacements(session, principal, [row.id])
    return _link_response(row, stock, latest.get(row.id), today())


def create_appliance_consumable(session, principal, payload):
    lock_asset_scope(session, principal)
    stock = scoped_entity(session, Consumable, payload.consumable_id, principal, for_update=True)
    appliance = scoped_entity(session, Appliance, payload.appliance_id, principal, for_update=True)
    _active(stock, "consumable")
    _active(appliance, "appliance")
    if (
        session.scalar(
            select(ApplianceConsumable.id).where(
                ApplianceConsumable.household_id == principal.household_id,
                ApplianceConsumable.appliance_id == appliance.id,
                ApplianceConsumable.consumable_id == stock.id,
            )
        )
        is not None
    ):
        raise DomainError(
            "APPLIANCE_CONSUMABLE_EXISTS",
            "이미 연결된 소모품입니다. 기존 연결을 확인해 주세요.",
            409,
        )
    row = ApplianceConsumable(**payload.model_dump(), **_actors(principal))
    session.add(row)
    session.flush()
    _audit(session, principal, row, "appliance_consumable", "create", payload.model_fields_set)
    return _finish(session, _link_response(row, stock, None, today()))


def get_appliance_consumable(session, principal, link_id):
    # Reads span stock and surviving history. The shared writer lock gives one coherent view.
    lock_asset_scope(session, principal)
    row = scoped_entity(session, ApplianceConsumable, link_id, principal)
    return _finish(session, _get_link_response(session, principal, row))


def update_appliance_consumable(session, principal, link_id, payload, if_match):
    lock_asset_scope(session, principal)
    row = scoped_entity(session, ApplianceConsumable, link_id, principal, for_update=True)
    require_version(row, if_match)
    candidate = _candidate(row, ApplianceConsumableFields, payload)
    if candidate.active:
        _active(scoped_entity(session, Consumable, row.consumable_id, principal), "consumable")
        _active(scoped_entity(session, Appliance, row.appliance_id, principal), "appliance")
    before = _touch(row, principal)
    _assign(row, candidate.model_dump())
    session.flush()
    result = _get_link_response(session, principal, row)
    _audit(
        session, principal, row, "appliance_consumable", "update", payload.model_fields_set, before
    )
    return _finish(session, result)


def _link_page(
    session,
    principal,
    *,
    appliance_id=None,
    consumable_id=None,
    active=None,
    cursor=None,
    limit=50,
    usable_only=False,
):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise DomainError("INVALID_PAGE_SIZE", "목록 크기를 확인해 주세요.", 422)
    if appliance_id is not None:
        scoped_entity(session, Appliance, appliance_id, principal)
    if consumable_id is not None:
        scoped_entity(session, Consumable, consumable_id, principal)
    query = (
        select(ApplianceConsumable, Appliance, Consumable)
        .join(
            Appliance,
            (Appliance.household_id == ApplianceConsumable.household_id)
            & (Appliance.id == ApplianceConsumable.appliance_id),
        )
        .join(
            Consumable,
            (Consumable.household_id == ApplianceConsumable.household_id)
            & (Consumable.id == ApplianceConsumable.consumable_id),
        )
        .where(ApplianceConsumable.household_id == principal.household_id)
    )
    if appliance_id is not None:
        query = query.where(ApplianceConsumable.appliance_id == appliance_id)
    if consumable_id is not None:
        query = query.where(ApplianceConsumable.consumable_id == consumable_id)
    if active is not None:
        query = query.where(ApplianceConsumable.active == active)
    if usable_only:
        query = query.where(
            ApplianceConsumable.active.is_(True),
            Appliance.ended_on.is_(None),
            Consumable.ended_on.is_(None),
        )
    if cursor is not None:
        query = query.where(ApplianceConsumable.id < cursor)
    rows = list(session.execute(query.order_by(ApplianceConsumable.id.desc()).limit(limit + 1)))
    return rows[:limit], rows[limit - 1][0].id if len(rows) > limit else None


def list_appliance_consumables(session, principal, **query):
    lock_asset_scope(session, principal)
    rows, cursor = _link_page(session, principal, **query)
    latest = _latest_replacements(session, principal, [row[0].id for row in rows])
    current = today()
    result = ApplianceConsumableListResponse(
        items=[
            _link_response(link, stock, latest.get(link.id), current) for link, _, stock in rows
        ],
        next_cursor=cursor,
    )
    return _finish(session, result)


def homecare_status(session, principal, **query):
    lock_asset_scope(session, principal)
    current = today()  # No selected asset month, request date, or purchase date can replace this.
    rows, cursor = _link_page(session, principal, usable_only=True, **query)
    latest = _latest_replacements(session, principal, [row[0].id for row in rows])
    items = [
        HomecareStatusItem(
            **_link_response(link, stock, latest.get(link.id), current).model_dump(),
            appliance_name=appliance.name,
            appliance_location=appliance.location,
            consumable_name=stock.name,
            sku_or_model=stock.sku_or_model,
            unit=stock.unit,
            low_stock_threshold=stock.low_stock_threshold,
        )
        for link, appliance, stock in rows
    ]
    return _finish(session, HomecareStatusResponse(as_of=current, items=items, next_cursor=cursor))


def _apply_movement(
    session,
    principal,
    stock,
    *,
    kind,
    delta,
    occurred_on,
    unit_cost=None,
    purchase_url=None,
    reversal_of=None,
    reason=None,
    note=None,
):
    quantity = stock.stock_quantity + delta
    if quantity < 0:
        raise DomainError(
            "INSUFFICIENT_STOCK", "공용 재고가 부족합니다. 현재 재고를 확인해 주세요.", 409
        )
    if quantity > MAX_QUANTITY:
        raise DomainError("STOCK_LIMIT_EXCEEDED", "허용 재고 수량을 초과합니다.", 422)
    before = _touch(stock, principal)
    stock.stock_quantity = quantity
    session.flush()
    movement = StockMovement(
        household_id=principal.household_id,
        consumable_id=stock.id,
        created_by_member_id=principal.member_id,
        kind=kind,
        quantity_delta=delta,
        occurred_on=occurred_on,
        unit_cost_krw=None if unit_cost is None else Decimal(unit_cost),
        purchase_url=purchase_url,
        reversal_of=reversal_of,
        reason=reason,
        note=note,
        stock_version=stock.version,
    )
    session.add(movement)
    session.flush()
    _audit(session, principal, stock, "consumable", "update", {"stock_quantity"}, before)
    _audit(
        session,
        principal,
        movement,
        "stock_movement",
        "create",
        {"kind", "quantity_delta", "occurred_on", "reversal_of"},
        after=stock.version,
    )
    return movement


def _stock_result(session, principal, result):
    movement = scoped_entity(session, StockMovement, result.resource_id, principal)
    if (
        result.resource_type != "stock_movement"
        or movement.stock_version != result.resource_version
    ):
        raise DomainError("OPERATION_IN_PROGRESS", "저장 결과를 다시 확인해 주세요.", 409)
    replacement_id = session.scalar(
        select(ConsumableReplacement.id).where(
            ConsumableReplacement.household_id == principal.household_id,
            ConsumableReplacement.stock_movement_id == movement.id,
        )
    )
    response = StockMutationReference(
        id=movement.id,
        consumable_id=movement.consumable_id,
        stock_version=movement.stock_version,
        replacement_id=replacement_id,
    )
    return _finish(session, response)


def _stock_command(
    session,
    principal,
    operation,
    target_id,
    payload,
    if_match,
    key,
    execute,
    *,
    scope,
    parent_id=None,
):
    # Shared lock order: household -> idempotency -> consumable -> appliance/link/fact.
    lock_asset_scope(session, principal)
    # Authorization and parent binding also run on replay, while active/version checks
    # belong to the first execution and cannot invalidate an immutable retry receipt.
    scope()
    result = run_idempotent(
        session,
        principal,
        operation,
        key,
        {
            "id": str(target_id),
            "parent_id": None if parent_id is None else str(parent_id),
            "if_match": if_match,
            "body": payload.model_dump(mode="json"),
        },
        execute,
    )
    return _stock_result(session, principal, result)


def create_stock_movement(session, principal, consumable_id, payload, if_match, key):
    def execute():
        stock = scoped_entity(session, Consumable, consumable_id, principal, for_update=True)
        require_version(stock, if_match)
        _active(stock, "consumable")
        _actual_dates(payload.occurred_on)
        movement = _apply_movement(
            session,
            principal,
            stock,
            kind=payload.kind,
            delta=payload.quantity_delta,
            occurred_on=payload.occurred_on,
            unit_cost=payload.unit_cost_krw,
            purchase_url=payload.purchase_url,
            reason=payload.reason,
            note=payload.note,
        )
        return IdempotentResult(movement.id, "stock_movement", movement.stock_version, 201)

    return _stock_command(
        session,
        principal,
        "homecare.stock.create",
        consumable_id,
        payload,
        if_match,
        key,
        execute,
        scope=lambda: scoped_entity(session, Consumable, consumable_id, principal),
    )


def _clear_override(session, principal, link):
    cleared = link.next_check_override
    if cleared is None:
        return None, None
    before = _touch(link, principal)
    link.next_check_override = None
    session.flush()
    _audit(
        session, principal, link, "appliance_consumable", "update", {"next_check_override"}, before
    )
    return cleared, link.version


def _restore_override(session, principal, link_id, replacement):
    if replacement.cleared_link_version is None:
        return
    link = scoped_entity(session, ApplianceConsumable, link_id, principal, for_update=True)
    if link.version != replacement.cleared_link_version:
        return
    before = _touch(link, principal)
    link.next_check_override = replacement.cleared_next_check_override
    session.flush()
    _audit(
        session, principal, link, "appliance_consumable", "update", {"next_check_override"}, before
    )


def create_replacement(session, principal, link_id, payload, if_match, key):
    def execute():
        link = scoped_entity(session, ApplianceConsumable, link_id, principal)
        stock = scoped_entity(session, Consumable, link.consumable_id, principal, for_update=True)
        appliance = scoped_entity(session, Appliance, link.appliance_id, principal, for_update=True)
        link = scoped_entity(session, ApplianceConsumable, link_id, principal, for_update=True)
        _active(stock, "consumable")
        _active(appliance, "appliance")
        _active(link, "link")
        _actual_dates(payload.replaced_on)
        # A concurrent spend reports the now-insufficient shared stock. A stale edit with
        # sufficient stock still gets VERSION_CONFLICT; neither path can change inventory.
        if stock.stock_quantity < payload.quantity:
            raise DomainError(
                "INSUFFICIENT_STOCK", "공용 재고가 부족합니다. 현재 재고를 확인해 주세요.", 409
            )
        require_version(stock, if_match)
        require_version(link, f'"{payload.link_version}"')
        movement = _apply_movement(
            session,
            principal,
            stock,
            kind="replacement",
            delta=-payload.quantity,
            occurred_on=payload.replaced_on,
            note=payload.note,
        )
        # Clear before the insert: the database checks the recorded version against the link.
        cleared_on, cleared_version = (
            _clear_override(session, principal, link)
            if payload.clear_next_check_override
            else (None, None)
        )
        replacement = ConsumableReplacement(
            household_id=principal.household_id,
            created_by_member_id=principal.member_id,
            appliance_consumable_id=link.id,
            consumable_id=stock.id,
            stock_movement_id=movement.id,
            replaced_on=payload.replaced_on,
            quantity=payload.quantity,
            note=payload.note,
            cleared_next_check_override=cleared_on,
            cleared_link_version=cleared_version,
        )
        session.add(replacement)
        session.flush()
        _audit(
            session,
            principal,
            replacement,
            "consumable_replacement",
            "create",
            {"replaced_on", "quantity", "stock_movement_id"},
        )
        return IdempotentResult(movement.id, "stock_movement", movement.stock_version, 201)

    return _stock_command(
        session,
        principal,
        "homecare.replacement.create",
        link_id,
        payload,
        if_match,
        key,
        execute,
        scope=lambda: scoped_entity(session, ApplianceConsumable, link_id, principal),
    )


def _reverse(session, principal, stock, original, payload):
    if original.kind == "reversal":
        raise DomainError("INVALID_STOCK_REVERSAL", "취소 기록을 다시 취소할 수 없습니다.", 422)
    if (
        session.scalar(
            select(StockMovement.id).where(
                StockMovement.household_id == principal.household_id,
                StockMovement.reversal_of == original.id,
            )
        )
        is not None
    ):
        raise DomainError("STOCK_MOVEMENT_ALREADY_REVERSED", "이미 취소된 재고 기록입니다.", 409)
    _actual_dates(payload.occurred_on)
    if payload.occurred_on < original.occurred_on:
        raise DomainError(
            "INVALID_HOMECARE_DATE", "취소일은 원본 기록일보다 빠를 수 없습니다.", 422
        )
    movement = _apply_movement(
        session,
        principal,
        stock,
        kind="reversal",
        delta=-original.quantity_delta,
        occurred_on=payload.occurred_on,
        reversal_of=original.id,
        reason=payload.reason,
    )
    return IdempotentResult(movement.id, "stock_movement", movement.stock_version, 200)


def cancel_stock_movement(session, principal, consumable_id, movement_id, payload, if_match, key):
    def execute():
        stock = scoped_entity(session, Consumable, consumable_id, principal, for_update=True)
        original = scoped_entity(session, StockMovement, movement_id, principal)
        if original.consumable_id != stock.id:
            raise DomainError("NOT_FOUND", "요청한 재고 기록을 찾을 수 없습니다.", 404)
        require_version(stock, if_match)
        if original.kind == "replacement":
            raise DomainError(
                "REPLACEMENT_CANCEL_REQUIRED", "기기별 교체 기록에서 취소해 주세요.", 409
            )
        return _reverse(session, principal, stock, original, payload)

    def scope():
        scoped_entity(session, Consumable, consumable_id, principal)
        original = scoped_entity(session, StockMovement, movement_id, principal)
        if original.consumable_id != consumable_id:
            raise DomainError("NOT_FOUND", "요청한 재고 기록을 찾을 수 없습니다.", 404)

    return _stock_command(
        session,
        principal,
        "homecare.stock.cancel",
        movement_id,
        payload,
        if_match,
        key,
        execute,
        scope=scope,
        parent_id=consumable_id,
    )


def cancel_replacement(session, principal, link_id, replacement_id, payload, if_match, key):
    def execute():
        link = scoped_entity(session, ApplianceConsumable, link_id, principal)
        stock = scoped_entity(session, Consumable, link.consumable_id, principal, for_update=True)
        replacement = scoped_entity(session, ConsumableReplacement, replacement_id, principal)
        if replacement.appliance_consumable_id != link.id:
            raise DomainError("NOT_FOUND", "요청한 교체 기록을 찾을 수 없습니다.", 404)
        require_version(stock, if_match)
        original = scoped_entity(session, StockMovement, replacement.stock_movement_id, principal)
        result = _reverse(session, principal, stock, original, payload)
        # Restore only the override this replacement cleared, and only while the link is still
        # at the version that clear produced; any later link edit stays the current choice.
        _restore_override(session, principal, link.id, replacement)
        return result

    def scope():
        scoped_entity(session, ApplianceConsumable, link_id, principal)
        replacement = scoped_entity(session, ConsumableReplacement, replacement_id, principal)
        if replacement.appliance_consumable_id != link_id:
            raise DomainError("NOT_FOUND", "요청한 교체 기록을 찾을 수 없습니다.", 404)

    return _stock_command(
        session,
        principal,
        "homecare.replacement.cancel",
        replacement_id,
        payload,
        if_match,
        key,
        execute,
        scope=scope,
        parent_id=link_id,
    )


def _movement_query(principal):
    reversal = aliased(StockMovement)
    return (
        select(StockMovement, reversal.id)
        .outerjoin(
            reversal,
            (reversal.household_id == StockMovement.household_id)
            & (reversal.reversal_of == StockMovement.id),
        )
        .where(StockMovement.household_id == principal.household_id)
    )


def _movement_response(row, reversed_by):
    return StockMovementResponse(
        **{
            name: getattr(row, name)
            for name in StockMovementResponse.model_fields
            if name not in {"unit_cost_krw", "reversed_by"}
        },
        unit_cost_krw=None if row.unit_cost_krw is None else krw_string(row.unit_cost_krw),
        reversed_by=reversed_by,
    )


def list_stock_movements(session, principal, consumable_id, *, cursor=None, limit=50):
    scoped_entity(session, Consumable, consumable_id, principal)
    query = _movement_query(principal).where(StockMovement.consumable_id == consumable_id)
    if cursor is not None:
        query = query.where(StockMovement.id < cursor)
    rows = list(session.execute(query.order_by(StockMovement.id.desc()).limit(limit + 1)))
    return _finish(
        session,
        StockMovementListResponse(
            items=[_movement_response(*row) for row in rows[:limit]],
            next_cursor=rows[limit - 1][0].id if len(rows) > limit else None,
        ),
    )


def get_stock_movement(session, principal, consumable_id, movement_id):
    scoped_entity(session, Consumable, consumable_id, principal)
    row = session.execute(
        _movement_query(principal).where(
            StockMovement.id == movement_id, StockMovement.consumable_id == consumable_id
        )
    ).one_or_none()
    if row is None:
        raise DomainError("NOT_FOUND", "요청한 재고 기록을 찾을 수 없습니다.", 404)
    return _finish(session, _movement_response(*row))


def _replacement_query(principal):
    reversal = aliased(StockMovement)
    return (
        select(ConsumableReplacement, reversal.id)
        .outerjoin(
            reversal,
            (reversal.household_id == ConsumableReplacement.household_id)
            & (reversal.reversal_of == ConsumableReplacement.stock_movement_id),
        )
        .where(ConsumableReplacement.household_id == principal.household_id)
    )


def _replacement_response(row, cancellation):
    return ReplacementResponse(
        **{
            name: getattr(row, name)
            for name in ReplacementResponse.model_fields
            if name != "cancelled_by_movement_id"
        },
        cancelled_by_movement_id=cancellation,
    )


def list_replacements(session, principal, link_id, *, cursor=None, limit=50):
    scoped_entity(session, ApplianceConsumable, link_id, principal)
    query = _replacement_query(principal).where(
        ConsumableReplacement.appliance_consumable_id == link_id
    )
    if cursor is not None:
        query = query.where(ConsumableReplacement.id < cursor)
    rows = list(session.execute(query.order_by(ConsumableReplacement.id.desc()).limit(limit + 1)))
    return _finish(
        session,
        ReplacementListResponse(
            items=[_replacement_response(*row) for row in rows[:limit]],
            next_cursor=rows[limit - 1][0].id if len(rows) > limit else None,
        ),
    )


def get_replacement(session, principal, link_id, replacement_id):
    scoped_entity(session, ApplianceConsumable, link_id, principal)
    row = session.execute(
        _replacement_query(principal).where(
            ConsumableReplacement.id == replacement_id,
            ConsumableReplacement.appliance_consumable_id == link_id,
        )
    ).one_or_none()
    if row is None:
        raise DomainError("NOT_FOUND", "요청한 교체 기록을 찾을 수 없습니다.", 404)
    return _finish(session, _replacement_response(*row))
