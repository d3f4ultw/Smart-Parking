"""Preserve the historical migration revision without creating a directory."""

from __future__ import annotations

revision = "20261010_0002"
down_revision = "20261010_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Retain this revision identifier for databases already on the chain."""


def downgrade() -> None:
    """There is no schema change in this retired revision."""

