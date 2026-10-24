from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from sallimbook.assets.schemas import DateOnly
from sallimbook.cashflow.schemas import InputModel, Note, Reason
from sallimbook.core.types import KrwString
from sallimbook.homecare.purchase_calculations import MAX_AGGREGATE_QUANTITY
from sallimbook.homecare.schemas import (
    ConsumableResponse,
    EntityResponse,
    PositiveQuantity,
    PurchaseUrl,
    StockMovementResponse,
    Version,
    _patch,
)

type OrderState = Literal["planned", "ordered", "received", "cancelled"]
type OrderFilter = Literal["open", "planned", "ordered", "received", "cancelled", "all"]
AggregateQuantity = Annotated[int, Field(strict=True, ge=0, le=MAX_AGGREGATE_QUANTITY)]


class ConsumableOrderFields(InputModel):
    quantity: PositiveQuantity
    unit_cost_krw: KrwString | None = Field(default=None, repr=False)
    purchase_url: PurchaseUrl | None = None
    note: Note | None = Field(default=None, repr=False)


class ConsumableOrderCreate(ConsumableOrderFields):
    consumable_id: UUID


class ConsumableOrderPatch(InputModel):
    quantity: PositiveQuantity | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    unit_cost_krw: KrwString | None = Field(default=None, repr=False)
    purchase_url: PurchaseUrl | None = None
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def patch(self) -> Self:
        return _patch(self, {"quantity"})


class ConsumableOrderSubmit(InputModel):
    ordered_on: DateOnly


class ConsumableOrderReceive(InputModel):
    received_on: DateOnly
    stock_version: Version


class ConsumableOrderCancel(InputModel):
    reason: Reason = Field(repr=False)


class ConsumableOrderReference(BaseModel):
    """Immutable command receipt; read current details separately after any replay."""

    id: UUID
    version: Version


class ConsumableOrderResponse(ConsumableOrderFields, EntityResponse):
    consumable_id: UUID
    consumable_name: str
    unit: str
    sku_or_model: str | None
    state: OrderState
    ordered_on: DateOnly | None
    ordered_by_member_id: UUID | None
    received_on: DateOnly | None
    received_by_member_id: UUID | None
    stock_movement_id: UUID | None
    receipt_reversed_by: UUID | None
    cancel_reason: str | None = Field(repr=False)


class ConsumableOrderListResponse(BaseModel):
    items: list[ConsumableOrderResponse]
    next_cursor: UUID | None


class PurchaseDemand(BaseModel):
    link_id: UUID
    appliance_id: UUID
    appliance_name: str
    next_check_on: DateOnly | None
    replacement_count: AggregateQuantity | None
    quantity: AggregateQuantity | None


class PurchasePlanItem(BaseModel):
    consumable: ConsumableResponse
    demand_quantity: AggregateQuantity
    shortage_quantity: AggregateQuantity
    planned_quantity: AggregateQuantity
    ordered_quantity: AggregateQuantity
    additional_quantity: AggregateQuantity
    open_order_count: AggregateQuantity
    unscheduled_link_count: AggregateQuantity
    demand_sources: list[PurchaseDemand]
    additional_source_count: AggregateQuantity
    last_receipt: StockMovementResponse | None


class PurchasePlanResponse(BaseModel):
    as_of: DateOnly
    through: DateOnly
    items: list[PurchasePlanItem]
    next_cursor: UUID | None
