"""Crea el esquema inicial de autenticacion de Smart Parking.

Revision ID: 20260926_0001
Revises:
Fecha de creacion: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260926_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=True),
        sa.Column("apellido_paterno", sa.String(length=100), nullable=True),
        sa.Column("apellido_materno", sa.String(length=100), nullable=True),
        sa.Column("correo", sa.String(length=320), nullable=False),
        sa.Column("contrasena_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "rol",
            sa.String(length=32),
            server_default=sa.text("'ADMIN'"),
            nullable=False,
        ),
        sa.Column(
            "correo_verificado",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "debe_cambiar_contrasena",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "esta_activo", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_usuarios"),
    )
    op.create_index("ix_usuarios_correo", "usuarios", ["correo"], unique=True)

    op.create_table(
        "activaciones_cuenta",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("codigo_hash", sa.String(length=255), nullable=False),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumido_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name="fk_activaciones_cuenta_usuario_id_usuarios",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activaciones_cuenta"),
    )
    op.create_index(
        "ix_activaciones_cuenta_usuario_id",
        "activaciones_cuenta",
        ["usuario_id"],
        unique=False,
    )
    op.create_index(
        "ix_activaciones_cuenta_token_hash",
        "activaciones_cuenta",
        ["token_hash"],
        unique=True,
    )

    op.create_table(
        "sesiones",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revocado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name="fk_sesiones_usuario_id_usuarios",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sesiones"),
    )
    op.create_index("ix_sesiones_usuario_id", "sesiones", ["usuario_id"], unique=False)
    op.create_index("ix_sesiones_token_hash", "sesiones", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_sesiones_token_hash", table_name="sesiones")
    op.drop_index("ix_sesiones_usuario_id", table_name="sesiones")
    op.drop_table("sesiones")

    op.drop_index("ix_activaciones_cuenta_token_hash", table_name="activaciones_cuenta")
    op.drop_index("ix_activaciones_cuenta_usuario_id", table_name="activaciones_cuenta")
    op.drop_table("activaciones_cuenta")

    op.drop_index("ix_usuarios_correo", table_name="usuarios")
    op.drop_table("usuarios")
