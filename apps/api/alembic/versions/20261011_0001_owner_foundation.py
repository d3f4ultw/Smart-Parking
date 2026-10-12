"""Add the active OWNER uniqueness constraint."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261011_0001"
down_revision: str | None = "20261010_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Permite como maximo un OWNER activo sin requerir que exista uno."""

    op.create_index(
        "uq_usuarios_owner_activo",
        "usuarios",
        ["rol"],
        unique=True,
        postgresql_where=sa.text("rol = 'OWNER' AND esta_activo IS TRUE"),
    )


def downgrade() -> None:
    """Retira la restriccion sin modificar cuentas existentes."""

    op.drop_index("uq_usuarios_owner_activo", table_name="usuarios")
