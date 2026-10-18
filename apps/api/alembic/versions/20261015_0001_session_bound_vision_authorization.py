"""Replace the temporary Vision authorization expiry with session state."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261015_0001"
down_revision = "20261014_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sesiones",
        sa.Column(
            "vision_autorizada",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE sesiones
            SET vision_autorizada = TRUE
            WHERE vision_elevada_hasta > CURRENT_TIMESTAMP
            """
        )
    )
    op.drop_column("sesiones", "vision_elevada_hasta")


def downgrade() -> None:
    op.add_column(
        "sesiones",
        sa.Column("vision_elevada_hasta", sa.DateTime(timezone=True)),
    )
    op.drop_column("sesiones", "vision_autorizada")
