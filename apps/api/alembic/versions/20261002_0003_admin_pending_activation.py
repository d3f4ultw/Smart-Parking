"""Allow ADMIN accounts to remain passwordless while activating by link."""

from __future__ import annotations

from sqlalchemy import text

from alembic import op

revision = "20261002_0003"
down_revision = "20261002_0002"
branch_labels = None
depends_on = None

_CHECK_ANTERIOR = "ck_usuarios_contrasena_hash_operador_pendiente"
_CHECK_NUEVO = "ck_usuarios_contrasena_hash_pendiente_activacion"


def upgrade() -> None:
    op.drop_constraint(_CHECK_ANTERIOR, "usuarios", type_="check")
    op.create_check_constraint(
        _CHECK_NUEVO,
        "usuarios",
        "contrasena_hash IS NOT NULL OR "
        "(rol IN ('ADMIN', 'OPERADOR') AND correo_verificado = false)",
    )


def downgrade() -> None:
    conexion = op.get_bind()
    admin_pendiente_sin_contrasena = conexion.execute(
        text(
            "SELECT 1 FROM usuarios "
            "WHERE rol = 'ADMIN' AND correo_verificado = false "
            "AND contrasena_hash IS NULL LIMIT 1"
        )
    ).first()
    if admin_pendiente_sin_contrasena is not None:
        raise RuntimeError(
            "No se puede revertir: existen ADMIN pendientes sin contrasena."
        )

    op.drop_constraint(_CHECK_NUEVO, "usuarios", type_="check")
    op.create_check_constraint(
        _CHECK_ANTERIOR,
        "usuarios",
        "contrasena_hash IS NOT NULL OR "
        "(rol = 'OPERADOR' AND correo_verificado = false)",
    )
