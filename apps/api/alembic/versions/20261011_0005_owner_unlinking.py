"""Allow safe OWNER unlinking and retain one-time confirmation audit."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261011_0005"
down_revision: str | None = "20261011_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add roleless accounts and purpose-specific unlink confirmations."""

    op.alter_column(
        "usuarios",
        "rol",
        existing_type=sa.String(length=32),
        nullable=True,
    )
    op.drop_constraint(
        "ck_usuarios_contrasena_hash_pendiente_activacion",
        "usuarios",
        type_="check",
    )
    op.create_check_constraint(
        "ck_usuarios_contrasena_hash_pendiente_activacion",
        "usuarios",
        "contrasena_hash IS NOT NULL OR "
        "(rol IS NOT NULL AND rol IN ('ADMIN', 'OPERADOR') "
        "AND correo_verificado = false)",
    )
    op.alter_column(
        "cuentas_propietario",
        "contrasena_admin_hash",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.create_table(
        "desvinculaciones_propietario",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("cuenta_propietario_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("emitida_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumida_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidada_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "emitida_en < expira_en",
            name="ck_desvinculaciones_propietario_vigencia",
        ),
        sa.CheckConstraint(
            "consumida_en IS NULL OR invalidada_en IS NULL",
            name="ck_desvinculaciones_propietario_estado_final",
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name="fk_desvinculaciones_propietario_usuario_id_usuarios",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cuenta_propietario_id"],
            ["cuentas_propietario.id"],
            name="fk_desvinculaciones_propietario_cuenta_id_cuentas_propietario",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_desvinculaciones_propietario_token_hash",
        "desvinculaciones_propietario",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_desvinculaciones_propietario_usuario_emitida",
        "desvinculaciones_propietario",
        ["usuario_id", "emitida_en"],
    )
    op.create_index(
        "uq_desvinculaciones_propietario_pendiente",
        "desvinculaciones_propietario",
        ["usuario_id"],
        unique=True,
        postgresql_where=sa.text(
            "consumida_en IS NULL AND invalidada_en IS NULL"
        ),
    )


def downgrade() -> None:
    """Refuse data loss when roleless accounts or unlink history exist."""

    bind = op.get_bind()
    unsafe_rows = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM usuarios WHERE rol IS NULL) + "
            "(SELECT count(*) FROM cuentas_propietario "
            "WHERE contrasena_admin_hash IS NULL) + "
            "(SELECT count(*) FROM desvinculaciones_propietario)"
        )
    ).scalar_one()
    if unsafe_rows:
        raise RuntimeError(
            "No se puede revertir OWNER unlinking: existen cuentas sin rol, "
            "credenciales administrativas invalidadas o historial de enlaces."
        )

    op.drop_index(
        "uq_desvinculaciones_propietario_pendiente",
        table_name="desvinculaciones_propietario",
    )
    op.drop_index(
        "ix_desvinculaciones_propietario_usuario_emitida",
        table_name="desvinculaciones_propietario",
    )
    op.drop_index(
        "uq_desvinculaciones_propietario_token_hash",
        table_name="desvinculaciones_propietario",
    )
    op.drop_table("desvinculaciones_propietario")
    op.alter_column(
        "cuentas_propietario",
        "contrasena_admin_hash",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.drop_constraint(
        "ck_usuarios_contrasena_hash_pendiente_activacion",
        "usuarios",
        type_="check",
    )
    op.create_check_constraint(
        "ck_usuarios_contrasena_hash_pendiente_activacion",
        "usuarios",
        "contrasena_hash IS NOT NULL OR "
        "(rol IN ('ADMIN', 'OPERADOR') AND correo_verificado = false)",
    )
    op.alter_column(
        "usuarios",
        "rol",
        existing_type=sa.String(length=32),
        nullable=False,
    )
