"""Allow durable parking events in the realtime journal."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261011_0006"
down_revision: str | None = "20261011_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow operator and parking event types in the shared journal."""

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
    """Refuse to remove parking event support while its history is retained."""

    bind = op.get_bind()
    eventos_cajon = bind.execute(
        sa.text(
            "SELECT count(*) FROM eventos_tiempo_real WHERE recurso_tipo = 'cajon'"
        )
    ).scalar_one()
    if eventos_cajon:
        raise RuntimeError(
            "No se puede revertir: el journal contiene eventos de estacionamiento."
        )

    op.drop_constraint(
        "ck_eventos_tiempo_real_tipo",
        "eventos_tiempo_real",
        type_="check",
    )
    op.create_check_constraint(
        "ck_eventos_tiempo_real_tipo",
        "eventos_tiempo_real",
        "recurso_tipo = 'operador' AND "
        "tipo IN ('operador.creado', 'operador.actualizado')",
    )

