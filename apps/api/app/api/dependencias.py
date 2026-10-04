"""Dependencias reutilizables para proteger rutas de la API."""

from typing import Annotated, NoReturn

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import RolUsuario, Usuario
from app.servicios.autenticacion import obtener_usuario_por_token

DETALLE_SESION_NO_AUTENTICADA = "No autenticado"
CABECERA_NO_CACHE = {"Cache-Control": "no-store"}


def _error_sesion_no_autenticada() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=DETALLE_SESION_NO_AUTENTICADA,
        headers=CABECERA_NO_CACHE,
    )


def exigir_operador(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> Usuario:
    """Devuelve el OPERADOR actual si su sesión y cuenta siguen siendo válidas."""

    response.headers.update(CABECERA_NO_CACHE)
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        db.rollback()
        _error_sesion_no_autenticada()

    try:
        usuario = obtener_usuario_por_token(db, token=token)
    except SQLAlchemyError:
        db.rollback()
        _error_sesion_no_autenticada()

    if usuario is None or usuario.rol != RolUsuario.OPERADOR.value:
        db.rollback()
        _error_sesion_no_autenticada()

    return usuario


__all__ = ["exigir_operador"]
