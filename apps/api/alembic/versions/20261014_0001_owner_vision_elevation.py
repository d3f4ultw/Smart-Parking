"""Agrega la elevacion Vision temporal a la sesion existente del OWNER."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261014_0001"
down_revision = "20261013_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sesiones",
        sa.Column("vision_elevada_hasta", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sesiones", "vision_elevada_hasta")
