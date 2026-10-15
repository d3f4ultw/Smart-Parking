"""Repara el cursor SSE global si falta su fila singleton."""

from sqlalchemy import text

from alembic import op

revision = "20261013_0003"
down_revision = "20261013_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Crea el cursor ausente sin retroceder uno que ya exista."""

    op.execute(
        text(
            "INSERT INTO estado_eventos_tiempo_real (id, ultimo_id) "
            "SELECT 1, COALESCE(MAX(id), 0) FROM eventos_tiempo_real "
            "ON CONFLICT (id) DO UPDATE SET ultimo_id = GREATEST("
            "estado_eventos_tiempo_real.ultimo_id, EXCLUDED.ultimo_id)"
        )
    )


def downgrade() -> None:
    """No elimina la fila compartida del cursor global."""

    raise RuntimeError("La reparacion del cursor SSE es forward-only.")
