"""Retira los ocho cajones heredados y habilita configuracion Vision dinamica."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261013_0002"
down_revision = "20261013_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    numeros = list(
        bind.execute(sa.text("SELECT numero FROM cajones ORDER BY numero")).scalars()
    )
    if numeros != list(range(1, 9)):
        raise RuntimeError(
            "No se eliminan cajones: se esperaba exactamente la semilla heredada 1-8."
        )

    bind.execute(
        sa.text("DELETE FROM eventos_tiempo_real WHERE recurso_tipo = 'cajon'")
    )
    bind.execute(sa.text("DELETE FROM cajones"))

    op.add_column(
        "cajones",
        sa.Column("vision_zone_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "cajones",
        sa.Column("poligono", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "cajones",
        sa.Column("activa", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.alter_column("cajones", "vision_zone_id", nullable=False)
    op.alter_column("cajones", "poligono", nullable=False)
    op.alter_column(
        "cajones",
        "numero",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )
    op.create_unique_constraint(
        "uq_cajones_vision_zone_id",
        "cajones",
        ["vision_zone_id"],
    )
    op.create_check_constraint(
        "ck_cajones_activos_con_poligono",
        "cajones",
        "NOT activa OR poligono IS NOT NULL",
    )

    op.create_table(
        "vision_configuration",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "revision", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "next_c_number",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("current_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_sequence", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint("id = 1", name="ck_vision_configuration_singleton"),
        sa.CheckConstraint("revision >= 0", name="ck_vision_configuration_revision"),
        sa.CheckConstraint(
            "next_c_number > 0",
            name="ck_vision_configuration_next_c_number",
        ),
        sa.CheckConstraint(
            "last_sequence >= 0", name="ck_vision_configuration_sequence"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vision_configuration"),
    )
    op.create_table(
        "vision_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_type", sa.String(length=24), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "char_length(request_digest) = 64",
            name="ck_vision_requests_digest_length",
        ),
        sa.PrimaryKeyConstraint("request_id", name="pk_vision_requests"),
    )
    op.execute(
        sa.text(
            "INSERT INTO vision_configuration "
            "(id, revision, next_c_number, last_sequence) VALUES (1, 0, 1, 0)"
        )
    )


def downgrade() -> None:
    raise RuntimeError(
        "La migracion Vision es forward-only; restaura la copia protegida para revertirla."
    )
