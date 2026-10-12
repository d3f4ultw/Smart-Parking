"""Track the fixed OWNER enrollment window separately from each email link."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261011_0003"
down_revision: str | None = "20261011_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Adds the fixed one-hour window without changing enrollment records."""

    op.add_column(
        "inscripciones_propietario",
        sa.Column("proceso_expira_en", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE inscripciones_propietario "
        "SET proceso_expira_en = creado_en + INTERVAL '60 minutes'"
    )
    op.alter_column(
        "inscripciones_propietario",
        "proceso_expira_en",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )


def downgrade() -> None:
    """Removes only the fixed-window timestamp."""

    op.drop_column("inscripciones_propietario", "proceso_expira_en")
