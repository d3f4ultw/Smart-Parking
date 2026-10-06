"""Generalize the operator SSE journal and leases for authenticated users."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261004_0001"
down_revision = "20261003_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_eventos_operadores_ocurrido_en",
        table_name="eventos_operadores",
    )
    op.drop_index(
        "ix_eventos_operadores_operador_id",
        table_name="eventos_operadores",
    )
    op.drop_constraint(
        "ck_eventos_operadores_tipo",
        "eventos_operadores",
        type_="check",
    )
    op.drop_constraint(
        "eventos_operadores_operador_id_fkey",
        "eventos_operadores",
        type_="foreignkey",
    )
    op.rename_table("eventos_operadores", "eventos_tiempo_real")
    op.add_column(
        "eventos_tiempo_real",
        sa.Column(
            "recurso_tipo",
            sa.String(length=32),
            nullable=False,
            server_default="operador",
        ),
    )
    op.alter_column(
        "eventos_tiempo_real",
        "operador_id",
        new_column_name="recurso_id",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "eventos_tiempo_real",
        "tipo",
        type_=sa.String(length=64),
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_eventos_tiempo_real_tipo",
        "eventos_tiempo_real",
        "tipo IN ('operador.creado', 'operador.actualizado')",
    )
    op.create_index(
        "ix_eventos_tiempo_real_ocurrido_en",
        "eventos_tiempo_real",
        ["ocurrido_en"],
    )
    op.create_index(
        "ix_eventos_tiempo_real_tipo_id",
        "eventos_tiempo_real",
        ["tipo", "id"],
    )

    op.drop_index(
        "ix_conexiones_sse_admin_admin_abierta",
        table_name="conexiones_sse_admin",
    )
    op.drop_index(
        "ix_conexiones_sse_admin_admin_expira",
        table_name="conexiones_sse_admin",
    )
    op.drop_constraint(
        "conexiones_sse_admin_admin_usuario_id_fkey",
        "conexiones_sse_admin",
        type_="foreignkey",
    )
    op.rename_table("conexiones_sse_admin", "conexiones_sse_usuario")
    op.alter_column(
        "conexiones_sse_usuario",
        "admin_usuario_id",
        new_column_name="usuario_id",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.create_foreign_key(
        "fk_conexiones_sse_usuario_usuario_id_usuarios",
        "conexiones_sse_usuario",
        "usuarios",
        ["usuario_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_conexiones_sse_usuario_usuario_abierta",
        "conexiones_sse_usuario",
        ["usuario_id", "abierta_en"],
    )
    op.create_index(
        "ix_conexiones_sse_usuario_usuario_expira",
        "conexiones_sse_usuario",
        ["usuario_id", "expira_en"],
    )

    op.drop_constraint(
        "ck_estado_eventos_operadores_singleton",
        "estado_eventos_operadores",
        type_="check",
    )
    op.rename_table("estado_eventos_operadores", "estado_eventos_tiempo_real")
    op.create_check_constraint(
        "ck_estado_eventos_tiempo_real_singleton",
        "estado_eventos_tiempo_real",
        "id = 1",
    )


def downgrade() -> None:
    conexion = op.get_bind()
    referencias_no_operador = conexion.scalar(
        sa.text(
            "SELECT count(*) FROM eventos_tiempo_real WHERE recurso_tipo <> 'operador'"
        )
    )
    referencias_huerfanas = conexion.scalar(
        sa.text(
            "SELECT count(*) FROM eventos_tiempo_real e "
            "LEFT JOIN usuarios u ON u.id = e.recurso_id "
            "WHERE e.recurso_tipo = 'operador' AND u.id IS NULL"
        )
    )
    if referencias_no_operador or referencias_huerfanas:
        raise RuntimeError(
            "No se puede revertir: existen referencias incompatibles "
            "con el esquema anterior."
        )

    op.drop_constraint(
        "ck_estado_eventos_tiempo_real_singleton",
        "estado_eventos_tiempo_real",
        type_="check",
    )
    op.rename_table("estado_eventos_tiempo_real", "estado_eventos_operadores")
    op.create_check_constraint(
        "ck_estado_eventos_operadores_singleton",
        "estado_eventos_operadores",
        "id = 1",
    )

    op.drop_index(
        "ix_conexiones_sse_usuario_usuario_abierta",
        table_name="conexiones_sse_usuario",
    )
    op.drop_index(
        "ix_conexiones_sse_usuario_usuario_expira",
        table_name="conexiones_sse_usuario",
    )
    op.drop_constraint(
        "fk_conexiones_sse_usuario_usuario_id_usuarios",
        "conexiones_sse_usuario",
        type_="foreignkey",
    )
    op.rename_table("conexiones_sse_usuario", "conexiones_sse_admin")
    op.alter_column(
        "conexiones_sse_admin",
        "usuario_id",
        new_column_name="admin_usuario_id",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.create_foreign_key(
        "conexiones_sse_admin_admin_usuario_id_fkey",
        "conexiones_sse_admin",
        "usuarios",
        ["admin_usuario_id"],
        ["id"],
        ondelete="CASCADE",
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

    op.drop_index(
        "ix_eventos_tiempo_real_ocurrido_en",
        table_name="eventos_tiempo_real",
    )
    op.drop_index(
        "ix_eventos_tiempo_real_tipo_id",
        table_name="eventos_tiempo_real",
    )
    op.drop_constraint(
        "ck_eventos_tiempo_real_tipo",
        "eventos_tiempo_real",
        type_="check",
    )
    op.alter_column(
        "eventos_tiempo_real",
        "tipo",
        type_=sa.String(length=32),
        existing_type=sa.String(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "eventos_tiempo_real",
        "recurso_id",
        new_column_name="operador_id",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.drop_column("eventos_tiempo_real", "recurso_tipo")
    op.rename_table("eventos_tiempo_real", "eventos_operadores")
    op.create_foreign_key(
        "eventos_operadores_operador_id_fkey",
        "eventos_operadores",
        "usuarios",
        ["operador_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_eventos_operadores_tipo",
        "eventos_operadores",
        "tipo IN ('operador.creado', 'operador.actualizado')",
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
