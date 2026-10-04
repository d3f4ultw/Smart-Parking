"""Rutas publicas para el enlace de primera activacion OPERADOR."""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.esquemas.activaciones_operador import (
    RespuestaCompletarActivacionOperador,
    RespuestaEstadoDesafioOperador,
    SolicitudCanjearEnlaceOperador,
    SolicitudCompletarActivacionOperador,
)
from app.seguridad.activaciones import hash_token_activacion
from app.seguridad.contrasenas import ContrasenaInvalidaError
from app.seguridad.limitador import (
    MAXIMO_INTENTOS_POR_TOKEN,
    LimitadorActivaciones,
    limitador_activaciones,
)
from app.servicios.activaciones_operador import (
    ActivacionOperadorNoDisponible,
    canjear_enlace_operador,
    completar_activacion_operador,
    verificar_desafio_operador,
)

RUTA_ACTIVACION_OPERADOR = "/api/autenticacion/activacion-operador"
NOMBRE_COOKIE_DESAFIO = "smart_parking_activation_challenge"
PATH_COOKIE_DESAFIO = RUTA_ACTIVACION_OPERADOR
DETALLE_ACTIVACION_NO_DISPONIBLE = "Activación no disponible"
CABECERAS_ACTIVACION = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}
limitador_desafios_operador = LimitadorActivaciones(
    limite_token=MAXIMO_INTENTOS_POR_TOKEN,
)

router = APIRouter(prefix=RUTA_ACTIVACION_OPERADOR, tags=["activacion-operador"])


def _origen(request: Request) -> str:
    """Usa solo el origen de red observado por ASGI, sin confiar en proxies."""

    return request.client.host if request.client is not None else "desconocido"


def _error_no_disponible() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=DETALLE_ACTIVACION_NO_DISPONIBLE,
        headers=CABECERAS_ACTIVACION,
    )


def _error_limite() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Demasiados intentos",
        headers=CABECERAS_ACTIVACION,
    )


def _error_interno() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Error interno",
        headers=CABECERAS_ACTIVACION,
    )


@router.post("/enlace", status_code=status.HTTP_204_NO_CONTENT)
def canjear_enlace(
    solicitud: SolicitudCanjearEnlaceOperador,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Cambia el token vigente por una cookie temporal HttpOnly."""

    response.headers.update(CABECERAS_ACTIVACION)
    huella_token = hash_token_activacion(solicitud.token)
    if not limitador_activaciones.permitir(_origen(request), huella_token):
        _error_limite()

    try:
        resultado = canjear_enlace_operador(
            db,
            token=solicitud.token,
            duracion_desafio_minutos=get_settings().activation_challenge_ttl_minutes,
        )
    except ActivacionOperadorNoDisponible:
        _error_no_disponible()
    except SQLAlchemyError:
        _error_interno()

    settings = get_settings()
    response.set_cookie(
        key=NOMBRE_COOKIE_DESAFIO,
        value=resultado.token,
        max_age=settings.activation_challenge_ttl_minutes * 60,
        path=PATH_COOKIE_DESAFIO,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/desafio", response_model=RespuestaEstadoDesafioOperador)
def estado_desafio(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaEstadoDesafioOperador:
    """Devuelve solo si la cookie corresponde al desafio actual y vigente."""

    response.headers.update(CABECERAS_ACTIVACION)
    token_desafio = request.cookies.get(NOMBRE_COOKIE_DESAFIO)
    try:
        valido = verificar_desafio_operador(db, token_desafio=token_desafio)
    except SQLAlchemyError:
        _error_interno()
    return RespuestaEstadoDesafioOperador(valido=valido)


@router.post(
    "/completar",
    response_model=RespuestaCompletarActivacionOperador,
)
def completar_activacion(
    solicitud: SolicitudCompletarActivacionOperador,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaCompletarActivacionOperador:
    """Completa la primera contrasena y no crea una sesion autenticada."""

    response.headers.update(CABECERAS_ACTIVACION)
    token_desafio = request.cookies.get(NOMBRE_COOKIE_DESAFIO)
    if token_desafio and not limitador_desafios_operador.permitir(
        _origen(request),
        hash_token_activacion(token_desafio),
    ):
        _error_limite()

    try:
        completar_activacion_operador(
            db,
            token_desafio=token_desafio,
            nueva_contrasena=solicitud.nueva_contrasena,
        )
    except ActivacionOperadorNoDisponible:
        _error_no_disponible()
    except ContrasenaInvalidaError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
            headers=CABECERAS_ACTIVACION,
        ) from None
    except SQLAlchemyError:
        _error_interno()

    settings = get_settings()
    response.delete_cookie(
        key=NOMBRE_COOKIE_DESAFIO,
        path=PATH_COOKIE_DESAFIO,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return RespuestaCompletarActivacionOperador(estado="cuenta_activada")


__all__ = [
    "CABECERAS_ACTIVACION",
    "NOMBRE_COOKIE_DESAFIO",
    "PATH_COOKIE_DESAFIO",
    "RUTA_ACTIVACION_OPERADOR",
    "limitador_desafios_operador",
    "router",
]
