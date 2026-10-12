"""Rutas publicas para verificar y activar el primer OWNER."""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.esquemas.activaciones_propietario import (
    RespuestaEstadoDesafioPropietario,
    RespuestaInscripcionPropietario,
    SolicitudCanjearEnlacePropietario,
    SolicitudCompletarInscripcionPropietario,
)
from app.seguridad.activaciones import hash_token_activacion
from app.seguridad.contrasenas import ContrasenaInvalidaError
from app.seguridad.limitador import (
    MAXIMO_INTENTOS_POR_TOKEN,
    LimitadorActivaciones,
    limitador_activaciones,
)
from app.servicios.propietario import (
    DatosInscripcionPropietarioInvalidosError,
    InscripcionPropietarioNoDisponible,
    canjear_enlace_propietario,
    completar_inscripcion_propietario,
    obtener_datos_desafio_propietario,
)

RUTA_ACTIVACION_PROPIETARIO = "/api/autenticacion/activacion-propietario"
NOMBRE_COOKIE_DESAFIO_PROPIETARIO = "smart_parking_owner_activation_challenge"
PATH_COOKIE_DESAFIO_PROPIETARIO = RUTA_ACTIVACION_PROPIETARIO
CABECERAS_ACTIVACION = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}
limitador_desafios_propietario = LimitadorActivaciones(
    limite_token=MAXIMO_INTENTOS_POR_TOKEN,
)
router = APIRouter(prefix=RUTA_ACTIVACION_PROPIETARIO, tags=["activacion-propietario"])


def _origen(request: Request) -> str:
    """Usa el origen de red observado por ASGI, no cabeceras reenviadas."""

    return request.client.host if request.client is not None else "desconocido"


def _error_no_disponible() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Activación no disponible",
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
    solicitud: SolicitudCanjearEnlacePropietario,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Cambia un enlace vigente por una cookie temporal de activacion."""

    response.headers.update(CABECERAS_ACTIVACION)
    if not limitador_activaciones.permitir_origen(_origen(request)):
        _error_limite()
    try:
        resultado = canjear_enlace_propietario(
            db,
            token=solicitud.token.get_secret_value(),
            duracion_desafio_minutos=get_settings().activation_challenge_ttl_minutes,
        )
    except InscripcionPropietarioNoDisponible:
        _error_no_disponible()
    except SQLAlchemyError:
        _error_interno()

    settings = get_settings()
    response.set_cookie(
        key=NOMBRE_COOKIE_DESAFIO_PROPIETARIO,
        value=resultado.token,
        max_age=settings.activation_challenge_ttl_minutes * 60,
        path=PATH_COOKIE_DESAFIO_PROPIETARIO,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/desafio", response_model=RespuestaEstadoDesafioPropietario)
def estado_desafio(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaEstadoDesafioPropietario:
    """Valida la cookie y devuelve el nombre solo para una cuenta de retorno."""

    response.headers.update(CABECERAS_ACTIVACION)
    token = request.cookies.get(NOMBRE_COOKIE_DESAFIO_PROPIETARIO)
    if token and not limitador_desafios_propietario.permitir(
        _origen(request), hash_token_activacion(token)
    ):
        _error_limite()
    try:
        datos_desafio = obtener_datos_desafio_propietario(
            db,
            token_desafio=token,
        )
    except SQLAlchemyError:
        _error_interno()
    return RespuestaEstadoDesafioPropietario(
        valido=datos_desafio.tipo_cuenta is not None,
        tipo_cuenta=datos_desafio.tipo_cuenta,
        nombre=datos_desafio.nombre,
        apellido_paterno=datos_desafio.apellido_paterno,
        apellido_materno=datos_desafio.apellido_materno,
        expira_en=datos_desafio.expira_en,
    )


@router.post(
    "/completar",
    response_model=RespuestaInscripcionPropietario,
)
def completar_inscripcion(
    solicitud: SolicitudCompletarInscripcionPropietario,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaInscripcionPropietario:
    """Confirma correo y cambia el rol en la misma transaccion."""

    response.headers.update(CABECERAS_ACTIVACION)
    token = request.cookies.get(NOMBRE_COOKIE_DESAFIO_PROPIETARIO)
    if token and not limitador_desafios_propietario.permitir(
        _origen(request), hash_token_activacion(token)
    ):
        _error_limite()
    try:
        completar_inscripcion_propietario(
            db,
            token_desafio=token,
            contrasena_admin=solicitud.contrasena_admin.get_secret_value(),
            confirmar_contrasena_admin=(
                solicitud.confirmar_contrasena_admin.get_secret_value()
            ),
            contrasena_login=(
                solicitud.contrasena_login.get_secret_value()
                if solicitud.contrasena_login is not None
                else None
            ),
            confirmar_contrasena_login=(
                solicitud.confirmar_contrasena_login.get_secret_value()
                if solicitud.confirmar_contrasena_login is not None
                else None
            ),
            nombre=solicitud.nombre,
            apellido_paterno=solicitud.apellido_paterno,
            apellido_materno=solicitud.apellido_materno,
        )
    except InscripcionPropietarioNoDisponible:
        _error_no_disponible()
    except ContrasenaInvalidaError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
            headers=CABECERAS_ACTIVACION,
        ) from None
    except DatosInscripcionPropietarioInvalidosError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Nombre y apellido paterno son obligatorios y cada campo "
                "debe contener hasta 100 caracteres válidos."
            ),
            headers=CABECERAS_ACTIVACION,
        ) from None
    except SQLAlchemyError:
        _error_interno()

    settings = get_settings()
    response.delete_cookie(
        key=NOMBRE_COOKIE_DESAFIO_PROPIETARIO,
        path=PATH_COOKIE_DESAFIO_PROPIETARIO,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return RespuestaInscripcionPropietario(estado="owner_activado")


__all__ = [
    "CABECERAS_ACTIVACION",
    "NOMBRE_COOKIE_DESAFIO_PROPIETARIO",
    "PATH_COOKIE_DESAFIO_PROPIETARIO",
    "RUTA_ACTIVACION_PROPIETARIO",
    "limitador_desafios_propietario",
    "router",
]
