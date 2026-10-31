"""Encrypted direct-entry card details, separate from client-owned vault storage."""

import sqlalchemy as sa
from alembic import op

revision = "0025_card_stored_details"
down_revision = "0024_income_planning"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "card_stored_details",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("household_id", "card_id", name=op.f("pk_card_stored_details")),
        sa.ForeignKeyConstraint(
            ["household_id", "card_id"],
            ["cards.household_id", "cards.id"],
            name="fk_card_stored_details_card",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "key_version > 0", name=op.f("ck_card_stored_details_positive_key_version")
        ),
        sa.CheckConstraint(
            "octet_length(nonce) = 12", name=op.f("ck_card_stored_details_nonce_length")
        ),
        sa.CheckConstraint(
            "octet_length(ciphertext) = 144", name=op.f("ck_card_stored_details_ciphertext_length")
        ),
    )


def downgrade():
    # Serialize the existence check and DROP against concurrent detail writes.
    op.execute(sa.text("LOCK TABLE card_stored_details IN ACCESS EXCLUSIVE MODE"))
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM card_stored_details)")):
        raise RuntimeError("Cannot downgrade while stored card details exist")
    op.drop_table("card_stored_details")
