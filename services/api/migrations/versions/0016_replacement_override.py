"""Keep the manual next-check date a replacement cleared so cancellation can restore it.

Revision ID: 0016_replacement_override
Revises: 0015_rule_revocation
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_replacement_override"
down_revision = "0015_rule_revocation"
branch_labels = None
depends_on = None

VALIDATE = """
    CREATE OR REPLACE FUNCTION validate_consumable_replacement() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE movement stock_movements%ROWTYPE;
    BEGIN
        SELECT * INTO movement FROM stock_movements
            WHERE id = NEW.stock_movement_id AND household_id = NEW.household_id
                AND consumable_id = NEW.consumable_id;
        IF NOT FOUND OR movement.kind <> 'replacement'
            OR movement.quantity_delta <> -NEW.quantity
            OR movement.occurred_on <> NEW.replaced_on THEN
            RAISE EXCEPTION 'Replacement requires its matching usage movement'
                USING ERRCODE = '23514';
        END IF;{cleared}
        RETURN NEW;
    END $$
"""
CLEARED = """
        IF NEW.cleared_link_version IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM appliance_consumables
            WHERE household_id = NEW.household_id AND id = NEW.appliance_consumable_id
                AND version = NEW.cleared_link_version AND next_check_override IS NULL
        ) THEN
            RAISE EXCEPTION 'A cleared override must record the link version that cleared it'
                USING ERRCODE = '23514';
        END IF;"""


def upgrade() -> None:
    op.add_column(
        "consumable_replacements",
        sa.Column("cleared_next_check_override", sa.Date(), nullable=True),
    )
    op.add_column(
        "consumable_replacements",
        sa.Column("cleared_link_version", sa.BigInteger(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_consumable_replacements_cleared_override_pair"),
        "consumable_replacements",
        "(cleared_next_check_override IS NULL) = (cleared_link_version IS NULL)",
    )
    op.execute(VALIDATE.format(cleared=CLEARED))


def downgrade() -> None:
    op.execute(VALIDATE.format(cleared=""))
    op.drop_constraint(
        op.f("ck_consumable_replacements_cleared_override_pair"),
        "consumable_replacements",
        type_="check",
    )
    op.drop_column("consumable_replacements", "cleared_link_version")
    op.drop_column("consumable_replacements", "cleared_next_check_override")
