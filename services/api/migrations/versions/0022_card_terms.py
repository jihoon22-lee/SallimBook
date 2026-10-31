"""Optional card annual fee and family status; existing notes remain unchanged.

Revision ID: 0022_card_terms
Revises: 0021_consumable_orders
"""

import sqlalchemy as sa
from alembic import op

revision = "0022_card_terms"
down_revision = "0021_consumable_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cards", sa.Column("annual_fee_krw", sa.Numeric(20, 0), nullable=True))
    op.add_column("cards", sa.Column("is_family_card", sa.Boolean(), nullable=True))
    op.create_check_constraint(
        op.f("ck_cards_annual_fee_nonnegative"),
        "cards",
        "annual_fee_krw IS NULL OR annual_fee_krw >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_cards_annual_fee_nonnegative"), "cards", type_="check")
    op.drop_column("cards", "is_family_card")
    op.drop_column("cards", "annual_fee_krw")
