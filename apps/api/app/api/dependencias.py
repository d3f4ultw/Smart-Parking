"""Dependencias reutilizables para proteger rutas de la API."""

import re
import secrets
from typing import Annotated, NoReturn

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import RolUsuario, Usuario
from app.servicios.autenticacion import obtener_usuario_por_token

DETALLE_SESION_NO_AUTENTICADA = "No autenticado"
CABECERA_NO_CACHE = {"Cache-Control": "no-store"}
_ESQUEMA_BEARER_VISION = HTTPBearer(auto_error=False)
_FORMATO_TOKEN_VISION = re.compile(r"[A-Za-z0-9_-]{43,}")


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


def exigir_personal(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> int:
    """Valida la sesion persistida de OWNER u OPERADOR."""

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

    if usuario is None or usuario.rol not in {
        RolUsuario.OWNER.value,
        RolUsuario.OPERADOR.value,
    }:
        db.rollback()
        _error_sesion_no_autenticada()

    usuario_id = usuario.id
    db.rollback()
    return usuario_id


def exigir_owner(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> int:
    """Valida la sesion vigente y exige el rol OWNER persistido."""

    response.headers.update(CABECERA_NO_CACHE)
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        db.rollback()
        _error_sesion_no_autenticada()

    try:
        usuario = obtener_usuario_por_token(db, token=token)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno",
            headers=CABECERA_NO_CACHE,
        ) from None

    if usuario is None:
        db.rollback()
        _error_sesion_no_autenticada()

    usuario_id = usuario.id
    es_owner = usuario.rol == RolUsuario.OWNER.value
    db.rollback()
    if not es_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado",
            headers=CABECERA_NO_CACHE,
        )
    return usuario_id


def _error_vision_no_autenticada() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado",
        headers={**CABECERA_NO_CACHE, "WWW-Authenticate": "Bearer"},
    )


def exigir_vision(
    response: Response,
    credenciales: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_ESQUEMA_BEARER_VISION),
    ],
) -> None:
    """Autoriza solo el bearer dedicado a la aplicacion Vision."""

    response.headers.update(CABECERA_NO_CACHE)
    configurado = get_settings().vision_bearer_token
    secreto = configurado.get_secret_value() if configurado is not None else ""
    if not _FORMATO_TOKEN_VISION.fullmatch(secreto):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La API de Vision no esta disponible",
            headers=CABECERA_NO_CACHE,
        )

    if (
        credenciales is None
        or credenciales.scheme.lower() != "bearer"
        or not credenciales.credentials.isascii()
        or not secrets.compare_digest(credenciales.credentials, secreto)
    ):
        _error_vision_no_autenticada()


__all__ = [
    "exigir_vision",
    "exigir_operador",
    "exigir_owner",
    "exigir_personal",
]
