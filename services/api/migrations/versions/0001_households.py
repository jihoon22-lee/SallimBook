"""Create the household root. Authentication tables follow in SB-005."""

import sqlalchemy as sa
from alembic import op

revision = "0001_households"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "households",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "timezone", sa.String(32), server_default=sa.text("'Asia/Seoul'"), nullable=False
        ),
        sa.Column("base_currency", sa.String(3), server_default=sa.text("'KRW'"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("timezone = 'Asia/Seoul'", name=op.f("ck_households_seoul_timezone")),
        sa.CheckConstraint("base_currency = 'KRW'", name=op.f("ck_households_krw_currency")),
        sa.CheckConstraint("version > 0", name=op.f("ck_households_positive_version")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_households")),
    )


def downgrade() -> None:
    op.drop_table("households")
