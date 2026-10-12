"""Persist the temporary OWNER Web management session lease."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261011_0004"
down_revision: str | None = "20261011_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Adds session state without changing users or OWNER enrollments."""

    op.create_table(
        "sesiones_gestion_propietario",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("estado", sa.String(length=16), nullable=False),
        sa.Column("ticket_hash", sa.String(length=64), nullable=True),
        sa.Column("codigo_apareamiento_hash", sa.String(length=64), nullable=True),
        sa.Column("credencial_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "intentos_apareamiento",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "creada_en",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reclamada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_latido_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("preclaim_expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminada_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('pendiente', 'activa', 'reemplazada', 'expirada')",
            name="ck_sesiones_gestion_propietario_estado",
        ),
        sa.CheckConstraint(
            "intentos_apareamiento BETWEEN 0 AND 5",
            name="ck_sesiones_gestion_propietario_intentos",
        ),
        sa.CheckConstraint(
            "(estado = 'pendiente' AND ticket_hash IS NOT NULL "
            "AND codigo_apareamiento_hash IS NOT NULL AND credencial_hash IS NULL "
            "AND ultimo_latido_en IS NULL AND terminada_en IS NULL) OR "
            "(estado = 'activa' AND ticket_hash IS NOT NULL "
            "AND codigo_apareamiento_hash IS NULL AND credencial_hash IS NOT NULL "
            "AND reclamada_en IS NOT NULL AND ultimo_latido_en IS NOT NULL "
            "AND terminada_en IS NULL) OR "
            "(estado IN ('reemplazada', 'expirada') AND ticket_hash IS NULL "
            "AND codigo_apareamiento_hash IS NULL AND credencial_hash IS NULL "
            "AND terminada_en IS NOT NULL)",
            name="ck_sesiones_gestion_propietario_credenciales_estado",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_sesiones_gestion_propietario_ticket_hash",
        "sesiones_gestion_propietario",
        ["ticket_hash"],
        unique=True,
    )
    op.create_index(
        "uq_sesiones_gestion_propietario_credencial",
        "sesiones_gestion_propietario",
        ["credencial_hash"],
        unique=True,
    )
    op.create_index(
        "uq_sesiones_gestion_propietario_activa",
        "sesiones_gestion_propietario",
        [sa.text("(1)")],
        unique=True,
        postgresql_where=sa.text("estado IN ('pendiente', 'activa')"),
    )


def downgrade() -> None:
    """Drops only the temporary management-session records."""

    op.drop_index(
        "uq_sesiones_gestion_propietario_activa",
        table_name="sesiones_gestion_propietario",
    )
    op.drop_index(
        "uq_sesiones_gestion_propietario_credencial",
        table_name="sesiones_gestion_propietario",
    )
    op.drop_index(
        "uq_sesiones_gestion_propietario_ticket_hash",
        table_name="sesiones_gestion_propietario",
    )
    op.drop_table("sesiones_gestion_propietario")
