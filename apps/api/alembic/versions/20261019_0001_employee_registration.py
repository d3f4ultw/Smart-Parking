"""Create the employee directory linked to shared employee shifts."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261019_0001"
down_revision = "20261018_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "empleados",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("configuracion_estacionamiento_id", sa.Integer(), nullable=False),
        sa.Column("turno_empleado_id", sa.BigInteger(), nullable=False),
        sa.Column("nombres", sa.String(length=100), nullable=False),
        sa.Column("apellido_paterno", sa.String(length=100), nullable=False),
        sa.Column("apellido_materno", sa.String(length=100), nullable=True),
        sa.Column(
            "esta_activo",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "revision_estado",
            sa.BigInteger(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("clave_solicitud", sa.Uuid(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "char_length(btrim(nombres)) > 0",
            name="ck_empleados_nombres_no_vacios",
        ),
        sa.CheckConstraint(
            "char_length(btrim(apellido_paterno)) > 0",
            name="ck_empleados_apellido_paterno_no_vacio",
        ),
        sa.CheckConstraint(
            "apellido_materno IS NULL OR char_length(btrim(apellido_materno)) > 0",
            name="ck_empleados_apellido_materno_no_vacio",
        ),
        sa.CheckConstraint(
            "revision_estado > 0",
            name="ck_empleados_revision_positiva",
        ),
        sa.ForeignKeyConstraint(
            ["configuracion_estacionamiento_id", "turno_empleado_id"],
            [
                "turnos_empleados.configuracion_estacionamiento_id",
                "turnos_empleados.id",
            ],
            name="fk_empleados_turno_configuracion",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_empleados"),
        sa.UniqueConstraint(
            "configuracion_estacionamiento_id",
            "id",
            name="uq_empleados_configuracion_id_id",
        ),
        sa.UniqueConstraint(
            "clave_solicitud",
            name="uq_empleados_clave_solicitud",
        ),
    )
    op.execute(
        sa.text(
            "CREATE FUNCTION impedir_cambio_id_empleado() "
            "RETURNS trigger AS $$ BEGIN "
            "IF NEW.id IS DISTINCT FROM OLD.id THEN "
            "RAISE EXCEPTION 'El ID del empleado es inmutable' "
            "USING ERRCODE = '22000'; "
            "END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_empleados_id_inmutable "
            "BEFORE UPDATE OF id ON empleados "
            "FOR EACH ROW EXECUTE FUNCTION impedir_cambio_id_empleado()"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM empleados) THEN "
            "RAISE EXCEPTION 'No se pueden retirar empleados registrados'; "
            "END IF; END; $$"
        )
    )
    op.drop_table("empleados")
    op.execute(sa.text("DROP FUNCTION impedir_cambio_id_empleado()"))
