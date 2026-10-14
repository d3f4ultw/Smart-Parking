"""API OWNER para leer y cambiar la modalidad del estacionamiento."""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencias import exigir_owner
from app.core.database import get_db
from app.esquemas.configuracion_estacionamiento import (
    RespuestaModalidadEstacionamiento,
    SolicitudCambiarAccesoEstacionamiento,
    SolicitudCambiarModalidadEstacionamiento,
)
from app.servicios.configuracion_estacionamiento import (
    AccesoEstacionamientoSuspendidoError,
    ConfiguracionDesactualizadaError,
    EstacionamientoSinModalidadError,
    ModalidadEstacionamientoInvalidaError,
    cambiar_estado_acceso_estacionamiento,
    cambiar_modalidad_estacionamiento,
    obtener_configuracion_estacionamiento,
)

RUTA_CONFIGURACION_MODALIDAD = "/api/admin/configuracion/modalidad"
RUTA_CONFIGURACION_ACCESO = "/api/admin/configuracion/acceso"
CABECERA_NO_CACHE = {"Cache-Control": "no-store"}

router = APIRouter(prefix=RUTA_CONFIGURACION_MODALIDAD, tags=["owner"])
router_acceso = APIRouter(prefix=RUTA_CONFIGURACION_ACCESO, tags=["owner"])


def _error_interno() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Error interno",
        headers=CABECERA_NO_CACHE,
    ) from None


@router.get("", response_model=RespuestaModalidadEstacionamiento)
def obtener_modalidad_endpoint(
    response: Response,
    _owner: Annotated[int, Depends(exigir_owner)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaModalidadEstacionamiento:
    """Devuelve la modalidad persistida sin revelar otros campos."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        configuracion = obtener_configuracion_estacionamiento(db)
    except SQLAlchemyError:
        _error_interno()

    return RespuestaModalidadEstacionamiento(
        modalidad=configuracion.modalidad if configuracion is not None else None,
        revision=configuracion.revision if configuracion is not None else 0,
        acceso_suspendido=(
            configuracion.acceso_suspendido if configuracion is not None else False
        ),
    )


@router.put("", response_model=RespuestaModalidadEstacionamiento)
def cambiar_modalidad_endpoint(
    solicitud: SolicitudCambiarModalidadEstacionamiento,
    response: Response,
    _owner: Annotated[int, Depends(exigir_owner)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaModalidadEstacionamiento:
    """Persiste el cambio mediante el servicio y su historial atómico."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        resultado = cambiar_modalidad_estacionamiento(
            db,
            solicitud.modalidad,
            revision_esperada=solicitud.revision_esperada,
        )
    except ConfiguracionDesactualizadaError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La configuración cambió. Actualiza los datos e intenta de nuevo.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except ModalidadEstacionamientoInvalidaError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La modalidad solicitada no es válida.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except AccesoEstacionamientoSuspendidoError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No se puede cambiar la modalidad mientras el acceso está suspendido."
            ),
            headers=CABECERA_NO_CACHE,
        ) from None
    except SQLAlchemyError:
        _error_interno()

    return RespuestaModalidadEstacionamiento(
        modalidad=resultado.configuracion.modalidad,
        revision=resultado.configuracion.revision,
        acceso_suspendido=resultado.configuracion.acceso_suspendido,
    )


@router_acceso.put("", response_model=RespuestaModalidadEstacionamiento)
def cambiar_acceso_endpoint(
    solicitud: SolicitudCambiarAccesoEstacionamiento,
    response: Response,
    _owner: Annotated[int, Depends(exigir_owner)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaModalidadEstacionamiento:
    """Suspende o reanuda el acceso sin cambiar la modalidad guardada."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        resultado = cambiar_estado_acceso_estacionamiento(
            db,
            solicitud.acceso_suspendido,
            revision_esperada=solicitud.revision_esperada,
        )
    except ConfiguracionDesactualizadaError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La configuración cambió. Actualiza los datos e intenta de nuevo.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except EstacionamientoSinModalidadError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configura una modalidad antes de suspender el acceso.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except SQLAlchemyError:
        _error_interno()

    configuracion = resultado.configuracion
    return RespuestaModalidadEstacionamiento(
        modalidad=configuracion.modalidad if configuracion is not None else None,
        revision=configuracion.revision if configuracion is not None else 0,
        acceso_suspendido=(
            configuracion.acceso_suspendido if configuracion is not None else False
        ),
    )


__all__ = [
    "RUTA_CONFIGURACION_ACCESO",
    "RUTA_CONFIGURACION_MODALIDAD",
    "router",
    "router_acceso",
]
