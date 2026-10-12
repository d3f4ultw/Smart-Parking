"""Persiste la autorizacion temporal de gestion inicial de OWNER."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SesionGestionPropietario(Base):
    """Guarda hashes de las credenciales y el lease del navegador autorizado."""

    __tablename__ = "sesiones_gestion_propietario"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente', 'activa', 'reemplazada', 'expirada')",
            name="ck_sesiones_gestion_propietario_estado",
        ),
        CheckConstraint(
            "intentos_apareamiento BETWEEN 0 AND 5",
            name="ck_sesiones_gestion_propietario_intentos",
        ),
        CheckConstraint(
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
        Index(
            "uq_sesiones_gestion_propietario_ticket_hash",
            "ticket_hash",
            unique=True,
        ),
        Index(
            "uq_sesiones_gestion_propietario_credencial",
            "credencial_hash",
            unique=True,
        ),
        Index(
            "uq_sesiones_gestion_propietario_activa",
            text("(1)"),
            unique=True,
            postgresql_where=text("estado IN ('pendiente', 'activa')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    estado: Mapped[str] = mapped_column(String(16), nullable=False)
    ticket_hash: Mapped[str | None] = mapped_column(String(64))
    codigo_apareamiento_hash: Mapped[str | None] = mapped_column(String(64))
    credencial_hash: Mapped[str | None] = mapped_column(String(64))
    intentos_apareamiento: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    creada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    reclamada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_latido_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preclaim_expira_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    terminada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
