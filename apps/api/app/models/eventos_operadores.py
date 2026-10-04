"""Modelos para la bitacora temporal y las concesiones SSE de ADMIN."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EstadoEventosOperadores(Base):
    """Fila singleton que conserva el ultimo id aunque se depure la bitacora."""

    __tablename__ = "estado_eventos_operadores"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_estado_eventos_operadores_singleton"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ultimo_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class EventoOperador(Base):
    """Cambio ADMIN-visible persistido junto con la mutacion del operador."""

    __tablename__ = "eventos_operadores"
    __table_args__ = (
        CheckConstraint(
            "tipo IN ('operador.creado', 'operador.actualizado')",
            name="ck_eventos_operadores_tipo",
        ),
        Index("ix_eventos_operadores_ocurrido_en", "ocurrido_en"),
        Index("ix_eventos_operadores_operador_id", "operador_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    operador_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    tipo: Mapped[str] = mapped_column(String(32), nullable=False)
    ocurrido_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ConexionSSEAdmin(Base):
    """Concesion efimera que limita streams simultaneos por ADMIN."""

    __tablename__ = "conexiones_sse_admin"
    __table_args__ = (
        Index(
            "ix_conexiones_sse_admin_admin_abierta",
            "admin_usuario_id",
            "abierta_en",
        ),
        Index("ix_conexiones_sse_admin_admin_expira", "admin_usuario_id", "expira_en"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    admin_usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    abierta_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cerrada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
