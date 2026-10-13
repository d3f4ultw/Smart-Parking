"""Add OWNER-controlled parking access suspension."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261012_0001"
down_revision = "20261011_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "configuracion_estacionamiento",
        sa.Column(
            "acceso_suspendido",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    tabla_configuracion = sa.table(
        "configuracion_estacionamiento",
        sa.column("acceso_suspendido", sa.Boolean()),
    )
    acceso_suspendido = op.get_bind().scalar(
        sa.select(
            sa.exists().where(tabla_configuracion.c.acceso_suspendido.is_(True))
        )
    )
    if acceso_suspendido:
        raise RuntimeError(
            "No se puede revertir mientras exista una suspension de acceso activa."
        )

    op.drop_column("configuracion_estacionamiento", "acceso_suspendido")
