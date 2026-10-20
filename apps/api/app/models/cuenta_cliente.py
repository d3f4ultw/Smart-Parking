"""Identidad de cliente independiente de usuarios y facturacion Stripe."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CuentaCliente(Base):
    """Cuenta publica de cliente sin permisos ni sesiones administrativas."""

    __tablename__ = "cuentas_clientes"
    __table_args__ = (
        Index(
            "uq_cuentas_clientes_correo_lower",
            text("lower(correo)"),
            unique=True,
        ),
        CheckConstraint(
            "char_length(btrim(nombre)) > 0",
            name="ck_cuentas_clientes_nombre_no_vacio",
        ),
        CheckConstraint(
            "char_length(btrim(apellido_paterno)) > 0",
            name="ck_cuentas_clientes_apellido_paterno_no_vacio",
        ),
        CheckConstraint(
            "apellido_materno IS NULL OR char_length(btrim(apellido_materno)) > 0",
            name="ck_cuentas_clientes_apellido_materno_no_vacio",
        ),
        CheckConstraint(
            "char_length(btrim(correo)) > 0",
            name="ck_cuentas_clientes_correo_no_vacio",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    apellido_paterno: Mapped[str] = mapped_column(String(100), nullable=False)
    apellido_materno: Mapped[str | None] = mapped_column(String(100), nullable=True)
    correo: Mapped[str] = mapped_column(String(320), nullable=False)
    contrasena_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    correo_verificado: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    esta_activa: Mapped[bool] = mapped_column(
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


__all__ = ["CuentaCliente"]
