from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.database import Base


class RolUsuario(StrEnum):
    """Roles canonicos reconocidos por el dominio de usuarios."""

    ADMIN = "ADMIN"
    OPERADOR = "OPERADOR"
    OWNER = "OWNER"


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        Index("ix_usuarios_correo", "correo", unique=True),
        Index(
            "uq_usuarios_owner_activo",
            "rol",
            unique=True,
            postgresql_where=text("rol = 'OWNER' AND esta_activo IS TRUE"),
        ),
        CheckConstraint(
            "contrasena_hash IS NOT NULL OR "
            "(rol IS NOT NULL AND rol IN ('ADMIN', 'OPERADOR') "
            "AND correo_verificado = false)",
            name="ck_usuarios_contrasena_hash_pendiente_activacion",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    nombre: Mapped[str | None] = mapped_column(String(100))
    apellido_paterno: Mapped[str | None] = mapped_column(String(100))
    apellido_materno: Mapped[str | None] = mapped_column(String(100))
    correo: Mapped[str] = mapped_column(String(320), nullable=False)
    contrasena_hash: Mapped[str | None] = mapped_column(String(255))
    rol: Mapped[str | None] = mapped_column(
        String(32).evaluates_none(),
        nullable=True,
        default=RolUsuario.ADMIN.value,
        server_default=text(f"'{RolUsuario.ADMIN.value}'"),
    )
    correo_verificado: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    debe_cambiar_contrasena: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    esta_activo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    creado_por_usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    creado_por: Mapped[Usuario | None] = relationship(
        remote_side=[id],
        foreign_keys=[creado_por_usuario_id],
    )

    @validates("rol")
    def validar_rol(self, _atributo: str, valor: str | None) -> str | None:
        """Acepta roles conocidos o el estado explicito sin rol."""

        if valor is None:
            return None
        if not isinstance(valor, str):
            raise ValueError("Rol de usuario no valido.")
        try:
            return RolUsuario(valor).value
        except ValueError as error:
            raise ValueError("Rol de usuario no valido.") from error
