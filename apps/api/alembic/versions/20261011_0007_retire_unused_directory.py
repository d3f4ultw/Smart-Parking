"""Remove the abandoned directory table and its realtime journal records."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261011_0007"
down_revision: str | None = "20261011_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the unused directory and disallow its retired event type."""

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM eventos_tiempo_real WHERE recurso_tipo = 'personal'"
        )
    )
    bind.execute(sa.text("DROP TABLE IF EXISTS empleados"))

    op.drop_constraint(
        "ck_eventos_tiempo_real_tipo",
        "eventos_tiempo_real",
        type_="check",
    )
    op.create_check_constraint(
        "ck_eventos_tiempo_real_tipo",
        "eventos_tiempo_real",
        "(recurso_tipo = 'operador' AND "
        "tipo IN ('operador.creado', 'operador.actualizado')) OR "
        "(recurso_tipo = 'cajon' AND tipo = 'cajon.actualizado')",
    )


def downgrade() -> None:
    """Keep the removed directory unavailable after a downgrade."""

