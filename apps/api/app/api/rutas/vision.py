"""Rutas de servicio autenticadas para la aplicacion Vision."""

from typing import Annotated, NoReturn

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencias import CABECERA_NO_CACHE, exigir_vision
from app.core.database import get_db
from app.esquemas.vision import (
    RespuestaAceptacionVision,
    RespuestaConfiguracionVision,
    RespuestaSesionVision,
    SolicitudConfiguracionVision,
    SolicitudObservacionesVision,
    SolicitudSecuenciaVision,
)
from app.servicios.vision import (
    VisionConfiguracionError,
    VisionConflictoError,
    cargar_configuracion_vision,
    guardar_configuracion_vision,
    iniciar_sesion_vision,
    recibir_heartbeat_vision,
    recibir_observaciones_vision,
)

RUTA_VISION = "/api/vision"
router = APIRouter(
    prefix=RUTA_VISION,
    tags=["vision"],
    dependencies=[Depends(exigir_vision)],
)


def _error_interno() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Error interno",
        headers=CABECERA_NO_CACHE,
    )


def _traducir_error(error: ValueError) -> NoReturn:
    codigo = (
        status.HTTP_409_CONFLICT
        if isinstance(error, VisionConflictoError)
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    raise HTTPException(
        status_code=codigo,
        detail=str(error),
        headers=CABECERA_NO_CACHE,
    ) from None


@router.get("/configuration", response_model=RespuestaConfiguracionVision)
def obtener_configuracion(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaConfiguracionVision:
    response.headers.update(CABECERA_NO_CACHE)
    try:
        return RespuestaConfiguracionVision.model_validate(
            cargar_configuracion_vision(db)
        )
    except SQLAlchemyError:
        db.rollback()
        _error_interno()


@router.put("/configuration", response_model=RespuestaConfiguracionVision)
def guardar_configuracion(
    solicitud: SolicitudConfiguracionVision,
    response: Response,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaConfiguracionVision:
    response.headers.update(CABECERA_NO_CACHE)
    try:
        resultado = guardar_configuracion_vision(db, solicitud)
    except (VisionConflictoError, VisionConfiguracionError) as error:
        _traducir_error(error)
    except SQLAlchemyError:
        db.rollback()
        _error_interno()
    hub = getattr(request.app.state, "vision_frame_hub", None)
    if hub is not None:
        anyio.from_thread.run(hub.actualizar_revision, resultado["revision"])
    return RespuestaConfiguracionVision.model_validate(resultado)


@router.post("/sessions", response_model=RespuestaSesionVision)
async def iniciar_sesion(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaSesionVision:
    response.headers.update(CABECERA_NO_CACHE)
    try:
        resultado = RespuestaSesionVision.model_validate(iniciar_sesion_vision(db))
        hub = getattr(request.app.state, "vision_frame_hub", None)
        if hub is not None:
            await hub.nueva_sesion(resultado.session_id, resultado.revision)
        return resultado
    except SQLAlchemyError:
        db.rollback()
        _error_interno()


@router.post("/heartbeat", response_model=RespuestaAceptacionVision)
def recibir_heartbeat(
    solicitud: SolicitudSecuenciaVision,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaAceptacionVision:
    response.headers.update(CABECERA_NO_CACHE)
    try:
        resultado = recibir_heartbeat_vision(db, solicitud)
    except (VisionConflictoError, VisionConfiguracionError) as error:
        _traducir_error(error)
    except SQLAlchemyError:
        db.rollback()
        _error_interno()
    return RespuestaAceptacionVision.model_validate(resultado)


@router.post("/observations", response_model=RespuestaAceptacionVision)
def recibir_observaciones(
    solicitud: SolicitudObservacionesVision,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaAceptacionVision:
    response.headers.update(CABECERA_NO_CACHE)
    try:
        resultado = recibir_observaciones_vision(db, solicitud)
    except (VisionConflictoError, VisionConfiguracionError) as error:
        _traducir_error(error)
    except SQLAlchemyError:
        db.rollback()
        _error_interno()
    return RespuestaAceptacionVision.model_validate(resultado)


__all__ = ["RUTA_VISION", "router"]
