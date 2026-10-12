"""Add the uninitialized parking modality and its change history."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261010_0001"
down_revision = "20261008_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Creates the singleton and history tables without selecting a mode."""

    op.create_table(
        "configuracion_estacionamiento",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("modalidad", sa.String(length=8), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "id = 1",
            name="ck_configuracion_estacionamiento_singleton",
        ),
        sa.CheckConstraint(
            "modalidad IN ('PRIVADO', 'PUBLICO', 'MIXTO')",
            name="ck_configuracion_estacionamiento_modalidad",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_configuracion_estacionamiento_revision_positiva",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "historial_modalidad_estacionamiento",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("configuracion_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("modalidad_anterior", sa.String(length=8), nullable=True),
        sa.Column("modalidad_nueva", sa.String(length=8), nullable=False),
        sa.Column(
            "cambiado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_historial_modalidad_revision_positiva",
        ),
        sa.CheckConstraint(
            "modalidad_nueva IN ('PRIVADO', 'PUBLICO', 'MIXTO')",
            name="ck_historial_modalidad_nueva",
        ),
        sa.CheckConstraint(
            "(modalidad_anterior IS NULL AND revision = 1) OR "
            "(modalidad_anterior IS NOT NULL AND "
            "modalidad_anterior IN ('PRIVADO', 'PUBLICO', 'MIXTO') AND "
            "modalidad_anterior <> modalidad_nueva AND revision > 1)",
            name="ck_historial_modalidad_secuencia",
        ),
        sa.ForeignKeyConstraint(
            ["configuracion_id"],
            ["configuracion_estacionamiento.id"],
            name="fk_historial_modalidad_configuracion",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "configuracion_id",
            "revision",
            name="uq_historial_modalidad_config_revision",
        ),
    )


def downgrade() -> None:
    """Refuses to drop a configuration or its recorded history."""

    conexion = op.get_bind()
    filas_configuracion = int(
        conexion.scalar(sa.text("SELECT count(*) FROM configuracion_estacionamiento"))
        or 0
    )
    filas_historial = int(
        conexion.scalar(
            sa.text("SELECT count(*) FROM historial_modalidad_estacionamiento")
        )
        or 0
    )
    if filas_configuracion or filas_historial:
        raise RuntimeError(
            "No se puede revertir: hay una modalidad o historial configurado."
        )

    op.drop_table("historial_modalidad_estacionamiento")
    op.drop_table("configuracion_estacionamiento")
