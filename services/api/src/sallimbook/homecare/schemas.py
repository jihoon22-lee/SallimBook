from datetime import datetime
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator
from pydantic.json_schema import SkipJsonSchema

from sallimbook.assets.schemas import DateOnly
from sallimbook.cashflow.schemas import InputModel, Note, Reason
from sallimbook.core.types import KrwString
from sallimbook.homecare.calculations import MAX_QUANTITY

Quantity = Annotated[int, Field(strict=True, ge=0, le=MAX_QUANTITY)]
PositiveQuantity = Annotated[int, Field(strict=True, ge=1, le=MAX_QUANTITY)]
Version = Annotated[int, Field(strict=True, ge=1, le=9_007_199_254_740_991)]
Title = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)
]
Unit = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=40)
]
type IntervalUnit = Literal["manual", "days", "months"]
type RecordStatus = Literal["active", "ended"]
type StatusFilter = Literal["active", "ended", "all"]
type MovementKind = Literal[
    "receipt", "replacement", "return_in", "return_out", "adjustment", "reversal"
]


def _nonzero(value: int) -> int:
    if value == 0:
        raise ValueError("A movement must change stock")
    return value


Delta = Annotated[
    int, Field(strict=True, ge=-MAX_QUANTITY, le=MAX_QUANTITY), AfterValidator(_nonzero)
]


def _purchase_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(c.isspace() or ord(c) < 32 for c in value)
        ):
            raise ValueError("Use an HTTPS purchase link without credentials")
        _ = parsed.port
    except ValueError:
        raise ValueError("Use an HTTPS purchase link without credentials") from None
    return value


PurchaseUrl = Annotated[
    str, StringConstraints(strict=True, max_length=2048), AfterValidator(_purchase_url)
]


def _patch(value, required):
    supplied = value.model_fields_set
    if not supplied or any(getattr(value, field) is None for field in supplied & required):
        raise ValueError("Supply at least one valid editable field")
    return value


class ApplianceInput(InputModel):
    name: Title
    manufacturer: Title | None = None
    model: Title | None = None
    location: Title | None = None
    purchased_on: DateOnly | None = None
    purchase_price_krw: KrwString | None = Field(default=None, repr=False)
    seller: Title | None = None
    warranty_until: DateOnly | None = None
    ended_on: DateOnly | None = None
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if (
            self.purchased_on is not None
            and self.ended_on is not None
            and self.ended_on < self.purchased_on
        ):
            raise ValueError("An appliance cannot end before purchase")
        return self


class AppliancePatch(InputModel):
    name: Title | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    manufacturer: Title | None = None
    model: Title | None = None
    location: Title | None = None
    purchased_on: DateOnly | None = None
    purchase_price_krw: KrwString | None = Field(default=None, repr=False)
    seller: Title | None = None
    warranty_until: DateOnly | None = None
    ended_on: DateOnly | None = None
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def patch(self) -> Self:
        return _patch(self, {"name"})


class ConsumableInput(InputModel):
    name: Title
    sku_or_model: Title | None = None
    unit: Unit
    low_stock_threshold: Quantity = 0
    ended_on: DateOnly | None = None
    note: Note | None = Field(default=None, repr=False)


class ConsumablePatch(InputModel):
    name: Title | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    sku_or_model: Title | None = None
    unit: Unit | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    low_stock_threshold: Quantity | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    ended_on: DateOnly | None = None
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def patch(self) -> Self:
        return _patch(self, {"name", "unit", "low_stock_threshold"})


class ApplianceConsumableFields(InputModel):
    interval_unit: IntervalUnit = "manual"
    interval_count: Annotated[int, Field(strict=True, ge=1, le=3650)] | None = None
    quantity_per_replacement: PositiveQuantity = 1
    next_check_override: DateOnly | None = None
    active: bool = Field(default=True, strict=True)
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.interval_unit == "manual":
            if self.interval_count is not None:
                raise ValueError("A manual check does not have an automatic interval")
        elif (
            self.interval_count is None
            or self.interval_unit == "months"
            and self.interval_count > 120
        ):
            raise ValueError("Specify a bounded interval for the chosen unit")
        return self


class ApplianceConsumableCreate(ApplianceConsumableFields):
    appliance_id: UUID
    consumable_id: UUID


class ApplianceConsumablePatch(InputModel):
    interval_unit: IntervalUnit | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    interval_count: Annotated[int, Field(strict=True, ge=1, le=3650)] | None = None
    quantity_per_replacement: PositiveQuantity | SkipJsonSchema[None] = Field(
        default_factory=lambda: None
    )
    next_check_override: DateOnly | None = None
    active: Annotated[bool, Field(strict=True)] | SkipJsonSchema[None] = Field(
        default_factory=lambda: None
    )
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def patch(self) -> Self:
        return _patch(self, {"interval_unit", "quantity_per_replacement", "active"})


class StockMovementCreate(InputModel):
    kind: Literal["receipt", "return_in", "return_out", "adjustment"]
    quantity_delta: Delta
    occurred_on: DateOnly
    unit_cost_krw: KrwString | None = Field(default=None, repr=False)
    purchase_url: PurchaseUrl | None = None
    reason: Reason | None = Field(default=None, repr=False)
    note: Note | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def direction(self) -> Self:
        if self.kind in {"receipt", "return_in"} and self.quantity_delta < 0:
            raise ValueError("Incoming stock must have a positive quantity")
        if self.kind == "return_out" and self.quantity_delta > 0:
            raise ValueError("Outgoing stock must have a negative quantity")
        if self.kind == "adjustment" and self.reason is None:
            raise ValueError("A stock adjustment needs a reason")
        return self


class ReplacementCreate(InputModel):
    replaced_on: DateOnly
    quantity: PositiveQuantity
    link_version: Version
    note: Note | None = Field(default=None, repr=False)


class StockCancellation(InputModel):
    occurred_on: DateOnly
    reason: Reason = Field(repr=False)


class EntityResponse(BaseModel):
    id: UUID
    household_id: UUID
    version: int
    created_by_member_id: UUID
    updated_by_member_id: UUID
    created_at: datetime
    updated_at: datetime


class ApplianceResponse(ApplianceInput, EntityResponse):
    status: RecordStatus
    as_of: DateOnly
    warranty_status: Literal["unknown", "active", "expired"]


class ApplianceListResponse(BaseModel):
    items: list[ApplianceResponse]
    next_cursor: UUID | None


class ConsumableResponse(ConsumableInput, EntityResponse):
    status: RecordStatus
    stock_quantity: Quantity
    low_stock: bool


class ConsumableListResponse(BaseModel):
    items: list[ConsumableResponse]
    next_cursor: UUID | None


class ApplianceConsumableResponse(ApplianceConsumableFields, EntityResponse):
    appliance_id: UUID
    consumable_id: UUID
    last_replacement_id: UUID | None
    last_replaced_on: DateOnly | None
    next_check_on: DateOnly | None
    stock_quantity: Quantity
    stock_version: Version
    as_of: DateOnly
    replacement_due: bool | None
    purchase_needed: bool
    low_stock: bool


class ApplianceConsumableListResponse(BaseModel):
    items: list[ApplianceConsumableResponse]
    next_cursor: UUID | None


class StockMutationReference(BaseModel):
    """Immutable outcome; stock_version is the version at the original mutation."""

    id: UUID
    consumable_id: UUID
    stock_version: Version
    replacement_id: UUID | None


class StockMovementResponse(BaseModel):
    id: UUID
    household_id: UUID
    consumable_id: UUID
    kind: MovementKind
    quantity_delta: Delta
    occurred_on: DateOnly
    unit_cost_krw: KrwString | None = Field(repr=False)
    purchase_url: str | None
    reversal_of: UUID | None
    reason: str | None = Field(repr=False)
    note: str | None = Field(repr=False)
    stock_version: Version
    created_by_member_id: UUID
    created_at: datetime
    reversed_by: UUID | None


class StockMovementListResponse(BaseModel):
    items: list[StockMovementResponse]
    next_cursor: UUID | None


class ReplacementResponse(BaseModel):
    id: UUID
    household_id: UUID
    appliance_consumable_id: UUID
    consumable_id: UUID
    stock_movement_id: UUID
    replaced_on: DateOnly
    quantity: PositiveQuantity
    note: str | None = Field(repr=False)
    created_by_member_id: UUID
    created_at: datetime
    cancelled_by_movement_id: UUID | None


class ReplacementListResponse(BaseModel):
    items: list[ReplacementResponse]
    next_cursor: UUID | None


class HomecareStatusItem(ApplianceConsumableResponse):
    appliance_name: str
    appliance_location: str | None
    consumable_name: str
    sku_or_model: str | None
    unit: str
    low_stock_threshold: Quantity


class HomecareStatusResponse(BaseModel):
    as_of: DateOnly
    items: list[HomecareStatusItem]
    next_cursor: UUID | None
