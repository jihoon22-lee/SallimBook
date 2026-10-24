"""Shared SKU stock and per-appliance history; never asset valuations or cash facts."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from sallimbook.core.database import Base, EntityMixin
from sallimbook.core.types import KrwNumeric
from sallimbook.homecare.calculations import MAX_QUANTITY


def household_fk(table: str, field: str, target: str):
    return ForeignKeyConstraint(
        ["household_id", field],
        [f"{target}.household_id", f"{target}.id"],
        ondelete="RESTRICT",
        name=f"fk_{table}_{field}",
    )


def actor_constraints(table: str):
    return (
        household_fk(table, "created_by_member_id", "household_members"),
        household_fk(table, "updated_by_member_id", "household_members"),
        CheckConstraint("version > 0", name="positive_version"),
    )


class ActorFields:
    household_id: Mapped[UUID]
    created_by_member_id: Mapped[UUID]
    updated_by_member_id: Mapped[UUID]


class Appliance(ActorFields, EntityMixin, Base):
    __tablename__ = "appliances"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        *actor_constraints("appliances"),
        CheckConstraint("char_length(btrim(name)) > 0", name="nonempty_name"),
        CheckConstraint(
            "purchase_price_krw IS NULL OR purchase_price_krw >= 0", name="nonnegative_price"
        ),
        CheckConstraint(
            "ended_on IS NULL OR purchased_on IS NULL OR ended_on >= purchased_on",
            name="purchase_end_order",
        ),
        Index("ix_appliances_household_ended_id", "household_id", "ended_on", "id"),
    )
    name: Mapped[str] = mapped_column(String(120))
    manufacturer: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(120))
    purchased_on: Mapped[date | None]
    purchase_price_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    seller: Mapped[str | None] = mapped_column(String(120))
    warranty_until: Mapped[date | None]
    ended_on: Mapped[date | None]
    note: Mapped[str | None] = mapped_column(String(2000))


class Consumable(ActorFields, EntityMixin, Base):
    __tablename__ = "consumables"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("household_id", "sku_or_model", name="uq_consumables_household_sku"),
        *actor_constraints("consumables"),
        CheckConstraint("char_length(btrim(name)) > 0", name="nonempty_name"),
        CheckConstraint(
            "sku_or_model IS NULL OR char_length(btrim(sku_or_model)) > 0", name="nonempty_sku"
        ),
        CheckConstraint("char_length(btrim(unit)) > 0", name="nonempty_unit"),
        CheckConstraint(f"stock_quantity BETWEEN 0 AND {MAX_QUANTITY}", name="stock_bounds"),
        CheckConstraint(
            f"low_stock_threshold BETWEEN 0 AND {MAX_QUANTITY}", name="threshold_bounds"
        ),
        Index("ix_consumables_household_ended_id", "household_id", "ended_on", "id"),
    )
    name: Mapped[str] = mapped_column(String(120))
    sku_or_model: Mapped[str | None] = mapped_column(String(120))
    unit: Mapped[str] = mapped_column(String(40))
    # A cached sum of immutable movements, never writable through metadata input.
    stock_quantity: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    low_stock_threshold: Mapped[int] = mapped_column(BigInteger)
    ended_on: Mapped[date | None]
    note: Mapped[str | None] = mapped_column(String(2000))


class ApplianceConsumable(ActorFields, EntityMixin, Base):
    __tablename__ = "appliance_consumables"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint(
            "household_id", "id", "consumable_id", name="uq_appliance_consumables_stock_target"
        ),
        UniqueConstraint(
            "household_id", "appliance_id", "consumable_id", name="uq_appliance_consumables_pair"
        ),
        *actor_constraints("appliance_consumables"),
        household_fk("appliance_consumables", "appliance_id", "appliances"),
        household_fk("appliance_consumables", "consumable_id", "consumables"),
        CheckConstraint(
            "(interval_unit = 'manual' AND interval_count IS NULL) OR "
            "(interval_unit = 'days' AND interval_count IS NOT NULL "
            "AND interval_count BETWEEN 1 AND 3650) OR "
            "(interval_unit = 'months' AND interval_count IS NOT NULL "
            "AND interval_count BETWEEN 1 AND 120)",
            name="interval_shape",
        ),
        CheckConstraint(
            f"quantity_per_replacement BETWEEN 1 AND {MAX_QUANTITY}", name="quantity_bounds"
        ),
        Index("ix_appliance_consumables_household_appliance", "household_id", "appliance_id", "id"),
        Index(
            "ix_appliance_consumables_household_consumable", "household_id", "consumable_id", "id"
        ),
    )
    appliance_id: Mapped[UUID]
    consumable_id: Mapped[UUID]
    interval_unit: Mapped[str] = mapped_column(String(6))
    interval_count: Mapped[int | None]
    quantity_per_replacement: Mapped[int] = mapped_column(BigInteger)
    next_check_override: Mapped[date | None]
    active: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str | None] = mapped_column(String(2000))


class ImmutableFields:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID]
    created_by_member_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StockMovement(ImmutableFields, Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint(
            "household_id", "consumable_id", "id", name="uq_stock_movements_stock_target"
        ),
        UniqueConstraint("household_id", "reversal_of", name="uq_stock_movements_reversal"),
        UniqueConstraint(
            "household_id",
            "consumable_id",
            "stock_version",
            name="uq_stock_movements_stock_version",
        ),
        household_fk("stock_movements", "consumable_id", "consumables"),
        household_fk("stock_movements", "created_by_member_id", "household_members"),
        ForeignKeyConstraint(
            ["household_id", "consumable_id", "reversal_of"],
            ["stock_movements.household_id", "stock_movements.consumable_id", "stock_movements.id"],
            ondelete="RESTRICT",
            name="fk_stock_movements_reversal_stock",
        ),
        CheckConstraint(
            "kind IN ('receipt','replacement','return_in','return_out','adjustment','reversal')",
            name="kind",
        ),
        CheckConstraint(
            f"quantity_delta BETWEEN -{MAX_QUANTITY} AND {MAX_QUANTITY} AND quantity_delta <> 0",
            name="delta_bounds",
        ),
        CheckConstraint(
            "(kind IN ('receipt','return_in') AND quantity_delta > 0) OR "
            "(kind IN ('replacement','return_out') AND quantity_delta < 0) OR "
            "kind IN ('adjustment','reversal')",
            name="direction",
        ),
        CheckConstraint("(kind = 'reversal') = (reversal_of IS NOT NULL)", name="reversal_shape"),
        CheckConstraint("reversal_of IS NULL OR reversal_of <> id", name="not_self_reversal"),
        CheckConstraint(
            "kind NOT IN ('adjustment','reversal') OR "
            "(reason IS NOT NULL AND char_length(btrim(reason)) > 0)",
            name="reason_required",
        ),
        CheckConstraint(
            "unit_cost_krw IS NULL OR unit_cost_krw >= 0", name="nonnegative_unit_cost"
        ),
        CheckConstraint("stock_version > 0", name="positive_stock_version"),
        Index("ix_stock_movements_household_consumable_id", "household_id", "consumable_id", "id"),
    )
    consumable_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(12))
    quantity_delta: Mapped[int] = mapped_column(BigInteger)
    occurred_on: Mapped[date]
    unit_cost_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    purchase_url: Mapped[str | None] = mapped_column(String(2048))
    reversal_of: Mapped[UUID | None]
    reason: Mapped[str | None] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(String(2000))
    # Captured at insertion for immutable replay receipts, not the current stock version.
    stock_version: Mapped[int] = mapped_column(BigInteger)


class ConsumableReplacement(ImmutableFields, Base):
    __tablename__ = "consumable_replacements"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint(
            "household_id", "stock_movement_id", name="uq_consumable_replacements_movement"
        ),
        household_fk("consumable_replacements", "created_by_member_id", "household_members"),
        ForeignKeyConstraint(
            ["household_id", "appliance_consumable_id", "consumable_id"],
            [
                "appliance_consumables.household_id",
                "appliance_consumables.id",
                "appliance_consumables.consumable_id",
            ],
            ondelete="RESTRICT",
            name="fk_consumable_replacements_link_stock",
        ),
        ForeignKeyConstraint(
            ["household_id", "consumable_id", "stock_movement_id"],
            ["stock_movements.household_id", "stock_movements.consumable_id", "stock_movements.id"],
            ondelete="RESTRICT",
            name="fk_consumable_replacements_movement_stock",
        ),
        CheckConstraint(f"quantity BETWEEN 1 AND {MAX_QUANTITY}", name="quantity_bounds"),
        CheckConstraint(
            "(cleared_next_check_override IS NULL) = (cleared_link_version IS NULL)",
            name="cleared_override_pair",
        ),
        Index(
            "ix_consumable_replacements_household_link_date_id",
            "household_id",
            "appliance_consumable_id",
            "replaced_on",
            "id",
        ),
    )
    appliance_consumable_id: Mapped[UUID]
    consumable_id: Mapped[UUID]
    stock_movement_id: Mapped[UUID]
    replaced_on: Mapped[date]
    quantity: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(String(2000))
    cleared_next_check_override: Mapped[date | None]
    cleared_link_version: Mapped[int | None] = mapped_column(BigInteger)


class ConsumableOrder(ActorFields, EntityMixin, Base):
    __tablename__ = "consumable_orders"
    __table_args__ = (
        UniqueConstraint("household_id", "id"),
        UniqueConstraint("household_id", "stock_movement_id", name="uq_consumable_orders_receipt"),
        *actor_constraints("consumable_orders"),
        household_fk("consumable_orders", "consumable_id", "consumables"),
        household_fk("consumable_orders", "ordered_by_member_id", "household_members"),
        household_fk("consumable_orders", "received_by_member_id", "household_members"),
        ForeignKeyConstraint(
            ["household_id", "consumable_id", "stock_movement_id"],
            ["stock_movements.household_id", "stock_movements.consumable_id", "stock_movements.id"],
            ondelete="RESTRICT",
            name="fk_consumable_orders_receipt_stock",
        ),
        CheckConstraint("state IN ('planned','ordered','received','cancelled')", name="state"),
        CheckConstraint(f"quantity BETWEEN 1 AND {MAX_QUANTITY}", name="quantity_bounds"),
        CheckConstraint(
            "unit_cost_krw IS NULL OR unit_cost_krw >= 0", name="nonnegative_unit_cost"
        ),
        CheckConstraint(
            "(ordered_on IS NULL) = (ordered_by_member_id IS NULL) AND "
            "(state <> 'planned' OR ordered_on IS NULL) AND "
            "(state NOT IN ('ordered','received') OR ordered_on IS NOT NULL)",
            name="order_shape",
        ),
        CheckConstraint(
            "(state = 'received' AND received_on IS NOT NULL AND received_by_member_id IS NOT NULL "
            "AND stock_movement_id IS NOT NULL AND received_on >= ordered_on) OR "
            "(state <> 'received' AND received_on IS NULL AND received_by_member_id IS NULL "
            "AND stock_movement_id IS NULL)",
            name="receipt_shape",
        ),
        CheckConstraint(
            "(state = 'cancelled' AND cancel_reason IS NOT NULL "
            "AND char_length(btrim(cancel_reason)) > 0) OR "
            "(state <> 'cancelled' AND cancel_reason IS NULL)",
            name="cancellation_shape",
        ),
        Index(
            "ix_consumable_orders_household_state_created_id",
            "household_id",
            "state",
            "created_at",
            "id",
        ),
    )
    consumable_id: Mapped[UUID]
    state: Mapped[str] = mapped_column(String(9))
    quantity: Mapped[int] = mapped_column(BigInteger)
    unit_cost_krw: Mapped[Decimal | None] = mapped_column(KrwNumeric())
    purchase_url: Mapped[str | None] = mapped_column(String(2048))
    note: Mapped[str | None] = mapped_column(String(2000))
    ordered_on: Mapped[date | None]
    ordered_by_member_id: Mapped[UUID | None]
    received_on: Mapped[date | None]
    received_by_member_id: Mapped[UUID | None]
    stock_movement_id: Mapped[UUID | None]
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
