"""Dependencias de autenticacion y capacidad para el modulo de empleados."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.dependencias import CABECERA_NO_CACHE, exigir_personal
from app.core.database import get_db
from app.servicios.autorizacion_empleados import (
    AccionEmpleado,
    usuario_tiene_accion_empleado,
)


def exigir_accion_empleado(
    accion: AccionEmpleado,
) -> Callable[..., int]:
    """Crea una dependencia que valida la sesion y la accion requerida."""

    def verificar_accion(
        response: Response,
        db: Annotated[Session, Depends(get_db)],
        usuario_id: Annotated[int, Depends(exigir_personal)],
    ) -> int:
        response.headers.update(CABECERA_NO_CACHE)
        if not usuario_tiene_accion_empleado(
            db,
            usuario_id=usuario_id,
            accion=accion,
        ):
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso denegado",
                headers=CABECERA_NO_CACHE,
            )
        db.rollback()
        return usuario_id

    return verificar_accion


__all__ = ["exigir_accion_empleado"]
