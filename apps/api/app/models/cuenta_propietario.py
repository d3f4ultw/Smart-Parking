from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CuentaPropietario(Base):
    """Guarda la credencial administrativa separada y el rol previo del OWNER."""

    __tablename__ = "cuentas_propietario"
    __table_args__ = (
        Index("uq_cuentas_propietario_usuario_id", "usuario_id", unique=True),
        CheckConstraint(
            "rol_anterior IS NULL OR rol_anterior IN ('ADMIN', 'OPERADOR')",
            name="ck_cuentas_propietario_rol_anterior",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey(
            "usuarios.id",
            name="fk_cuentas_propietario_usuario_id_usuarios",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    contrasena_admin_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    rol_anterior: Mapped[str | None] = mapped_column(String(32))
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

