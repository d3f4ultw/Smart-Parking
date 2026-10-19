"""Consultas y transacciones del directorio de empleados."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    CODIGOS_TURNOS_EMPLEADOS,
    NOMBRES_TURNOS_EMPLEADOS,
    CodigoTurnoEmpleado,
    ConfiguracionEstacionamiento,
    Empleado,
    TurnoEmpleado,
)
from app.servicios.horarios_empleados import MODALIDADES_CON_HORARIOS

ID_CONFIGURACION_ESTACIONAMIENTO = 1
TAMANO_PAGINA_EMPLEADOS = 10


class ErrorGestionEmpleado(RuntimeError):
    """Clase base para errores esperados del directorio laboral."""


class ConfiguracionEmpleadosNoDisponibleError(ErrorGestionEmpleado):
    """Indica que la configuracion no habilita la gestion de empleados."""


class TurnosEmpleadosIncompletosError(ErrorGestionEmpleado):
    """Indica que el catalogo compartido no contiene los cuatro turnos."""


class TurnoEmpleadoNoDisponibleError(ErrorGestionEmpleado):
    """Indica que el turno solicitado no pertenece al estacionamiento vigente."""


class EmpleadoNoEncontradoError(ErrorGestionEmpleado):
    """Indica que el ID no corresponde a un empleado registrado."""


class ClaveSolicitudEnConflictoError(ErrorGestionEmpleado):
    """Indica que una clave de idempotencia se reutilizo con otros datos."""


class RevisionEstadoEmpleadoDesactualizadaError(ErrorGestionEmpleado):
    """Indica que otra solicitud cambio el estado despues de leerlo."""


@dataclass(frozen=True, slots=True)
class TurnoDisponibleDTO:
    """Opcion de turno compartido sin campos horarios."""

    id: int
    codigo: CodigoTurnoEmpleado
    nombre: str


@dataclass(frozen=True, slots=True)
class EmpleadoDTO:
    """Vista de empleado que puede devolverse a la interfaz."""

    id: int
    nombres: str
    apellido_paterno: str
    apellido_materno: str | None
    turno: TurnoDisponibleDTO
    esta_activo: bool
    revision_estado: int
    creado_en: datetime
    actualizado_en: datetime


@dataclass(frozen=True, slots=True)
class ResultadoListaEmpleados:
    """Pagina del directorio y catalogo de turnos disponible."""

    empleados: tuple[EmpleadoDTO, ...]
    pagina: int
    tamano_pagina: int
    total: int
    total_paginas: int
    turnos_disponibles: tuple[TurnoDisponibleDTO, ...]


@dataclass(frozen=True, slots=True)
class ResultadoRegistroEmpleado:
    """Empleado resultante y marca interna de reintento idempotente."""

    empleado: EmpleadoDTO
    solicitud_repetida: bool


def _obtener_configuracion_valida(
    db: Session,
    *,
    bloquear_escritura: bool,
) -> ConfiguracionEstacionamiento:
    consulta = select(ConfiguracionEstacionamiento).where(
        ConfiguracionEstacionamiento.id == ID_CONFIGURACION_ESTACIONAMIENTO
    )
    consulta = consulta.with_for_update(
        read=not bloquear_escritura,
    )
    configuracion = db.scalar(consulta)
    if configuracion is None or configuracion.modalidad not in MODALIDADES_CON_HORARIOS:
        raise ConfiguracionEmpleadosNoDisponibleError
    return configuracion


def _crear_turno_disponible(turno: TurnoEmpleado) -> TurnoDisponibleDTO:
    codigo = CodigoTurnoEmpleado(turno.codigo)
    return TurnoDisponibleDTO(
        id=turno.id,
        codigo=codigo,
        nombre=NOMBRES_TURNOS_EMPLEADOS[codigo],
    )


def _obtener_catalogo_turnos(
    db: Session,
    *,
    configuracion_id: int,
) -> list[TurnoEmpleado]:
    turnos = db.scalars(
        select(TurnoEmpleado)
        .where(TurnoEmpleado.configuracion_estacionamiento_id == configuracion_id)
        .order_by(TurnoEmpleado.id)
    ).all()
    codigos = {turno.codigo for turno in turnos}
    if len(turnos) != len(CODIGOS_TURNOS_EMPLEADOS) or codigos != {
        codigo.value for codigo in CODIGOS_TURNOS_EMPLEADOS
    }:
        raise TurnosEmpleadosIncompletosError
    por_codigo = {turno.codigo: turno for turno in turnos}
    return [por_codigo[codigo.value] for codigo in CODIGOS_TURNOS_EMPLEADOS]


def _crear_empleado_dto(empleado: Empleado, turno: TurnoEmpleado) -> EmpleadoDTO:
    return EmpleadoDTO(
        id=empleado.id,
        nombres=empleado.nombres,
        apellido_paterno=empleado.apellido_paterno,
        apellido_materno=empleado.apellido_materno,
        turno=_crear_turno_disponible(turno),
        esta_activo=empleado.esta_activo,
        revision_estado=empleado.revision_estado,
        creado_en=empleado.creado_en,
        actualizado_en=empleado.actualizado_en,
    )


def _obtener_turno_de_empleado(db: Session, empleado: Empleado) -> TurnoEmpleado:
    turno = db.scalar(
        select(TurnoEmpleado).where(
            TurnoEmpleado.configuracion_estacionamiento_id
            == empleado.configuracion_estacionamiento_id,
            TurnoEmpleado.id == empleado.turno_empleado_id,
        )
    )
    if turno is None:
        raise TurnosEmpleadosIncompletosError
    return turno


def listar_empleados(db: Session, *, pagina: int) -> ResultadoListaEmpleados:
    """Devuelve una pagina y las opciones compartidas en modalidad permitida."""

    if type(pagina) is not int or pagina < 1:
        raise ValueError("La pagina debe ser un entero positivo.")

    db.rollback()
    try:
        with db.begin():
            configuracion = _obtener_configuracion_valida(
                db,
                bloquear_escritura=False,
            )
            turnos = _obtener_catalogo_turnos(
                db,
                configuracion_id=configuracion.id,
            )
            consulta_conteo = (
                select(func.count())
                .select_from(Empleado)
                .where(Empleado.configuracion_estacionamiento_id == configuracion.id)
            )
            total = int(db.scalar(consulta_conteo) or 0)
            total_paginas = (
                total + TAMANO_PAGINA_EMPLEADOS - 1
            ) // TAMANO_PAGINA_EMPLEADOS
            pagina_efectiva = min(pagina, total_paginas) if total_paginas else 1

            filas = db.execute(
                select(Empleado, TurnoEmpleado)
                .join(
                    TurnoEmpleado,
                    (
                        TurnoEmpleado.configuracion_estacionamiento_id
                        == Empleado.configuracion_estacionamiento_id
                    )
                    & (TurnoEmpleado.id == Empleado.turno_empleado_id),
                )
                .where(Empleado.configuracion_estacionamiento_id == configuracion.id)
                .order_by(Empleado.id)
                .limit(TAMANO_PAGINA_EMPLEADOS)
                .offset((pagina_efectiva - 1) * TAMANO_PAGINA_EMPLEADOS)
            ).all()
            return ResultadoListaEmpleados(
                empleados=tuple(
                    _crear_empleado_dto(empleado, turno) for empleado, turno in filas
                ),
                pagina=pagina_efectiva,
                tamano_pagina=TAMANO_PAGINA_EMPLEADOS,
                total=total,
                total_paginas=total_paginas,
                turnos_disponibles=tuple(
                    _crear_turno_disponible(turno) for turno in turnos
                ),
            )
    except ErrorGestionEmpleado, ValueError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise


def registrar_empleado(
    db: Session,
    *,
    nombres: str,
    apellido_paterno: str,
    apellido_materno: str | None,
    turno_empleado_id: int,
    clave_solicitud: UUID,
) -> ResultadoRegistroEmpleado:
    """Crea una fila Activa o reconoce un reintento con la misma clave."""

    db.rollback()
    try:
        with db.begin():
            configuracion = _obtener_configuracion_valida(
                db,
                bloquear_escritura=True,
            )
            turno = db.scalar(
                select(TurnoEmpleado)
                .where(
                    TurnoEmpleado.configuracion_estacionamiento_id == configuracion.id,
                    TurnoEmpleado.id == turno_empleado_id,
                    TurnoEmpleado.codigo.in_(
                        [codigo.value for codigo in CODIGOS_TURNOS_EMPLEADOS]
                    ),
                )
                .with_for_update(read=True)
            )
            if turno is None:
                raise TurnoEmpleadoNoDisponibleError

            empleado_id = db.scalar(
                insert(Empleado)
                .values(
                    configuracion_estacionamiento_id=configuracion.id,
                    turno_empleado_id=turno.id,
                    nombres=nombres,
                    apellido_paterno=apellido_paterno,
                    apellido_materno=apellido_materno,
                    esta_activo=True,
                    revision_estado=1,
                    clave_solicitud=clave_solicitud,
                )
                .on_conflict_do_nothing(
                    index_elements=[Empleado.clave_solicitud],
                )
                .returning(Empleado.id)
            )

            solicitud_repetida = empleado_id is None
            if solicitud_repetida:
                empleado = db.scalar(
                    select(Empleado)
                    .where(Empleado.clave_solicitud == clave_solicitud)
                    .with_for_update()
                )
                if empleado is None:
                    raise ClaveSolicitudEnConflictoError
                if (
                    empleado.nombres != nombres
                    or empleado.apellido_paterno != apellido_paterno
                    or empleado.apellido_materno != apellido_materno
                    or empleado.turno_empleado_id != turno.id
                ):
                    raise ClaveSolicitudEnConflictoError
            else:
                empleado = db.get(Empleado, empleado_id)
                if empleado is None:
                    raise SQLAlchemyError("No se pudo confirmar el alta del empleado.")

            turno_guardado = _obtener_turno_de_empleado(db, empleado)
            return ResultadoRegistroEmpleado(
                empleado=_crear_empleado_dto(empleado, turno_guardado),
                solicitud_repetida=solicitud_repetida,
            )
    except ErrorGestionEmpleado, ValueError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise


def cambiar_estado_empleado(
    db: Session,
    *,
    empleado_id: int,
    esta_activo: bool,
    revision_esperada: int,
) -> EmpleadoDTO:
    """Guarda un cambio de estado sin pisar una revision concurrente."""

    if type(empleado_id) is not int or empleado_id < 1:
        raise ValueError("El ID debe ser un entero positivo.")
    if type(esta_activo) is not bool:
        raise ValueError("El estado solicitado no es valido.")
    if type(revision_esperada) is not int or revision_esperada < 1:
        raise ValueError("La revision esperada debe ser un entero positivo.")

    db.rollback()
    try:
        with db.begin():
            configuracion = _obtener_configuracion_valida(
                db,
                bloquear_escritura=True,
            )
            empleado = db.scalar(
                select(Empleado)
                .where(
                    Empleado.id == empleado_id,
                    Empleado.configuracion_estacionamiento_id == configuracion.id,
                )
                .with_for_update()
            )
            if empleado is None:
                raise EmpleadoNoEncontradoError

            if (
                empleado.revision_estado != revision_esperada
                and empleado.esta_activo != esta_activo
            ):
                raise RevisionEstadoEmpleadoDesactualizadaError

            if empleado.esta_activo != esta_activo:
                empleado.esta_activo = esta_activo
                empleado.revision_estado += 1
                empleado.actualizado_en = func.now()
                db.flush()
                db.refresh(empleado)

            turno = _obtener_turno_de_empleado(db, empleado)
            return _crear_empleado_dto(empleado, turno)
    except ErrorGestionEmpleado, ValueError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise


__all__ = [
    "ClaveSolicitudEnConflictoError",
    "ConfiguracionEmpleadosNoDisponibleError",
    "EmpleadoDTO",
    "EmpleadoNoEncontradoError",
    "ErrorGestionEmpleado",
    "ResultadoListaEmpleados",
    "ResultadoRegistroEmpleado",
    "RevisionEstadoEmpleadoDesactualizadaError",
    "TAMANO_PAGINA_EMPLEADOS",
    "TurnoDisponibleDTO",
    "TurnoEmpleadoNoDisponibleError",
    "TurnosEmpleadosIncompletosError",
    "cambiar_estado_empleado",
    "listar_empleados",
    "registrar_empleado",
]
