"""Rutas HTTP para consumir activaciones de cuenta."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.esquemas.activaciones import (
    ESTADO_REENVIO_ACTIVACION,
    RespuestaActivacionManual,
    RespuestaPrevalidacionActivacion,
    RespuestaReenvioActivacion,
    SolicitudActivacionManual,
    SolicitudActivacionTemporal,
    SolicitudPrevalidacionActivacion,
    SolicitudReenvioActivacion,
)
from app.seguridad.activaciones import hash_token_activacion
from app.seguridad.contrasenas import (
    ContrasenaInvalidaError,
    ContrasenasNoCoincidenError,
)
from app.seguridad.correos import CorreoInvalidoError, normalizar_correo
from app.seguridad.limitador import limitador_activaciones
from app.servicios.activaciones import (
    ActivacionNoDisponible,
    DatosActivacionInvalidos,
    activar_cuenta_manual,
    activar_cuenta_temporal,
    prevalidar_activacion,
)

router = APIRouter(prefix="/api/autenticacion/activar", tags=["autenticacion"])
reenviar_router = APIRouter(
    prefix="/api/autenticacion/activacion",
    tags=["autenticacion"],
)
DETALLE_ACTIVACION_NO_DISPONIBLE = "Activacion no disponible"
DETALLE_DATOS_ACTIVACION_INVALIDOS = "Solicitud invalida"
DETALLE_DEMASIADOS_INTENTOS = "Demasiados intentos"
CODIGO_ACTIVACION_NO_DISPONIBLE = "ACTIVACION_NO_DISPONIBLE"
CODIGO_DATOS_ACTIVACION_INVALIDOS = "DATOS_ACTIVACION_INVALIDOS"
CABECERA_NO_CACHE = {"Cache-Control": "no-store"}
LOGGER = logging.getLogger(__name__)


def _error_activacion(
    *,
    status_code: int,
    detalle: str,
    codigo: str,
) -> HTTPException:
    """Construye un error publico sin revelar la causa interna."""

    return HTTPException(
        status_code=status_code,
        detail={"code": codigo, "message": detalle},
        headers=CABECERA_NO_CACHE,
    )


def _obtener_origen(request: Request) -> str:
    """Obtiene el origen de red sin confiar en cabeceras reenviadas."""

    return request.client.host if request.client is not None else "desconocido"


def _verificar_limite_activacion(
    request: Request,
    *,
    token: str,
    modo: str,
) -> None:
    """Aplica ambos limites antes de buscar la activacion en PostgreSQL."""

    huella_token = hash_token_activacion(token)
    if limitador_activaciones.permitir(_obtener_origen(request), huella_token):
        return

    LOGGER.warning("Rate limit de activacion alcanzado", extra={"modo": modo})
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=DETALLE_DEMASIADOS_INTENTOS,
        headers=CABECERA_NO_CACHE,
    )


@router.post("/manual", response_model=RespuestaActivacionManual)
def activar_manual(
    solicitud: SolicitudActivacionManual,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaActivacionManual:
    """Activa una cuenta con contrasena manual sin iniciar sesion."""

    response.headers.update(CABECERA_NO_CACHE)
    _verificar_limite_activacion(
        request,
        token=solicitud.token,
        modo="manual",
    )

    try:
        activar_cuenta_manual(
            db,
            token=solicitud.token,
            codigo=solicitud.codigo,
        )
    except ActivacionNoDisponible:
        LOGGER.warning("Activacion rechazada", extra={"modo": "manual"})
        raise _error_activacion(
            status_code=status.HTTP_404_NOT_FOUND,
            detalle=DETALLE_ACTIVACION_NO_DISPONIBLE,
            codigo=CODIGO_ACTIVACION_NO_DISPONIBLE,
        ) from None
    except DatosActivacionInvalidos:
        LOGGER.warning(
            "Activacion rechazada por credenciales", extra={"modo": "manual"}
        )
        raise _error_activacion(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detalle=DETALLE_DATOS_ACTIVACION_INVALIDOS,
            codigo=CODIGO_DATOS_ACTIVACION_INVALIDOS,
        ) from None
    except SQLAlchemyError:
        LOGGER.error(
            "Error interno de persistencia durante activacion",
            extra={"modo": "manual"},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno",
            headers=CABECERA_NO_CACHE,
        ) from None

    LOGGER.info("Activacion exitosa", extra={"modo": "manual"})
    return RespuestaActivacionManual(estado="activada")


@router.post("/temporal", response_model=RespuestaActivacionManual)
def activar_temporal(
    solicitud: SolicitudActivacionTemporal,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaActivacionManual:
    """Reemplaza la contrasena temporal sin iniciar sesion."""

    response.headers.update(CABECERA_NO_CACHE)
    _verificar_limite_activacion(
        request,
        token=solicitud.token,
        modo="temporal",
    )

    try:
        activar_cuenta_temporal(
            db,
            token=solicitud.token,
            codigo=solicitud.codigo,
            contrasena_temporal=solicitud.contrasena_temporal,
            nueva_contrasena=solicitud.nueva_contrasena,
            confirmar_contrasena=solicitud.confirmar_contrasena,
        )
    except ActivacionNoDisponible:
        LOGGER.warning("Activacion rechazada", extra={"modo": "temporal"})
        raise _error_activacion(
            status_code=status.HTTP_404_NOT_FOUND,
            detalle=DETALLE_ACTIVACION_NO_DISPONIBLE,
            codigo=CODIGO_ACTIVACION_NO_DISPONIBLE,
        ) from None
    except DatosActivacionInvalidos:
        LOGGER.warning(
            "Activacion rechazada por credenciales", extra={"modo": "temporal"}
        )
        raise _error_activacion(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detalle=DETALLE_DATOS_ACTIVACION_INVALIDOS,
            codigo=CODIGO_DATOS_ACTIVACION_INVALIDOS,
        ) from None
    except ContrasenaInvalidaError, ContrasenasNoCoincidenError:
        LOGGER.warning(
            "Activacion rechazada por politica de contrasena",
            extra={"modo": "temporal"},
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": CODIGO_DATOS_ACTIVACION_INVALIDOS,
                "message": DETALLE_DATOS_ACTIVACION_INVALIDOS,
            },
            headers=CABECERA_NO_CACHE,
        ) from None
    except SQLAlchemyError:
        LOGGER.error(
            "Error interno de persistencia durante activacion",
            extra={"modo": "temporal"},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno",
            headers=CABECERA_NO_CACHE,
        ) from None

    LOGGER.info("Activacion exitosa", extra={"modo": "temporal"})
    return RespuestaActivacionManual(estado="activada")


@reenviar_router.post(
    "/prevalidar",
    response_model=RespuestaPrevalidacionActivacion,
)
def prevalidar_activacion_endpoint(
    solicitud: SolicitudPrevalidacionActivacion,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaPrevalidacionActivacion:
    """Resuelve el modo de un token sin consumir ni modificar la activacion."""

    response.headers.update(CABECERA_NO_CACHE)
    _verificar_limite_activacion(
        request,
        token=solicitud.token,
        modo="prevalidacion",
    )

    try:
        modo = prevalidar_activacion(db, token=solicitud.token)
    except ActivacionNoDisponible:
        LOGGER.warning("Prevalidacion de activacion rechazada")
        raise _error_activacion(
            status_code=status.HTTP_404_NOT_FOUND,
            detalle=DETALLE_ACTIVACION_NO_DISPONIBLE,
            codigo=CODIGO_ACTIVACION_NO_DISPONIBLE,
        ) from None
    except SQLAlchemyError:
        LOGGER.error("Error interno de persistencia durante prevalidacion")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno",
            headers=CABECERA_NO_CACHE,
        ) from None

    return RespuestaPrevalidacionActivacion(modo=modo)


@reenviar_router.post(
    "/reenviar",
    response_model=RespuestaReenvioActivacion,
    status_code=status.HTTP_202_ACCEPTED,
)
def reenviar_activacion_endpoint(
    solicitud: SolicitudReenvioActivacion,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaReenvioActivacion:
    """Conserva el contrato generico sin emitir nuevas invitaciones legacy."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        normalizar_correo(solicitud.correo)
    except CorreoInvalidoError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Solicitud invalida",
            headers=CABECERA_NO_CACHE,
        ) from None
    del solicitud, db
    return RespuestaReenvioActivacion(estado=ESTADO_REENVIO_ACTIVACION)


__all__ = [
    "CODIGO_ACTIVACION_NO_DISPONIBLE",
    "CODIGO_DATOS_ACTIVACION_INVALIDOS",
    "DETALLE_ACTIVACION_NO_DISPONIBLE",
    "DETALLE_DATOS_ACTIVACION_INVALIDOS",
    "DETALLE_DEMASIADOS_INTENTOS",
    "activar_manual",
    "activar_temporal",
    "reenviar_activacion_endpoint",
    "reenviar_router",
    "router",
]
