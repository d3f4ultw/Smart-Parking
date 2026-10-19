from __future__ import annotations

from datetime import UTC, datetime, time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.servicios.horarios_empleados as servicio_horarios
from app.core.config import get_settings
from app.models import (
    CodigoTurnoEmpleado,
    ConfiguracionEstacionamiento,
    TurnoEmpleado,
)
from app.servicios.configuracion_estacionamiento import (
    cambiar_modalidad_estacionamiento,
)
from app.servicios.horarios_empleados import (
    cambiar_horarios_empleados,
    evaluar_horario_empleado,
)


def _crear_turnos(db: Session) -> dict[CodigoTurnoEmpleado, TurnoEmpleado]:
    cambiar_modalidad_estacionamiento(db, "MIXTO", revision_esperada=0)
    return {
        CodigoTurnoEmpleado(turno.codigo): turno
        for turno in db.scalars(
            select(TurnoEmpleado).order_by(TurnoEmpleado.id)
        ).all()
    }


def _guardar_horarios(
    db: Session,
    *,
    matutino: tuple[time | None, time | None] = (None, None),
    vespertino: tuple[time | None, time | None] = (None, None),
    nocturno: tuple[time | None, time | None] = (None, None),
) -> None:
    cambiar_horarios_empleados(
        db,
        {
            CodigoTurnoEmpleado.MATUTINO: matutino,
            CodigoTurnoEmpleado.VESPERTINO: vespertino,
            CodigoTurnoEmpleado.NOCTURNO: nocturno,
        },
        revision_esperada=1,
    )


def test_horario_regular_incluye_inicio_y_excluye_fin_con_hora_local(
    db: Session,
) -> None:
    turnos = _crear_turnos(db)
    _guardar_horarios(db, matutino=(time(6), time(14)))
    turno_id = turnos[CodigoTurnoEmpleado.MATUTINO].id

    antes_del_inicio = evaluar_horario_empleado(
        db,
        turno_id=turno_id,
        instante_utc=datetime(2026, 10, 18, 11, 59, tzinfo=UTC),
    )
    inicio = evaluar_horario_empleado(
        db,
        turno_id=turno_id,
        instante_utc=datetime(2026, 10, 18, 12, 0, tzinfo=UTC),
    )
    antes_del_fin = evaluar_horario_empleado(
        db,
        turno_id=turno_id,
        instante_utc=datetime(2026, 10, 18, 19, 59, tzinfo=UTC),
    )
    fin = evaluar_horario_empleado(
        db,
        turno_id=turno_id,
        instante_utc=datetime(2026, 10, 18, 20, 0, tzinfo=UTC),
    )

    assert not antes_del_inicio.permitido
    assert inicio.permitido
    assert antes_del_fin.permitido
    assert not fin.permitido


def test_horario_que_cruza_medianoche_se_evalua_en_la_zona_configurada(
    db: Session,
) -> None:
    turnos = _crear_turnos(db)
    _guardar_horarios(db, nocturno=(time(22), time(6)))
    turno_id = turnos[CodigoTurnoEmpleado.NOCTURNO].id

    inicio = evaluar_horario_empleado(
        db,
        turno_id=turno_id,
        instante_utc=datetime(2026, 10, 19, 4, 0, tzinfo=UTC),
    )
    antes_del_fin = evaluar_horario_empleado(
        db,
        turno_id=turno_id,
        instante_utc=datetime(2026, 10, 19, 11, 59, tzinfo=UTC),
    )
    fin = evaluar_horario_empleado(
        db,
        turno_id=turno_id,
        instante_utc=datetime(2026, 10, 19, 12, 0, tzinfo=UTC),
    )

    assert inicio.permitido
    assert antes_del_fin.permitido
    assert not fin.permitido


def test_ambas_ocurrencias_de_una_hora_repetida_respetan_el_turno(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ajustes = get_settings().model_copy(
        update={"parking_timezone": "America/New_York"}
    )
    monkeypatch.setattr(servicio_horarios, "get_settings", lambda: ajustes)
    turnos = _crear_turnos(db)
    _guardar_horarios(db, nocturno=(time(1), time(2)))
    turno_id = turnos[CodigoTurnoEmpleado.NOCTURNO].id

    primera_ocurrencia = evaluar_horario_empleado(
        db,
        turno_id=turno_id,
        instante_utc=datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
    )
    segunda_ocurrencia = evaluar_horario_empleado(
        db,
        turno_id=turno_id,
        instante_utc=datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
    )

    assert primera_ocurrencia.permitido
    assert segunda_ocurrencia.permitido


def test_turno_sin_configurar_deniega_y_sin_restriccion_omite_solo_la_hora(
    db: Session,
) -> None:
    turnos = _crear_turnos(db)
    instante = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

    sin_horario = evaluar_horario_empleado(
        db,
        turno_id=turnos[CodigoTurnoEmpleado.MATUTINO].id,
        instante_utc=instante,
    )
    sin_restriccion = evaluar_horario_empleado(
        db,
        turno_id=turnos[CodigoTurnoEmpleado.SIN_RESTRICCION].id,
        instante_utc=instante,
    )

    assert sin_horario == type(sin_horario)(False, "turno_sin_configurar")
    assert sin_restriccion == type(sin_restriccion)(True, "sin_restriccion")

    configuracion = db.get(ConfiguracionEstacionamiento, 1)
    assert configuracion is not None
    configuracion.acceso_suspendido = True
    db.commit()

    acceso_suspendido = evaluar_horario_empleado(
        db,
        turno_id=turnos[CodigoTurnoEmpleado.SIN_RESTRICCION].id,
        instante_utc=instante,
    )
    assert not acceso_suspendido.permitido
    assert acceso_suspendido.motivo == "acceso_suspendido"


def test_evaluador_rechaza_modalidad_publica_e_instantes_sin_zona_horaria(
    db: Session,
) -> None:
    turnos = _crear_turnos(db)
    cambio = cambiar_modalidad_estacionamiento(db, "PUBLICO", revision_esperada=1)
    assert cambio.configuracion.modalidad == "PUBLICO"

    resultado = evaluar_horario_empleado(
        db,
        turno_id=turnos[CodigoTurnoEmpleado.SIN_RESTRICCION].id,
        instante_utc=datetime(2026, 10, 18, 12, 0, tzinfo=UTC),
    )
    assert not resultado.permitido
    assert resultado.motivo == "modalidad_no_admitida"

    with pytest.raises(ValueError, match="zona horaria"):
        evaluar_horario_empleado(
            db,
            turno_id=turnos[CodigoTurnoEmpleado.SIN_RESTRICCION].id,
            instante_utc=datetime(2026, 10, 18, 12, 0),
        )


def test_servicio_rechaza_intervalos_incompletos_iguales_y_sin_horario(
    db: Session,
) -> None:
    _crear_turnos(db)
    base = {
        CodigoTurnoEmpleado.MATUTINO: (None, None),
        CodigoTurnoEmpleado.VESPERTINO: (None, None),
        CodigoTurnoEmpleado.NOCTURNO: (None, None),
    }
    invalidos = (
        {**base, CodigoTurnoEmpleado.MATUTINO: (time(6), None)},
        {**base, CodigoTurnoEmpleado.MATUTINO: (time(6), time(6))},
        {
            **base,
            CodigoTurnoEmpleado.SIN_RESTRICCION: (None, None),
        },
    )

    for horarios in invalidos:
        with pytest.raises(ValueError):
            cambiar_horarios_empleados(db, horarios, revision_esperada=1)
