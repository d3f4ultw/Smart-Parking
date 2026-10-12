"""Make the operational parking reason optional."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261008_0001"
down_revision = "20261006_0001"
branch_labels = None
depends_on = None

_RESTRICCION_OPCIONAL = (
    "(estado_operativo = 'DISPONIBLE' AND motivo_operativo IS NULL) OR "
    "(estado_operativo IN ('MANTENIMIENTO', 'FUERA_DE_SERVICIO') AND "
    "(motivo_operativo IS NULL OR motivo_operativo ~ '[^[:space:]]'))"
)

_RESTRICCION_ANTERIOR = (
    "(estado_operativo = 'DISPONIBLE' AND motivo_operativo IS NULL) OR "
    "(estado_operativo IN ('MANTENIMIENTO', 'FUERA_DE_SERVICIO') AND "
    "motivo_operativo IS NOT NULL AND "
    "motivo_operativo ~ '[^[:space:]]')"
)


def upgrade() -> None:
    """Allows omitted reasons in maintenance and out-of-service states."""

    op.drop_constraint(
        "ck_cajones_motivo_operativo",
        "cajones",
        type_="check",
    )
    op.create_check_constraint(
        "ck_cajones_motivo_operativo",
        "cajones",
        _RESTRICCION_OPCIONAL,
    )


def downgrade() -> None:
    """Refuses to restore required reasons while reasonless states exist."""

    conexion = op.get_bind()
    cajones_sin_motivo = int(
        conexion.scalar(
            sa.text(
                "SELECT count(*) FROM cajones "
                "WHERE estado_operativo IN ('MANTENIMIENTO', 'FUERA_DE_SERVICIO') "
                "AND motivo_operativo IS NULL"
            )
        )
        or 0
    )
    if cajones_sin_motivo:
        raise RuntimeError(
            "No se puede revertir: hay cajones no disponibles sin motivo."
        )

    op.drop_constraint(
        "ck_cajones_motivo_operativo",
        "cajones",
        type_="check",
    )
    op.create_check_constraint(
        "ck_cajones_motivo_operativo",
        "cajones",
        _RESTRICCION_ANTERIOR,
    )
