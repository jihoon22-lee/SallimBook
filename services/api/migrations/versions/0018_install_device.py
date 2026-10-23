"""Let an Android install keep one device row across sign-ins.

A native sign-in may present the device id and key it received earlier. The server keeps only
the key's SHA-256 and reuses the row when the key, user and household match and the row is
still active. The row records the session of that latest sign-in and admits no other session.

Revision ID: 0018_install_device
Revises: 0017_rule_delete
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_install_device"
down_revision = "0017_rule_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("registered_devices", sa.Column("install_key_hash", sa.String(64)))
    op.create_check_constraint(
        op.f("ck_registered_devices_android_install_key"),
        "registered_devices",
        "install_key_hash IS NULL OR (platform = 'android' AND length(install_key_hash) = 64)",
    )
    op.add_column("registered_devices", sa.Column("install_session_id", sa.Uuid()))
    op.create_check_constraint(
        op.f("ck_registered_devices_install_session"),
        "registered_devices",
        "install_session_id IS NULL OR install_key_hash IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_registered_devices_install_session"), "registered_devices", type_="check"
    )
    op.drop_column("registered_devices", "install_session_id")
    op.drop_constraint(
        op.f("ck_registered_devices_android_install_key"), "registered_devices", type_="check"
    )
    op.drop_column("registered_devices", "install_key_hash")
