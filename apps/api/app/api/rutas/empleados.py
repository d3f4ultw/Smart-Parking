"""Rutas OWNER para consultar y administrar el directorio de empleados."""

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencias_empleados import exigir_accion_empleado
from app.core.database import get_db
from app.esquemas.empleados import (
    RespuestaEmpleado,
    RespuestaListaEmpleados,
    SolicitudCambiarEstadoEmpleado,
    SolicitudRegistrarEmpleado,
    TurnoEmpleadoDisponible,
)
from app.servicios.autorizacion_empleados import AccionEmpleado
from app.servicios.empleados import (
    ClaveSolicitudEnConflictoError,
    ConfiguracionEmpleadosNoDisponibleError,
    EmpleadoDTO,
    EmpleadoNoEncontradoError,
    ResultadoListaEmpleados,
    RevisionEstadoEmpleadoDesactualizadaError,
    TurnoDisponibleDTO,
    TurnoEmpleadoNoDisponibleError,
    TurnosEmpleadosIncompletosError,
    cambiar_estado_empleado,
    listar_empleados,
    registrar_empleado,
)

RUTA_ADMIN_EMPLEADOS = "/api/admin/empleados"
CABECERA_NO_CACHE = {"Cache-Control": "no-store"}

router = APIRouter(prefix=RUTA_ADMIN_EMPLEADOS, tags=["admin-empleados"])


def formatear_codigo_empleado(empleado_id: int) -> str:
    """Genera el codigo visible sin alterar el ID numerico persistido."""

    return f"E-{empleado_id:04d}"


def _error_interno(db: Session) -> NoReturn:
    db.rollback()
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Error interno",
        headers=CABECERA_NO_CACHE,
    ) from None


def _respuesta_turno(turno: TurnoDisponibleDTO) -> TurnoEmpleadoDisponible:
    return TurnoEmpleadoDisponible(
        id=str(turno.id),
        codigo=turno.codigo,
        nombre=turno.nombre,
    )


def _respuesta_empleado(empleado: EmpleadoDTO) -> RespuestaEmpleado:
    return RespuestaEmpleado(
        id=str(empleado.id),
        codigo_empleado=formatear_codigo_empleado(empleado.id),
        nombres=empleado.nombres,
        apellido_paterno=empleado.apellido_paterno,
        apellido_materno=empleado.apellido_materno,
        turno=_respuesta_turno(empleado.turno),
        esta_activo=empleado.esta_activo,
        revision_estado=empleado.revision_estado,
        creado_en=empleado.creado_en,
        actualizado_en=empleado.actualizado_en,
    )


def _respuesta_lista(resultado: ResultadoListaEmpleados) -> RespuestaListaEmpleados:
    return RespuestaListaEmpleados(
        empleados=[_respuesta_empleado(empleado) for empleado in resultado.empleados],
        pagina=resultado.pagina,
        tamano_pagina=resultado.tamano_pagina,
        total=resultado.total,
        total_paginas=resultado.total_paginas,
        turnos_disponibles=[
            _respuesta_turno(turno) for turno in resultado.turnos_disponibles
        ],
    )


def _error_modalidad_no_disponible() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "El módulo de empleados solo está disponible en modalidades "
            "Empresarial y Mixta."
        ),
        headers=CABECERA_NO_CACHE,
    ) from None


@router.get("", response_model=RespuestaListaEmpleados)
def consultar_empleados(
    response: Response,
    _usuario_id: Annotated[
        int,
        Depends(exigir_accion_empleado(AccionEmpleado.LEER)),
    ],
    db: Annotated[Session, Depends(get_db)],
    pagina: Annotated[int, Query(ge=1)] = 1,
) -> RespuestaListaEmpleados:
    """Devuelve la pagina y los turnos centrales al personal autorizado."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        return _respuesta_lista(listar_empleados(db, pagina=pagina))
    except ConfiguracionEmpleadosNoDisponibleError:
        _error_modalidad_no_disponible()
    except TurnosEmpleadosIncompletosError:
        _error_interno(db)
    except SQLAlchemyError:
        _error_interno(db)


@router.post(
    "",
    response_model=RespuestaEmpleado,
    status_code=status.HTTP_201_CREATED,
)
def registrar_empleado_endpoint(
    solicitud: SolicitudRegistrarEmpleado,
    response: Response,
    _usuario_id: Annotated[
        int,
        Depends(exigir_accion_empleado(AccionEmpleado.REGISTRAR)),
    ],
    db: Annotated[Session, Depends(get_db)],
    clave_solicitud: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> RespuestaEmpleado:
    """Registra una persona activa y reconoce reintentos equivalentes."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        resultado = registrar_empleado(
            db,
            nombres=solicitud.nombres,
            apellido_paterno=solicitud.apellido_paterno,
            apellido_materno=solicitud.apellido_materno,
            turno_empleado_id=solicitud.turno_empleado_id,
            clave_solicitud=clave_solicitud,
        )
    except ConfiguracionEmpleadosNoDisponibleError:
        _error_modalidad_no_disponible()
    except TurnoEmpleadoNoDisponibleError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El turno seleccionado no está disponible.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except ClaveSolicitudEnConflictoError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La clave de registro ya se usó con otros datos.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except TurnosEmpleadosIncompletosError:
        _error_interno(db)
    except SQLAlchemyError:
        _error_interno(db)

    if resultado.solicitud_repetida:
        response.status_code = status.HTTP_200_OK
    return _respuesta_empleado(resultado.empleado)


@router.patch("/{empleado_id}/estado", response_model=RespuestaEmpleado)
def cambiar_estado_empleado_endpoint(
    empleado_id: int,
    solicitud: SolicitudCambiarEstadoEmpleado,
    response: Response,
    _usuario_id: Annotated[
        int,
        Depends(exigir_accion_empleado(AccionEmpleado.CAMBIAR_ESTADO)),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaEmpleado:
    """Activa o desactiva sin eliminar el registro ni pisar otra revision."""

    response.headers.update(CABECERA_NO_CACHE)
    try:
        empleado = cambiar_estado_empleado(
            db,
            empleado_id=empleado_id,
            esta_activo=solicitud.esta_activo,
            revision_esperada=solicitud.revision_esperada,
        )
    except ConfiguracionEmpleadosNoDisponibleError:
        _error_modalidad_no_disponible()
    except EmpleadoNoEncontradoError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empleado no encontrado.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except RevisionEstadoEmpleadoDesactualizadaError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El estado cambió en otra sesión. Actualiza los datos.",
            headers=CABECERA_NO_CACHE,
        ) from None
    except TurnosEmpleadosIncompletosError:
        _error_interno(db)
    except SQLAlchemyError:
        _error_interno(db)

    return _respuesta_empleado(empleado)


__all__ = ["RUTA_ADMIN_EMPLEADOS", "router"]
