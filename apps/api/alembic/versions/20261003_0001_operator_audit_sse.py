"""Add operator creator attribution and the private ADMIN SSE journal."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261003_0001"
down_revision = "20261002_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usuarios",
        sa.Column("creado_por_usuario_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_usuarios_creado_por_usuario_id_usuarios",
        "usuarios",
        "usuarios",
        ["creado_por_usuario_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_usuarios_creado_por_usuario_id",
        "usuarios",
        ["creado_por_usuario_id"],
    )

    op.create_table(
        "estado_eventos_operadores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ultimo_id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_estado_eventos_operadores_singleton"),
    )
    op.execute(
        text("INSERT INTO estado_eventos_operadores (id, ultimo_id) VALUES (1, 0)")
    )

    op.create_table(
        "eventos_operadores",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "operador_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tipo", sa.String(length=32), nullable=False),
        sa.Column(
            "ocurrido_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "tipo IN ('operador.creado', 'operador.actualizado')",
            name="ck_eventos_operadores_tipo",
        ),
    )
    op.create_index(
        "ix_eventos_operadores_ocurrido_en",
        "eventos_operadores",
        ["ocurrido_en"],
    )
    op.create_index(
        "ix_eventos_operadores_operador_id",
        "eventos_operadores",
        ["operador_id"],
    )

    op.create_table(
        "conexiones_sse_admin",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "admin_usuario_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "abierta_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cerrada_en", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_conexiones_sse_admin_admin_abierta",
        "conexiones_sse_admin",
        ["admin_usuario_id", "abierta_en"],
    )
    op.create_index(
        "ix_conexiones_sse_admin_admin_expira",
        "conexiones_sse_admin",
        ["admin_usuario_id", "expira_en"],
    )


def downgrade() -> None:
    conexion = op.get_bind()
    existe_atribucion = conexion.execute(
        text(
            "SELECT 1 FROM usuarios "
            "WHERE creado_por_usuario_id IS NOT NULL LIMIT 1"
        )
    ).first()
    if existe_atribucion is not None:
        raise RuntimeError(
            "No se puede revertir: existen atribuciones de creacion de OPERADOR."
        )

    op.drop_table("conexiones_sse_admin")
    op.drop_table("eventos_operadores")
    op.drop_table("estado_eventos_operadores")
    op.drop_index("ix_usuarios_creado_por_usuario_id", table_name="usuarios")
    op.drop_constraint(
        "fk_usuarios_creado_por_usuario_id_usuarios",
        "usuarios",
        type_="foreignkey",
    )
    op.drop_column("usuarios", "creado_por_usuario_id")
