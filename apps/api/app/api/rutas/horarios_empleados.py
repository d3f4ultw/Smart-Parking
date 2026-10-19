"""Rutas OWNER para leer y modificar los turnos compartidos de empleados."""

from datetime import time
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencias import exigir_owner
from app.core.database import get_db
from app.esquemas.horarios_empleados import (
    RespuestaHorariosEmpleados,
    SolicitudCambiarHorariosEmpleados,
    TurnoEmpleadoRespuesta,
)
from app.models import CodigoTurnoEmpleado
from app.servicios.horarios_empleados import (
    ConfiguracionHorariosNoDisponibleError,
    HorariosEmpleadosDTO,
    RevisionHorariosDesactualizadaError,
    TurnosEmpleadosIncompletosError,
    cambiar_horarios_empleados,
    obtener_horarios_empleados,
)

RUTA_HORARIOS_EMPLEADOS = "/api/admin/configuracion/horarios-empleados"
CABECERA_NO_CACHE = {"Cache-Control": "no-store"}

router = APIRouter(prefix=RUTA_HORARIOS_EMPLEADOS, tags=["owner"])


def _error_interno(db: Session) -> NoReturn:
    db.rollback()
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Error interno",
        headers=CABECERA_NO_CACHE,
    ) from None


def _formatear_hora(valor: time | None) -> str | None:
    return valor.strftime("%H:%M") if valor is not None else None


def _crear_respuesta(horarios: HorariosEmpleadosDTO) -> RespuestaHorariosEmpleados:
    return RespuestaHorariosEmpleados(
        revision=horarios.revision,
        zona_horaria=horarios.zona_horaria,
        turnos=[
            TurnoEmpleadoRespuesta(
                id=turno.id,
                codigo=turno.codigo,
                nombre=turno.nombre,
                hora_inicio=_formatear_hora(turno.hora_inicio),
                hora_fin=_formatear_hora(turno.hora_fin),
            )
            for turno in horarios.turnos
        ],
    )


def _error_horarios_no_disponibles() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "Los horarios solo están disponibles en modalidades Empresarial y Mixta."
        ),
        headers=CABECERA_NO_CACHE,
    ) from None


@router.get("", response_model=RespuestaHorariosEmpleados)
def obtener_horarios_empleados_endpoint(
    response: Response,
    _owner: Annotated[int, Depends(exigir_owner)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaHorariosEmpleados:
    """Devuelve los horarios solo al Dueño en una modalidad elegible."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        return _crear_respuesta(obtener_horarios_empleados(db))
    except ConfiguracionHorariosNoDisponibleError:
        _error_horarios_no_disponibles()
    except TurnosEmpleadosIncompletosError:
        _error_interno(db)
    except SQLAlchemyError:
        _error_interno(db)


@router.put("", response_model=RespuestaHorariosEmpleados)
def cambiar_horarios_empleados_endpoint(
    solicitud: SolicitudCambiarHorariosEmpleados,
    response: Response,
    _owner: Annotated[int, Depends(exigir_owner)],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaHorariosEmpleados:
    """Guarda los tres horarios juntos sin aceptar horas para Sin restricción."""

    response.headers.update(CABECERA_NO_CACHE)
    turnos = solicitud.turnos
    horarios = {
        CodigoTurnoEmpleado.MATUTINO: (
            time.fromisoformat(turnos.matutino.hora_inicio)
            if turnos.matutino.hora_inicio is not None
            else None,
            time.fromisoformat(turnos.matutino.hora_fin)
            if turnos.matutino.hora_fin is not None
            else None,
        ),
        CodigoTurnoEmpleado.VESPERTINO: (
            time.fromisoformat(turnos.vespertino.hora_inicio)
            if turnos.vespertino.hora_inicio is not None
            else None,
            time.fromisoformat(turnos.vespertino.hora_fin)
            if turnos.vespertino.hora_fin is not None
            else None,
        ),
        CodigoTurnoEmpleado.NOCTURNO: (
            time.fromisoformat(turnos.nocturno.hora_inicio)
            if turnos.nocturno.hora_inicio is not None
            else None,
            time.fromisoformat(turnos.nocturno.hora_fin)
            if turnos.nocturno.hora_fin is not None
            else None,
        ),
    }

    try:
        actualizado = cambiar_horarios_empleados(
            db,
            horarios,
            revision_esperada=solicitud.revision_esperada,
        )
    except RevisionHorariosDesactualizadaError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Los horarios cambiaron. Actualiza los datos e intenta de nuevo.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except ConfiguracionHorariosNoDisponibleError:
        _error_horarios_no_disponibles()
    except TurnosEmpleadosIncompletosError:
        _error_interno(db)
    except SQLAlchemyError:
        _error_interno(db)

    return _crear_respuesta(actualizado)


__all__ = ["RUTA_HORARIOS_EMPLEADOS", "router"]
