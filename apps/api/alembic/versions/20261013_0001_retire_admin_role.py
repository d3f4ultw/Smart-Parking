"""Retire el rol ADMIN y sus restricciones activas."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261013_0001"
down_revision: str | None = "20261012_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_usuarios_contrasena_hash_pendiente_activacion",
        "usuarios",
        type_="check",
    )
    op.drop_constraint(
        "ck_cuentas_propietario_rol_anterior",
        "cuentas_propietario",
        type_="check",
    )
    op.drop_constraint(
        "ck_inscripciones_propietario_rol_anterior",
        "inscripciones_propietario",
        type_="check",
    )

    op.execute(
        sa.text(
            "UPDATE usuarios "
            "SET rol = NULL, esta_activo = false, debe_cambiar_contrasena = true "
            "WHERE rol = 'ADMIN'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE cuentas_propietario SET rol_anterior = NULL "
            "WHERE rol_anterior = 'ADMIN'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE inscripciones_propietario SET rol_anterior = NULL "
            "WHERE rol_anterior = 'ADMIN'"
        )
    )

    op.alter_column(
        "usuarios",
        "rol",
        existing_type=sa.String(length=32),
        server_default=None,
    )
    op.create_check_constraint(
        "ck_usuarios_rol_valido",
        "usuarios",
        "rol IS NULL OR rol IN ('OPERADOR', 'OWNER')",
    )
    op.create_check_constraint(
        "ck_usuarios_contrasena_hash_pendiente_activacion",
        "usuarios",
        "contrasena_hash IS NOT NULL OR "
        "(rol IS NOT NULL AND rol = 'OPERADOR' AND correo_verificado = false) OR "
        "(rol IS NULL AND esta_activo = false AND correo_verificado = false)",
    )
    op.create_check_constraint(
        "ck_cuentas_propietario_rol_anterior",
        "cuentas_propietario",
        "rol_anterior IS NULL OR rol_anterior = 'OPERADOR'",
    )
    op.create_check_constraint(
        "ck_inscripciones_propietario_rol_anterior",
        "inscripciones_propietario",
        "rol_anterior IS NULL OR rol_anterior = 'OPERADOR'",
    )
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conrelid = 'conexiones_sse_usuario'::regclass "
            "AND conname = 'conexiones_sse_admin_pkey') THEN "
            "ALTER TABLE conexiones_sse_usuario "
            "RENAME CONSTRAINT conexiones_sse_admin_pkey "
            "TO conexiones_sse_usuario_pkey; "
            "END IF; END $$"
        )
    )


def downgrade() -> None:
    op.drop_constraint("ck_usuarios_rol_valido", "usuarios", type_="check")
    op.drop_constraint(
        "ck_usuarios_contrasena_hash_pendiente_activacion",
        "usuarios",
        type_="check",
    )
    op.drop_constraint(
        "ck_cuentas_propietario_rol_anterior",
        "cuentas_propietario",
        type_="check",
    )
    op.drop_constraint(
        "ck_inscripciones_propietario_rol_anterior",
        "inscripciones_propietario",
        type_="check",
    )
    op.create_check_constraint(
        "ck_usuarios_contrasena_hash_pendiente_activacion",
        "usuarios",
        "contrasena_hash IS NOT NULL OR "
        "(rol IS NOT NULL AND rol IN ('ADMIN', 'OPERADOR') "
        "AND correo_verificado = false) OR "
        "(rol IS NULL AND esta_activo = false AND correo_verificado = false)",
    )
    op.create_check_constraint(
        "ck_cuentas_propietario_rol_anterior",
        "cuentas_propietario",
        "rol_anterior IS NULL OR rol_anterior IN ('ADMIN', 'OPERADOR')",
    )
    op.create_check_constraint(
        "ck_inscripciones_propietario_rol_anterior",
        "inscripciones_propietario",
        "rol_anterior IS NULL OR rol_anterior IN ('ADMIN', 'OPERADOR')",
    )
    op.alter_column(
        "usuarios",
        "rol",
        existing_type=sa.String(length=32),
        server_default=sa.text("'ADMIN'"),
    )
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conrelid = 'conexiones_sse_usuario'::regclass "
            "AND conname = 'conexiones_sse_usuario_pkey') THEN "
            "ALTER TABLE conexiones_sse_usuario "
            "RENAME CONSTRAINT conexiones_sse_usuario_pkey "
            "TO conexiones_sse_admin_pkey; "
            "END IF; END $$"
        )
    )
