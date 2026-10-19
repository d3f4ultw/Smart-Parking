"""Gestiona turnos compartidos y evalúa su condición horaria de acceso."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    CODIGOS_TURNOS_EMPLEADOS,
    NOMBRES_TURNOS_EMPLEADOS,
    CodigoTurnoEmpleado,
    ConfiguracionEstacionamiento,
    TurnoEmpleado,
)

MODALIDADES_CON_HORARIOS = frozenset({"PRIVADO", "MIXTO"})
CODIGOS_CONFIGURABLES = (
    CodigoTurnoEmpleado.MATUTINO,
    CodigoTurnoEmpleado.VESPERTINO,
    CodigoTurnoEmpleado.NOCTURNO,
)


class ConfiguracionHorariosNoDisponibleError(RuntimeError):
    """Indica que los horarios no aplican a la configuracion vigente."""


class TurnosEmpleadosIncompletosError(RuntimeError):
    """Indica que falta alguna fila del catalogo fijo de turnos."""


class RevisionHorariosDesactualizadaError(RuntimeError):
    """Indica que otra solicitud guardó primero una revision distinta."""


@dataclass(frozen=True, slots=True)
class TurnoEmpleadoDTO:
    """Datos centrales de un turno, sin copiar sus horas a empleados."""

    id: int
    codigo: CodigoTurnoEmpleado
    nombre: str
    hora_inicio: time | None
    hora_fin: time | None


@dataclass(frozen=True, slots=True)
class HorariosEmpleadosDTO:
    """Instantanea de los cuatro turnos y su revision independiente."""

    revision: int
    zona_horaria: str
    turnos: tuple[TurnoEmpleadoDTO, ...]


@dataclass(frozen=True, slots=True)
class ResultadoEvaluacionHorario:
    """Resultado de la compuerta horaria, no de la identidad RFID completa."""

    permitido: bool
    motivo: str


def sembrar_turnos_empleados(db: Session, *, configuracion_id: int) -> None:
    """Crea el catalogo fijo sin reemplazar turnos ya persistidos."""

    insercion = (
        insert(TurnoEmpleado)
        .values(
            [
                {
                    "configuracion_estacionamiento_id": configuracion_id,
                    "codigo": codigo.value,
                }
                for codigo in CODIGOS_TURNOS_EMPLEADOS
            ]
        )
        .on_conflict_do_nothing(
            index_elements=[
                TurnoEmpleado.configuracion_estacionamiento_id,
                TurnoEmpleado.codigo,
            ]
        )
    )
    db.execute(insercion)
    db.flush()


def _validar_intervalo(
    codigo: CodigoTurnoEmpleado,
    hora_inicio: time | None,
    hora_fin: time | None,
) -> None:
    """Mantiene iguales las reglas de servicio y las restricciones SQL."""

    if (hora_inicio is None) != (hora_fin is None):
        raise ValueError("El turno requiere ambas horas o ninguna.")
    if hora_inicio is not None and hora_inicio == hora_fin:
        raise ValueError("La hora de inicio y fin deben ser distintas.")
    if codigo == CodigoTurnoEmpleado.SIN_RESTRICCION and hora_inicio is not None:
        raise ValueError("Sin restricción no admite una configuración de horas.")


def _validar_configuracion(configuracion: ConfiguracionEstacionamiento | None) -> None:
    if (
        configuracion is None
        or configuracion.modalidad not in MODALIDADES_CON_HORARIOS
    ):
        raise ConfiguracionHorariosNoDisponibleError


def _crear_turno_dto(turno: TurnoEmpleado) -> TurnoEmpleadoDTO:
    return TurnoEmpleadoDTO(
        id=turno.id,
        codigo=CodigoTurnoEmpleado(turno.codigo),
        nombre=NOMBRES_TURNOS_EMPLEADOS[CodigoTurnoEmpleado(turno.codigo)],
        hora_inicio=turno.hora_inicio,
        hora_fin=turno.hora_fin,
    )


def _crear_horarios_dto(
    configuracion: ConfiguracionEstacionamiento,
    turnos: list[TurnoEmpleado],
) -> HorariosEmpleadosDTO:
    por_codigo = {turno.codigo: turno for turno in turnos}
    if len(por_codigo) != len(CODIGOS_TURNOS_EMPLEADOS):
        raise TurnosEmpleadosIncompletosError
    if any(codigo.value not in por_codigo for codigo in CODIGOS_TURNOS_EMPLEADOS):
        raise TurnosEmpleadosIncompletosError

    return HorariosEmpleadosDTO(
        revision=configuracion.revision_horarios,
        zona_horaria=get_settings().parking_timezone,
        turnos=tuple(
            _crear_turno_dto(por_codigo[codigo.value])
            for codigo in CODIGOS_TURNOS_EMPLEADOS
        ),
    )


def obtener_horarios_empleados(db: Session) -> HorariosEmpleadosDTO:
    """Lee los turnos si la modalidad actual permite configurar horarios."""

    configuracion = db.get(ConfiguracionEstacionamiento, 1)
    _validar_configuracion(configuracion)
    assert configuracion is not None
    turnos = db.scalars(
        select(TurnoEmpleado).where(
            TurnoEmpleado.configuracion_estacionamiento_id == configuracion.id
        )
    ).all()
    return _crear_horarios_dto(configuracion, list(turnos))


def cambiar_horarios_empleados(
    db: Session,
    horarios: Mapping[CodigoTurnoEmpleado, tuple[time | None, time | None]],
    *,
    revision_esperada: int,
) -> HorariosEmpleadosDTO:
    """Actualiza los tres turnos en una transaccion con revision optimista."""

    if type(revision_esperada) is not int or revision_esperada < 1:
        raise ValueError("La revision esperada debe ser un entero positivo.")
    if set(horarios) != set(CODIGOS_CONFIGURABLES):
        raise ValueError("La solicitud debe incluir los tres turnos configurables.")
    for codigo, (hora_inicio, hora_fin) in horarios.items():
        _validar_intervalo(codigo, hora_inicio, hora_fin)

    db.rollback()
    with db.begin():
        configuracion = db.scalar(
            select(ConfiguracionEstacionamiento)
            .where(ConfiguracionEstacionamiento.id == 1)
            .with_for_update()
        )
        _validar_configuracion(configuracion)
        assert configuracion is not None
        if configuracion.revision_horarios != revision_esperada:
            raise RevisionHorariosDesactualizadaError

        filas = db.scalars(
            select(TurnoEmpleado)
            .where(
                TurnoEmpleado.configuracion_estacionamiento_id == configuracion.id
            )
            .with_for_update()
        ).all()
        por_codigo = {turno.codigo: turno for turno in filas}
        if len(por_codigo) != len(CODIGOS_TURNOS_EMPLEADOS) or any(
            codigo.value not in por_codigo for codigo in CODIGOS_TURNOS_EMPLEADOS
        ):
            raise TurnosEmpleadosIncompletosError

        cambio_realizado = False
        for codigo, (hora_inicio, hora_fin) in horarios.items():
            turno = por_codigo[codigo.value]
            if turno.hora_inicio != hora_inicio or turno.hora_fin != hora_fin:
                turno.hora_inicio = hora_inicio
                turno.hora_fin = hora_fin
                turno.actualizado_en = func.now()
                cambio_realizado = True

        if cambio_realizado:
            configuracion.revision_horarios += 1
            db.flush()
            db.refresh(configuracion)
            for turno in filas:
                db.refresh(turno)

        return _crear_horarios_dto(configuracion, list(filas))


def _hora_dentro_del_intervalo(
    hora_actual: time,
    hora_inicio: time,
    hora_fin: time,
) -> bool:
    """Incluye el inicio y excluye el fin, incluso al cruzar medianoche."""

    if hora_inicio < hora_fin:
        return hora_inicio <= hora_actual < hora_fin
    return hora_actual >= hora_inicio or hora_actual < hora_fin


def evaluar_horario_empleado(
    db: Session,
    *,
    turno_id: int,
    instante_utc: datetime | None = None,
) -> ResultadoEvaluacionHorario:
    """Evalúa la compuerta horaria y conserva suspensión y modalidad vigentes."""

    instante = instante_utc or datetime.now(UTC)
    if instante.tzinfo is None or instante.utcoffset() is None:
        raise ValueError("El instante de evaluación debe incluir zona horaria.")

    fila = db.execute(
        select(ConfiguracionEstacionamiento, TurnoEmpleado)
        .join(
            TurnoEmpleado,
            TurnoEmpleado.configuracion_estacionamiento_id
            == ConfiguracionEstacionamiento.id,
        )
        .where(
            ConfiguracionEstacionamiento.id == 1,
            TurnoEmpleado.id == turno_id,
        )
    ).one_or_none()
    if fila is None:
        return ResultadoEvaluacionHorario(False, "turno_no_disponible")

    configuracion, turno = fila
    if configuracion.acceso_suspendido:
        return ResultadoEvaluacionHorario(False, "acceso_suspendido")
    if configuracion.modalidad not in MODALIDADES_CON_HORARIOS:
        return ResultadoEvaluacionHorario(False, "modalidad_no_admitida")
    if turno.codigo == CodigoTurnoEmpleado.SIN_RESTRICCION.value:
        return ResultadoEvaluacionHorario(True, "sin_restriccion")
    if turno.hora_inicio is None or turno.hora_fin is None:
        return ResultadoEvaluacionHorario(False, "turno_sin_configurar")

    hora_local = instante.astimezone(
        get_settings().zona_horaria_estacionamiento
    ).timetz().replace(tzinfo=None)
    if _hora_dentro_del_intervalo(
        hora_local,
        turno.hora_inicio,
        turno.hora_fin,
    ):
        return ResultadoEvaluacionHorario(True, "dentro_del_horario")
    return ResultadoEvaluacionHorario(False, "fuera_del_horario")


__all__ = [
    "CODIGOS_CONFIGURABLES",
    "ConfiguracionHorariosNoDisponibleError",
    "HorariosEmpleadosDTO",
    "RevisionHorariosDesactualizadaError",
    "ResultadoEvaluacionHorario",
    "TurnoEmpleadoDTO",
    "TurnosEmpleadosIncompletosError",
    "cambiar_horarios_empleados",
    "evaluar_horario_empleado",
    "obtener_horarios_empleados",
    "sembrar_turnos_empleados",
]
