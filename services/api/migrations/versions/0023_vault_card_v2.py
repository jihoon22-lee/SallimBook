"""Accept version-bound optional synchronized CVC envelopes without plaintext columns.

Revision ID: 0023_vault_card_v2
Revises: 0022_card_terms
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_vault_card_v2"
down_revision = "0022_card_terms"
branch_labels = None
depends_on = None


def constraints(schema: str, size: str) -> None:
    for name in ("payload_schema", "ciphertext_length"):
        op.drop_constraint(
            op.f("ck_card_secret_envelopes_" + name), "card_secret_envelopes", type_="check"
        )
    op.create_check_constraint(
        op.f("ck_card_secret_envelopes_payload_schema"), "card_secret_envelopes", schema
    )
    op.create_check_constraint(
        op.f("ck_card_secret_envelopes_ciphertext_length"), "card_secret_envelopes", size
    )


def upgrade() -> None:
    constraints(
        "payload_schema_version IN (1, 2)",
        "ciphertext IS NULL OR (payload_schema_version = 1 AND "
        "octet_length(ciphertext) = 43) OR (payload_schema_version = 2 AND "
        "octet_length(ciphertext) = 48)",
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM card_secret_envelopes WHERE payload_schema_version = 2)"
        )
    ):
        raise RuntimeError("Cannot downgrade while v2 card envelopes exist")
    constraints("payload_schema_version = 1", "ciphertext IS NULL OR octet_length(ciphertext) = 43")
