"""Create a persistent singleton lease for exclusive Vision calibration."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261018_0001"
down_revision = "20261015_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vision_calibration_lease",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_session_hash", sa.String(length=64), nullable=True),
        sa.Column("editor_instance_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "id = 1",
            name="ck_vision_calibration_lease_singleton",
        ),
        sa.CheckConstraint(
            "(owner_session_hash IS NULL AND editor_instance_id IS NULL "
            "AND expires_at IS NULL) OR "
            "(owner_session_hash IS NOT NULL AND editor_instance_id IS NOT NULL "
            "AND expires_at IS NOT NULL)",
            name="ck_vision_calibration_lease_owner_complete",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vision_calibration_lease"),
    )
    op.execute(
        sa.text(
            "INSERT INTO vision_calibration_lease (id) VALUES (1)"
        )
    )


def downgrade() -> None:
    op.drop_table("vision_calibration_lease")
