"""Shared purchase intentions; only an atomic receipt changes physical stock."""

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import case, exists, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import aliased

from sallimbook.assets.locking import lock_asset_scope
from sallimbook.core.authorization import require_version, scoped_entity
from sallimbook.core.errors import DomainError
from sallimbook.core.idempotency import IdempotentResult, run_idempotent
from sallimbook.core.name_search import search_names
from sallimbook.core.pagination import keyset_page
from sallimbook.homecare import service as inventory
from sallimbook.homecare.models import (
    Appliance,
    ApplianceConsumable,
    Consumable,
    ConsumableOrder,
    StockMovement,
)
from sallimbook.homecare.order_schemas import (
    ConsumableOrderFields,
    ConsumableOrderListResponse,
    ConsumableOrderReference,
    ConsumableOrderResponse,
    PurchaseDemand,
    PurchasePlanItem,
    PurchasePlanResponse,
)
from sallimbook.homecare.purchase_calculations import projected_replacements, purchase_quantities
from sallimbook.homecare.schemas import EntityResponse


def _state(row, allowed):
    if row.state not in allowed:
        raise DomainError(
            "CONSUMABLE_ORDER_STATE_CONFLICT", "현재 주문 상태를 확인해 주세요.", 409, row.version
        )


def _response(row, stock, reversed_by=None):
    return ConsumableOrderResponse(
        **inventory._values(row, ConsumableOrderFields),
        **inventory._values(row, EntityResponse),
        consumable_id=row.consumable_id,
        consumable_name=stock.name,
        unit=stock.unit,
        sku_or_model=stock.sku_or_model,
        state=row.state,
        ordered_on=row.ordered_on,
        ordered_by_member_id=row.ordered_by_member_id,
        received_on=row.received_on,
        received_by_member_id=row.received_by_member_id,
        stock_movement_id=row.stock_movement_id,
        receipt_reversed_by=reversed_by,
        cancel_reason=row.cancel_reason,
    )


def _query(principal):
    reversal = aliased(StockMovement)
    return (
        select(ConsumableOrder, Consumable, reversal.id)
        .join(
            Consumable,
            (Consumable.household_id == ConsumableOrder.household_id)
            & (Consumable.id == ConsumableOrder.consumable_id),
        )
        .outerjoin(
            reversal,
            (reversal.household_id == ConsumableOrder.household_id)
            & (reversal.reversal_of == ConsumableOrder.stock_movement_id),
        )
        .where(ConsumableOrder.household_id == principal.household_id)
    )


def get_order(session, principal, order_id):
    lock_asset_scope(session, principal)
    scoped_entity(session, ConsumableOrder, order_id, principal)
    row, stock, reversed_by = session.execute(
        _query(principal).where(ConsumableOrder.id == order_id)
    ).one()
    return _response(row, stock, reversed_by)


def list_orders(
    session, principal, *, state="open", consumable_id=None, q=None, cursor=None, limit=50
):
    lock_asset_scope(session, principal)
    query = _query(principal)
    if state == "open":
        query = query.where(ConsumableOrder.state.in_(("planned", "ordered")))
    elif state != "all":
        query = query.where(ConsumableOrder.state == state)
    if consumable_id is not None:
        scoped_entity(session, Consumable, consumable_id, principal)
        query = query.where(ConsumableOrder.consumable_id == consumable_id)
    query = search_names(query, q, Consumable.name, Consumable.sku_or_model)
    rows, following = keyset_page(
        session,
        query,
        model=ConsumableOrder,
        household_id=principal.household_id,
        keys=(ConsumableOrder.created_at,),
        cursor=cursor,
        limit=limit,
        scalars=False,
        cursor_of=lambda row: row[0].id,
        cursor_where=()
        if consumable_id is None
        else (ConsumableOrder.consumable_id == consumable_id,),
    )
    return ConsumableOrderListResponse(
        items=[_response(*row) for row in rows], next_cursor=following
    )


def _reference(session, principal, result):
    row = scoped_entity(session, ConsumableOrder, result.resource_id, principal)
    if result.resource_type != "consumable_order" or result.resource_version > row.version:
        raise DomainError("OPERATION_IN_PROGRESS", "저장 결과를 다시 확인해 주세요.", 409)
    # Do not render current mutable details as the original outcome of an old command.
    return inventory._finish(
        session, ConsumableOrderReference(id=result.resource_id, version=result.resource_version)
    )


def create_order(session, principal, payload, key):
    lock_asset_scope(session, principal)
    scoped_entity(session, Consumable, payload.consumable_id, principal)

    def execute():
        stock = scoped_entity(
            session, Consumable, payload.consumable_id, principal, for_update=True
        )
        inventory._active(stock, "consumable")
        values = payload.model_dump()
        if values["unit_cost_krw"] is not None:
            values["unit_cost_krw"] = Decimal(values["unit_cost_krw"])
        row = ConsumableOrder(**inventory._actors(principal), **values, state="planned")
        session.add(row)
        session.flush()
        inventory._audit(
            session,
            principal,
            row,
            "consumable_order",
            "create",
            {"consumable_id", "quantity", "state"},
        )
        return IdempotentResult(row.id, "consumable_order", row.version)

    result = run_idempotent(
        session, principal, "homecare.order.create", key, payload.model_dump(mode="json"), execute
    )
    return _reference(session, principal, result)


def update_order(session, principal, order_id, payload, if_match):
    lock_asset_scope(session, principal)
    initial = scoped_entity(session, ConsumableOrder, order_id, principal)
    stock = scoped_entity(session, Consumable, initial.consumable_id, principal, for_update=True)
    row = scoped_entity(session, ConsumableOrder, order_id, principal, for_update=True)
    require_version(row, if_match)
    _state(row, {"planned", "ordered"})
    inventory._active(stock, "consumable")
    candidate = inventory._candidate(row, ConsumableOrderFields, payload)
    before = inventory._touch(row, principal)
    inventory._assign(row, candidate.model_dump())
    session.flush()
    inventory._audit(
        session, principal, row, "consumable_order", "update", payload.model_fields_set, before
    )
    return inventory._finish(session, _response(row, stock))


def order_command(session, principal, order_id, payload, if_match, key, action):
    lock_asset_scope(session, principal)
    initial = scoped_entity(session, ConsumableOrder, order_id, principal)
    # Always check the shared SKU, including replays after its state changes.
    scoped_entity(session, Consumable, initial.consumable_id, principal)

    def execute():
        stock = scoped_entity(
            session, Consumable, initial.consumable_id, principal, for_update=True
        )
        row = scoped_entity(session, ConsumableOrder, order_id, principal, for_update=True)
        require_version(row, if_match)
        before = row.version
        if action == "submit":
            _state(row, {"planned"})
            inventory._active(stock, "consumable")
            inventory._actual_dates(payload.ordered_on)
            row.state, row.ordered_on, row.ordered_by_member_id = (
                "ordered",
                payload.ordered_on,
                principal.member_id,
            )
            fields = {"state", "ordered_on", "ordered_by_member_id"}
        elif action == "cancel":
            _state(row, {"planned", "ordered"})
            row.state, row.cancel_reason = "cancelled", payload.reason
            fields = {"state", "cancel_reason"}
        elif action == "receive":
            _state(row, {"ordered"})
            inventory._active(stock, "consumable")
            require_version(stock, f'"{payload.stock_version}"')
            inventory._actual_dates(payload.received_on)
            if payload.received_on < row.ordered_on:
                raise DomainError(
                    "INVALID_HOMECARE_DATE", "입고일은 주문일보다 빠를 수 없습니다.", 422
                )
            movement = inventory._apply_movement(
                session,
                principal,
                stock,
                kind="receipt",
                delta=row.quantity,
                occurred_on=payload.received_on,
                unit_cost=row.unit_cost_krw,
                purchase_url=row.purchase_url,
                note=row.note,
            )
            row.state, row.received_on, row.received_by_member_id = (
                "received",
                payload.received_on,
                principal.member_id,
            )
            row.stock_movement_id = movement.id
            fields = {"state", "received_on", "received_by_member_id", "stock_movement_id"}
        else:
            raise ValueError("Unknown order command")
        inventory._touch(row, principal)
        session.flush()
        inventory._audit(session, principal, row, "consumable_order", "update", fields, before)
        return IdempotentResult(row.id, "consumable_order", row.version, 200)

    result = run_idempotent(
        session,
        principal,
        f"homecare.order.{action}",
        key,
        {"id": str(order_id), "if_match": if_match, "body": payload.model_dump(mode="json")},
        execute,
    )
    return _reference(session, principal, result)


def purchase_plan(session, principal, *, through=None, q=None, cursor=None, limit=50):
    lock_asset_scope(session, principal)
    as_of = inventory.today()
    through = as_of if through is None else through
    if not 0 <= (through - as_of).days <= 365:
        raise DomainError(
            "INVALID_HOMECARE_INPUT",
            "구매 계획은 오늘부터 최대 365일 뒤까지 확인할 수 있습니다.",
            422,
        )
    stocks, following = inventory._page(
        session,
        principal,
        search_names(
            select(Consumable).where(
                Consumable.household_id == principal.household_id, Consumable.ended_on.is_(None)
            ),
            q,
            Consumable.name,
            Consumable.sku_or_model,
        ),
        Consumable,
        cursor,
        limit,
    )
    stock_ids = [stock.id for stock in stocks]
    links = (
        list(
            session.execute(
                select(ApplianceConsumable, Appliance)
                .join(
                    Appliance,
                    (Appliance.household_id == ApplianceConsumable.household_id)
                    & (Appliance.id == ApplianceConsumable.appliance_id),
                )
                .where(
                    ApplianceConsumable.household_id == principal.household_id,
                    ApplianceConsumable.consumable_id.in_(stock_ids),
                    ApplianceConsumable.active.is_(True),
                    Appliance.ended_on.is_(None),
                )
                .order_by(Appliance.name, ApplianceConsumable.id)
            )
        )
        if stocks
        else []
    )
    latest = inventory._latest_replacements(session, principal, [link.id for link, _ in links])
    by_stock = defaultdict(list)
    for link, appliance in links:
        by_stock[link.consumable_id].append((link, appliance))
    pending = (
        {
            row[0]: row[1:]
            for row in session.execute(
                select(
                    ConsumableOrder.consumable_id,
                    func.sum(
                        case(
                            (ConsumableOrder.state == "planned", ConsumableOrder.quantity), else_=0
                        )
                    ),
                    func.sum(
                        case(
                            (ConsumableOrder.state == "ordered", ConsumableOrder.quantity), else_=0
                        )
                    ),
                    func.count(ConsumableOrder.id),
                )
                .where(
                    ConsumableOrder.household_id == principal.household_id,
                    ConsumableOrder.consumable_id.in_(stock_ids),
                    ConsumableOrder.state.in_(("planned", "ordered")),
                )
                .group_by(ConsumableOrder.consumable_id)
            )
        }
        if stocks
        else {}
    )
    reversal = aliased(StockMovement)
    receipts = (
        {
            row.consumable_id: row
            for row in session.scalars(
                select(StockMovement)
                .where(
                    StockMovement.household_id == principal.household_id,
                    StockMovement.consumable_id.in_(stock_ids),
                    StockMovement.kind == "receipt",
                    ~exists(
                        select(reversal.id).where(
                            reversal.household_id == principal.household_id,
                            reversal.reversal_of == StockMovement.id,
                        )
                    ),
                )
                .ext(distinct_on(StockMovement.consumable_id))
                .order_by(
                    StockMovement.consumable_id,
                    StockMovement.occurred_on.desc(),
                    StockMovement.created_at.desc(),
                    StockMovement.id.desc(),
                )
            )
        }
        if stocks
        else {}
    )
    items = []
    for stock in stocks:
        demands = []
        for link, appliance in by_stock[stock.id]:
            current = inventory._link_response(link, stock, latest.get(link.id), as_of)
            count = projected_replacements(
                current.next_check_on, as_of, through, link.interval_unit, link.interval_count
            )
            demands.append(
                PurchaseDemand(
                    link_id=link.id,
                    appliance_id=appliance.id,
                    appliance_name=appliance.name,
                    next_check_on=current.next_check_on,
                    replacement_count=count,
                    quantity=None if count is None else count * link.quantity_per_replacement,
                )
            )
        planned, ordered, open_count = (int(value) for value in pending.get(stock.id, (0, 0, 0)))
        quantities = purchase_quantities(
            [row.quantity for row in demands if row.quantity is not None],
            stock.stock_quantity,
            planned,
            ordered,
        )
        receipt = receipts.get(stock.id)
        items.append(
            PurchasePlanItem(
                consumable=inventory._consumable_response(stock),
                **quantities,
                planned_quantity=planned,
                ordered_quantity=ordered,
                open_order_count=open_count,
                unscheduled_link_count=sum(row.quantity is None for row in demands),
                demand_sources=demands[:20],
                additional_source_count=max(0, len(demands) - 20),
                last_receipt=None
                if receipt is None
                else inventory._movement_response(receipt, None),
            )
        )
    return PurchasePlanResponse(as_of=as_of, through=through, items=items, next_cursor=following)
