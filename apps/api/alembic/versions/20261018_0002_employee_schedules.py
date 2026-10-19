"""Create shared employee schedules for the configured parking."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261018_0002"
down_revision = "20261018_0001"
branch_labels = None
depends_on = None

CODIGOS_TURNOS = (
    "MATUTINO",
    "VESPERTINO",
    "NOCTURNO",
    "SIN_RESTRICCION",
)


def upgrade() -> None:
    op.add_column(
        "configuracion_estacionamiento",
        sa.Column(
            "revision_horarios",
            sa.BigInteger(),
            server_default="1",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_configuracion_estacionamiento_revision_horarios_positiva",
        "configuracion_estacionamiento",
        "revision_horarios > 0",
    )
    op.create_table(
        "turnos_empleados",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("configuracion_estacionamiento_id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=24), nullable=False),
        sa.Column("hora_inicio", sa.Time(timezone=False), nullable=True),
        sa.Column("hora_fin", sa.Time(timezone=False), nullable=True),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "codigo IN ('MATUTINO', 'VESPERTINO', 'NOCTURNO', 'SIN_RESTRICCION')",
            name="ck_turnos_empleados_codigo",
        ),
        sa.CheckConstraint(
            "(codigo = 'SIN_RESTRICCION' AND hora_inicio IS NULL AND "
            "hora_fin IS NULL) OR (codigo <> 'SIN_RESTRICCION' AND "
            "((hora_inicio IS NULL AND hora_fin IS NULL) OR "
            "(hora_inicio IS NOT NULL AND hora_fin IS NOT NULL AND "
            "hora_inicio <> hora_fin)))",
            name="ck_turnos_empleados_horas_validas",
        ),
        sa.ForeignKeyConstraint(
            ["configuracion_estacionamiento_id"],
            ["configuracion_estacionamiento.id"],
            name="fk_turnos_empleados_configuracion",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_turnos_empleados"),
        sa.UniqueConstraint(
            "configuracion_estacionamiento_id",
            "codigo",
            name="uq_turnos_empleados_configuracion_codigo",
        ),
        sa.UniqueConstraint(
            "configuracion_estacionamiento_id",
            "id",
            name="uq_turnos_empleados_configuracion_id_id",
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO turnos_empleados "
            "(configuracion_estacionamiento_id, codigo) "
            "SELECT configuracion.id, catalogo.codigo "
            "FROM configuracion_estacionamiento AS configuracion "
            "CROSS JOIN (VALUES ('MATUTINO'), ('VESPERTINO'), ('NOCTURNO'), "
            "('SIN_RESTRICCION')) AS catalogo(codigo) "
            "WHERE configuracion.id = 1 "
            "ON CONFLICT (configuracion_estacionamiento_id, codigo) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM turnos_empleados "
            "WHERE codigo <> 'SIN_RESTRICCION' "
            "AND (hora_inicio IS NOT NULL OR hora_fin IS NOT NULL)) THEN "
            "RAISE EXCEPTION 'No se pueden eliminar horarios configurados'; "
            "END IF; END $$"
        )
    )
    op.drop_table("turnos_empleados")
    op.drop_constraint(
        "ck_configuracion_estacionamiento_revision_horarios_positiva",
        "configuracion_estacionamiento",
        type_="check",
    )
    op.drop_column("configuracion_estacionamiento", "revision_horarios")
