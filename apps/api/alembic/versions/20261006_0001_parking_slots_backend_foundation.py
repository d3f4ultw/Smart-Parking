"""Add parking slots and payloads to the realtime event journal."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261006_0001"
down_revision = "20261004_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cajones",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column(
            "estado_fisico",
            sa.String(length=16),
            server_default="DESCONOCIDO",
            nullable=False,
        ),
        sa.Column(
            "estado_operativo",
            sa.String(length=32),
            server_default="DISPONIBLE",
            nullable=False,
        ),
        sa.Column("motivo_operativo", sa.String(length=250), nullable=True),
        sa.Column(
            "estado_fisico_actualizado_en",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "estado_operativo_actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cajones"),
        sa.UniqueConstraint("numero", name="uq_cajones_numero"),
        sa.CheckConstraint("numero > 0", name="ck_cajones_numero_positivo"),
        sa.CheckConstraint(
            "estado_fisico IN ('DESCONOCIDO', 'LIBRE', 'OCUPADO')",
            name="ck_cajones_estado_fisico",
        ),
        sa.CheckConstraint(
            "estado_operativo IN ('DISPONIBLE', 'MANTENIMIENTO', 'FUERA_DE_SERVICIO')",
            name="ck_cajones_estado_operativo",
        ),
        sa.CheckConstraint(
            "(estado_operativo = 'DISPONIBLE' AND motivo_operativo IS NULL) OR "
            "(estado_operativo IN ('MANTENIMIENTO', 'FUERA_DE_SERVICIO') AND "
            "motivo_operativo IS NOT NULL AND "
            "motivo_operativo ~ '[^[:space:]]')",
            name="ck_cajones_motivo_operativo",
        ),
    )

    cajones = sa.table(
        "cajones",
        sa.column("numero", sa.Integer()),
        sa.column("estado_fisico", sa.String(length=16)),
        sa.column("estado_operativo", sa.String(length=32)),
        sa.column("motivo_operativo", sa.String(length=250)),
        sa.column("estado_fisico_actualizado_en", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        cajones,
        [
            {
                "numero": numero,
                "estado_fisico": "DESCONOCIDO",
                "estado_operativo": "DISPONIBLE",
                "motivo_operativo": None,
                "estado_fisico_actualizado_en": None,
            }
            for numero in range(1, 9)
        ],
    )

    op.add_column(
        "eventos_tiempo_real",
        sa.Column("datos", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
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
    op.create_check_constraint(
        "ck_eventos_tiempo_real_datos_cajon",
        "eventos_tiempo_real",
        "recurso_tipo <> 'cajon' OR datos IS NOT NULL",
    )


def downgrade() -> None:
    conexion = op.get_bind()
    cantidad_cajones = int(
        conexion.scalar(sa.text("SELECT count(*) FROM cajones")) or 0
    )
    cantidad_eventos_cajon = int(
        conexion.scalar(
            sa.text(
                "SELECT count(*) FROM eventos_tiempo_real "
                "WHERE recurso_tipo = 'cajon' OR tipo = 'cajon.actualizado'"
            )
        )
        or 0
    )
    cantidad_cajones_modificados = int(
        conexion.scalar(
            sa.text(
                "SELECT count(*) FROM cajones WHERE numero NOT BETWEEN 1 AND 8 "
                "OR estado_fisico <> 'DESCONOCIDO' "
                "OR estado_operativo <> 'DISPONIBLE' "
                "OR motivo_operativo IS NOT NULL "
                "OR estado_fisico_actualizado_en IS NOT NULL "
                "OR estado_operativo_actualizado_en <> creado_en"
            )
        )
        or 0
    )
    if (
        cantidad_cajones != 8
        or cantidad_eventos_cajon > 0
        or cantidad_cajones_modificados > 0
    ):
        raise RuntimeError(
            "No se puede revertir: existen cajones usados o eventos asociados."
        )

    op.drop_constraint(
        "ck_eventos_tiempo_real_datos_cajon",
        "eventos_tiempo_real",
        type_="check",
    )
    op.drop_constraint(
        "ck_eventos_tiempo_real_tipo",
        "eventos_tiempo_real",
        type_="check",
    )
    op.drop_column("eventos_tiempo_real", "datos")
    op.create_check_constraint(
        "ck_eventos_tiempo_real_tipo",
        "eventos_tiempo_real",
        "tipo IN ('operador.creado', 'operador.actualizado')",
    )
    op.drop_table("cajones")
