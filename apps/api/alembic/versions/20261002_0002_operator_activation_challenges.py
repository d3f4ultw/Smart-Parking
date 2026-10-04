"""Agrega activacion por enlace para cuentas OPERADOR."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261002_0002"
down_revision: str | Sequence[str] | None = "20260926_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "usuarios",
        "contrasena_hash",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_usuarios_contrasena_hash_operador_pendiente",
        "usuarios",
        "contrasena_hash IS NOT NULL OR "
        "(rol = 'OPERADOR' AND correo_verificado = false)",
    )
    op.alter_column(
        "activaciones_cuenta",
        "codigo_hash",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.add_column(
        "activaciones_cuenta",
        sa.Column("desafio_hash", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "activaciones_cuenta",
        sa.Column("desafio_expira_en", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "activaciones_cuenta",
        sa.Column("ultimo_reenvio_en", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_activaciones_cuenta_desafio_completo",
        "activaciones_cuenta",
        "(desafio_hash IS NULL AND desafio_expira_en IS NULL) OR "
        "(desafio_hash IS NOT NULL AND desafio_expira_en IS NOT NULL)",
    )
    op.create_index(
        "ix_activaciones_cuenta_desafio_hash",
        "activaciones_cuenta",
        ["desafio_hash"],
        unique=True,
    )


def downgrade() -> None:
    conexion = op.get_bind()
    usuarios = sa.table(
        "usuarios",
        sa.column("contrasena_hash", sa.String()),
    )
    activaciones = sa.table(
        "activaciones_cuenta",
        sa.column("codigo_hash", sa.String()),
        sa.column("desafio_hash", sa.String()),
        sa.column("desafio_expira_en", sa.DateTime(timezone=True)),
    )
    tiene_contrasenas_nulas = conexion.scalar(
        sa.select(sa.func.count()).select_from(usuarios).where(
            usuarios.c.contrasena_hash.is_(None)
        )
    )
    tiene_codigos_nulos = conexion.scalar(
        sa.select(sa.func.count()).select_from(activaciones).where(
            activaciones.c.codigo_hash.is_(None)
        )
    )
    tiene_desafios = conexion.scalar(
        sa.select(sa.func.count()).select_from(activaciones).where(
            sa.or_(
                activaciones.c.desafio_hash.is_not(None),
                activaciones.c.desafio_expira_en.is_not(None),
            )
        )
    )
    if tiene_contrasenas_nulas or tiene_codigos_nulos or tiene_desafios:
        raise RuntimeError(
            "No se puede revertir: existen cuentas o invitaciones del nuevo flujo."
        )

    op.drop_index(
        "ix_activaciones_cuenta_desafio_hash",
        table_name="activaciones_cuenta",
    )
    op.drop_constraint(
        "ck_activaciones_cuenta_desafio_completo",
        "activaciones_cuenta",
        type_="check",
    )
    op.drop_column("activaciones_cuenta", "ultimo_reenvio_en")
    op.drop_column("activaciones_cuenta", "desafio_expira_en")
    op.drop_column("activaciones_cuenta", "desafio_hash")
    op.alter_column(
        "activaciones_cuenta",
        "codigo_hash",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.drop_constraint(
        "ck_usuarios_contrasena_hash_operador_pendiente",
        "usuarios",
        type_="check",
    )
    op.alter_column(
        "usuarios",
        "contrasena_hash",
        existing_type=sa.String(length=255),
        nullable=False,
    )
