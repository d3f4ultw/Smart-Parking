"""Modelos del journal global de eventos y sus concesiones SSE por usuario."""

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
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.core.database import Base


class EstadoEventosTiempoReal(Base):
    """Fila singleton que conserva el ultimo id aunque se depure el journal."""

    __tablename__ = "estado_eventos_tiempo_real"
    __table_args__ = (
        CheckConstraint(
            "id = 1",
            name="ck_estado_eventos_tiempo_real_singleton",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ultimo_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class EventoTiempoReal(Base):
    """Notificacion minima de un cambio persistido en el dominio."""

    __tablename__ = "eventos_tiempo_real"
    __table_args__ = (
        CheckConstraint(
            "tipo IN ('operador.creado', 'operador.actualizado')",
            name="ck_eventos_tiempo_real_tipo",
        ),
        Index("ix_eventos_tiempo_real_ocurrido_en", "ocurrido_en"),
        Index("ix_eventos_tiempo_real_tipo_id", "tipo", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    recurso_tipo: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="operador",
        server_default="operador",
    )
    recurso_id: Mapped[int] = mapped_column(Integer, nullable=False)
    operador_id = synonym("recurso_id")
    tipo: Mapped[str] = mapped_column(String(64), nullable=False)
    ocurrido_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ConexionSSEUsuario(Base):
    """Concesion efimera que limita streams simultaneos por usuario."""

    __tablename__ = "conexiones_sse_usuario"
    __table_args__ = (
        Index(
            "ix_conexiones_sse_usuario_usuario_abierta",
            "usuario_id",
            "abierta_en",
        ),
        Index(
            "ix_conexiones_sse_usuario_usuario_expira",
            "usuario_id",
            "expira_en",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    admin_usuario_id = synonym("usuario_id")
    abierta_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cerrada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Aliases internos durante la migracion de los tests que cubren los productores
# de eventos de OPERADOR. El mapeo y las tablas ya son los genericos nuevos.
EstadoEventosOperadores = EstadoEventosTiempoReal
EventoOperador = EventoTiempoReal
ConexionSSEAdmin = ConexionSSEUsuario
