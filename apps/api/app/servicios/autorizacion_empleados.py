"""Resuelve capacidades laborales por accion sin grants de operador activos."""

from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RolUsuario, Usuario


class AccionEmpleado(StrEnum):
    """Acciones del modulo que pueden asignarse por separado en el futuro."""

    LEER = "empleados.leer"
    REGISTRAR = "empleados.registrar"
    CAMBIAR_ESTADO = "empleados.cambiar_estado"


ACCIONES_EMPLEADO = frozenset(AccionEmpleado)


def resolver_capacidades_empleado(
    db: Session,
    *,
    usuario_id: int,
) -> frozenset[AccionEmpleado]:
    """Concede todas las acciones al OWNER y deja OPERADOR sin acceso inicial."""

    rol = db.scalar(select(Usuario.rol).where(Usuario.id == usuario_id))
    if rol == RolUsuario.OWNER.value:
        return ACCIONES_EMPLEADO
    # Los grants por usuario se conectaran aqui cuando exista su administracion.
    return frozenset()


def usuario_tiene_accion_empleado(
    db: Session,
    *,
    usuario_id: int,
    accion: AccionEmpleado,
) -> bool:
    """Evalua una accion de forma independiente para cada operacion."""

    return accion in resolver_capacidades_empleado(db, usuario_id=usuario_id)


__all__ = [
    "ACCIONES_EMPLEADO",
    "AccionEmpleado",
    "resolver_capacidades_empleado",
    "usuario_tiene_accion_empleado",
]
