"""Rutas autenticadas de consulta y actualizacion de cajones."""

from dataclasses import asdict
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencias import (
    CABECERA_NO_CACHE,
    exigir_personal,
)
from app.core.database import get_db
from app.esquemas.cajones import (
    RespuestaCajon,
    RespuestaListaCajones,
    RespuestaMutacionCajon,
    SolicitudEstadoOperativoCajon,
)
from app.servicios.cajones import (
    CajonNoEncontradoError,
    cambiar_estado_operativo,
    listar_cajones,
)
from app.servicios.eventos_operadores import obtener_marca_eventos
from app.servicios.vision import obtener_estado_vision

RUTA_CAJONES = "/api/cajones"
router = APIRouter(prefix=RUTA_CAJONES, tags=["cajones"])


def _error_no_encontrado() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Cajon no encontrado",
        headers=CABECERA_NO_CACHE,
    )


def _error_interno() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Error interno",
        headers=CABECERA_NO_CACHE,
    )


@router.get("", response_model=RespuestaListaCajones)
def listar_cajones_endpoint(
    response: Response,
    _usuario_id: Annotated[int, Depends(exigir_personal)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaListaCajones:
    """Lista todos los cajones y el high-water para iniciar SSE."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        marca_eventos, _primer_evento = obtener_marca_eventos(db)
        vision = obtener_estado_vision(db)
        cajones = listar_cajones(db, vision_desactualizada=vision["stale"])
    except SQLAlchemyError:
        db.rollback()
        _error_interno()
    return RespuestaListaCajones(
        cajones=[RespuestaCajon.model_validate(cajon) for cajon in cajones],
        cursor_eventos=str(marca_eventos),
        vision=vision,
    )


@router.patch(
    "/{cajon_id}/estado-operativo",
    response_model=RespuestaMutacionCajon,
)
def actualizar_estado_operativo_endpoint(
    cajon_id: Annotated[int, Path(ge=1)],
    solicitud: SolicitudEstadoOperativoCajon,
    response: Response,
    _usuario_id: Annotated[int, Depends(exigir_personal)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaMutacionCajon:
    """Actualiza solo el estado operativo para personal autenticado."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        resultado = cambiar_estado_operativo(
            db,
            cajon_id,
            estado=solicitud.estado,
            motivo=solicitud.motivo,
        )
    except CajonNoEncontradoError:
        _error_no_encontrado()
    except SQLAlchemyError:
        db.rollback()
        _error_interno()
    return RespuestaMutacionCajon(
        **asdict(resultado.cajon),
        cambio_aplicado=resultado.cambio_aplicado,
    )


__all__ = ["RUTA_CAJONES", "router"]
