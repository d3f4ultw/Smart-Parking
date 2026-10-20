"""Capacidades por accion del modulo de clientes y membresias."""

from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RolUsuario, Usuario


class AccionClienteMembresia(StrEnum):
    """Permisos independientes que podran asignarse a operadores mas adelante."""

    LEER = "clientes_membresias.leer"
    DETALLE = "clientes_membresias.detalle"


ACCIONES_CLIENTES_MEMBRESIAS = frozenset(AccionClienteMembresia)


def resolver_capacidades_cliente(
    db: Session,
    *,
    usuario_id: int,
) -> frozenset[AccionClienteMembresia]:
    """Concede lectura al OWNER; los operadores quedan sin grants iniciales."""

    rol = db.scalar(select(Usuario.rol).where(Usuario.id == usuario_id))
    if rol == RolUsuario.OWNER.value:
        return ACCIONES_CLIENTES_MEMBRESIAS
    return frozenset()


def usuario_tiene_accion_cliente(
    db: Session,
    *,
    usuario_id: int,
    accion: AccionClienteMembresia,
) -> bool:
    return accion in resolver_capacidades_cliente(db, usuario_id=usuario_id)


__all__ = [
    "ACCIONES_CLIENTES_MEMBRESIAS",
    "AccionClienteMembresia",
    "resolver_capacidades_cliente",
    "usuario_tiene_accion_cliente",
]
