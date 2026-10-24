"""Add shared purchase intentions with one atomic, immutable full stock receipt."""

import sqlalchemy as sa
from alembic import op

revision = "0021_consumable_orders"
down_revision = "0020_insurance_misregistration"
branch_labels = None
depends_on = None


def upgrade():
    table = "consumable_orders"
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("consumable_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(9), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("unit_cost_krw", sa.Numeric(20, 0)),
        sa.Column("purchase_url", sa.String(2048)),
        sa.Column("note", sa.String(2000)),
        sa.Column("ordered_on", sa.Date()),
        sa.Column("ordered_by_member_id", sa.Uuid()),
        sa.Column("received_on", sa.Date()),
        sa.Column("received_by_member_id", sa.Uuid()),
        sa.Column("stock_movement_id", sa.Uuid()),
        sa.Column("cancel_reason", sa.String(500)),
        sa.Column("created_by_member_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by_member_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consumable_orders")),
        sa.UniqueConstraint("household_id", "id", name=op.f("uq_consumable_orders_household_id")),
        sa.UniqueConstraint(
            "household_id", "stock_movement_id", name="uq_consumable_orders_receipt"
        ),
        *[
            sa.ForeignKeyConstraint(
                ["household_id", column],
                [f"{target}.household_id", f"{target}.id"],
                name=f"fk_{table}_{column}",
                ondelete="RESTRICT",
            )
            for column, target in (
                ("consumable_id", "consumables"),
                ("created_by_member_id", "household_members"),
                ("updated_by_member_id", "household_members"),
                ("ordered_by_member_id", "household_members"),
                ("received_by_member_id", "household_members"),
            )
        ],
        sa.ForeignKeyConstraint(
            ["household_id", "consumable_id", "stock_movement_id"],
            ["stock_movements.household_id", "stock_movements.consumable_id", "stock_movements.id"],
            name="fk_consumable_orders_receipt_stock",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_consumable_orders_positive_version")),
        sa.CheckConstraint(
            "state IN ('planned','ordered','received','cancelled')",
            name=op.f("ck_consumable_orders_state"),
        ),
        sa.CheckConstraint(
            "quantity BETWEEN 1 AND 1000000", name=op.f("ck_consumable_orders_quantity_bounds")
        ),
        sa.CheckConstraint(
            "unit_cost_krw IS NULL OR unit_cost_krw >= 0",
            name=op.f("ck_consumable_orders_nonnegative_unit_cost"),
        ),
        sa.CheckConstraint(
            "(ordered_on IS NULL) = (ordered_by_member_id IS NULL) AND "
            "(state <> 'planned' OR ordered_on IS NULL) AND "
            "(state NOT IN ('ordered','received') OR ordered_on IS NOT NULL)",
            name=op.f("ck_consumable_orders_order_shape"),
        ),
        sa.CheckConstraint(
            "(state = 'received' AND received_on IS NOT NULL AND received_by_member_id IS NOT NULL "
            "AND stock_movement_id IS NOT NULL AND received_on >= ordered_on) OR "
            "(state <> 'received' AND received_on IS NULL AND received_by_member_id IS NULL "
            "AND stock_movement_id IS NULL)",
            name=op.f("ck_consumable_orders_receipt_shape"),
        ),
        sa.CheckConstraint(
            "(state = 'cancelled' AND cancel_reason IS NOT NULL "
            "AND char_length(btrim(cancel_reason)) > 0) OR "
            "(state <> 'cancelled' AND cancel_reason IS NULL)",
            name=op.f("ck_consumable_orders_cancellation_shape"),
        ),
    )
    op.create_index(
        "ix_consumable_orders_household_state_created_id",
        table,
        ["household_id", "state", "created_at", "id"],
    )
    op.execute("""
        CREATE FUNCTION guard_consumable_order() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Purchase order history must be retained' USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.state <> 'planned' OR NEW.version <> 1 THEN
                    RAISE EXCEPTION 'A purchase order starts as a plan' USING ERRCODE = '23514';
                END IF;
            ELSE
                IF OLD.state IN ('received','cancelled') OR
                   ROW(NEW.id, NEW.household_id, NEW.consumable_id,
                       NEW.created_by_member_id, NEW.created_at)
                   IS DISTINCT FROM ROW(OLD.id, OLD.household_id, OLD.consumable_id,
                       OLD.created_by_member_id, OLD.created_at)
                   OR NEW.version <> OLD.version + 1 THEN
                    RAISE EXCEPTION 'Purchase order identity or completed history is immutable'
                        USING ERRCODE = '23514';
                END IF;
                IF (OLD.state = 'planned' AND NEW.state NOT IN ('planned','ordered','cancelled')) OR
                   (OLD.state = 'ordered'
                     AND NEW.state NOT IN ('ordered','received','cancelled')) OR
                   (OLD.state = 'ordered' AND ROW(NEW.ordered_on, NEW.ordered_by_member_id)
                     IS DISTINCT FROM ROW(OLD.ordered_on, OLD.ordered_by_member_id)) THEN
                    RAISE EXCEPTION 'Invalid purchase order transition' USING ERRCODE = '23514';
                END IF;
            END IF;
            IF NEW.state = 'received' AND NOT EXISTS (
                SELECT 1 FROM stock_movements m
                WHERE m.household_id = NEW.household_id AND m.consumable_id = NEW.consumable_id
                AND m.id = NEW.stock_movement_id AND m.kind = 'receipt'
                AND m.quantity_delta = NEW.quantity AND m.occurred_on = NEW.received_on
                AND m.created_by_member_id = NEW.received_by_member_id
                AND NEW.updated_by_member_id = NEW.received_by_member_id
                AND m.unit_cost_krw IS NOT DISTINCT FROM NEW.unit_cost_krw
                AND m.purchase_url IS NOT DISTINCT FROM NEW.purchase_url
                AND NOT EXISTS (SELECT 1 FROM stock_movements r
                    WHERE r.household_id = m.household_id AND r.reversal_of = m.id)
            ) THEN
                RAISE EXCEPTION 'Order receipt must match its stock fact' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER consumable_orders_guard
        BEFORE INSERT OR UPDATE OR DELETE ON consumable_orders
        FOR EACH ROW EXECUTE FUNCTION guard_consumable_order()
    """)

    op.execute("""
        CREATE FUNCTION preserve_purchase_order_unit() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.unit IS DISTINCT FROM OLD.unit AND EXISTS (
                SELECT 1 FROM consumable_orders
                WHERE household_id = OLD.household_id AND consumable_id = OLD.id
            ) THEN
                RAISE EXCEPTION 'Purchase quantity units must be retained' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER consumables_order_unit BEFORE UPDATE ON consumables
        FOR EACH ROW EXECUTE FUNCTION preserve_purchase_order_unit()
    """)


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM consumable_orders) THEN
                RAISE EXCEPTION 'Export and retain purchase order history before downgrading'
                    USING ERRCODE = '55000';
            END IF;
        END $$
    """)
    op.execute("DROP TRIGGER consumables_order_unit ON consumables")
    op.execute("DROP FUNCTION preserve_purchase_order_unit()")
    op.drop_table("consumable_orders")
    op.execute("DROP FUNCTION guard_consumable_order()")
