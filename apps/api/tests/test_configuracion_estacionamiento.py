"""Pruebas aisladas de modalidad, concurrencia e interaccion de terminal."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.cli import configuracion_estacionamiento as cli
from app.cli import gestionar_admins
from app.models import (
    ConfiguracionEstacionamiento,
    HistorialModalidadEstacionamiento,
)
from app.servicios.configuracion_estacionamiento import (
    AccesoEstacionamientoSuspendidoError,
    ConfiguracionDesactualizadaError,
    EstacionamientoSinModalidadError,
    ModalidadEstacionamientoInvalidaError,
    cambiar_estado_acceso_estacionamiento,
    cambiar_modalidad_estacionamiento,
    listar_historial_modalidad,
    obtener_configuracion_estacionamiento,
)


def ejecutar_cli(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    respuestas: list[str],
) -> int:
    entradas = iter(respuestas)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(entradas))
    monkeypatch.setattr(cli, "limpiar_pantalla", lambda: None)
    return cli.main(db=db)


def test_ausencia_de_fila_significa_sin_configurar(db: Session) -> None:
    assert obtener_configuracion_estacionamiento(db) is None
    assert listar_historial_modalidad(db) == []


@pytest.mark.parametrize("modalidad", ["PRIVADO", "PUBLICO", "MIXTO"])
def test_configuracion_inicial_se_persiste_solo_tras_eleccion_explicita(
    db: Session,
    modalidad: str,
) -> None:
    resultado = cambiar_modalidad_estacionamiento(
        db,
        modalidad,
        revision_esperada=0,
    )

    assert resultado.cambio_realizado is True
    assert resultado.modalidad_anterior is None
    assert resultado.configuracion.modalidad == modalidad
    assert resultado.configuracion.revision == 1
    historial = listar_historial_modalidad(db)
    assert len(historial) == 1
    assert historial[0].modalidad_anterior is None
    assert historial[0].modalidad_nueva == modalidad


@pytest.mark.parametrize(
    ("modalidad_inicial", "modalidad_nueva"),
    [
        ("PRIVADO", "PUBLICO"),
        ("PUBLICO", "MIXTO"),
        ("MIXTO", "PRIVADO"),
    ],
)
def test_cambio_de_modalidad_incrementa_revision_y_registra_historial(
    db: Session,
    modalidad_inicial: str,
    modalidad_nueva: str,
) -> None:
    cambiar_modalidad_estacionamiento(db, modalidad_inicial, revision_esperada=0)
    resultado = cambiar_modalidad_estacionamiento(
        db,
        modalidad_nueva,
        revision_esperada=1,
    )

    assert resultado.cambio_realizado is True
    assert resultado.modalidad_anterior == modalidad_inicial
    assert resultado.configuracion.modalidad == modalidad_nueva
    assert resultado.configuracion.revision == 2
    historial = listar_historial_modalidad(db)
    assert [(fila.modalidad_anterior, fila.modalidad_nueva) for fila in historial] == [
        (modalidad_inicial, modalidad_nueva),
        (None, modalidad_inicial),
    ]


def test_seleccionar_modalidad_actual_no_modifica_revision_ni_historial(
    db: Session,
) -> None:
    inicial = cambiar_modalidad_estacionamiento(
        db,
        "PRIVADO",
        revision_esperada=0,
    )
    resultado = cambiar_modalidad_estacionamiento(
        db,
        "PRIVADO",
        revision_esperada=1,
    )

    assert resultado.cambio_realizado is False
    assert resultado.configuracion.revision == inicial.configuracion.revision
    assert (
        resultado.configuracion.actualizado_en == inicial.configuracion.actualizado_en
    )
    assert len(listar_historial_modalidad(db)) == 1


def test_suspend_resume_preserva_modalidad_y_solo_revision_cambia_estado(
    db: Session,
) -> None:
    inicial = cambiar_modalidad_estacionamiento(
        db,
        "MIXTO",
        revision_esperada=0,
    )
    configuracion = db.get(ConfiguracionEstacionamiento, 1)
    assert configuracion is not None
    configuracion.actualizado_en = inicial.configuracion.actualizado_en.replace(
        year=2000
    )
    db.commit()
    db.rollback()

    suspendida = cambiar_estado_acceso_estacionamiento(
        db,
        True,
        revision_esperada=1,
    )
    assert suspendida.cambio_realizado is True
    assert suspendida.configuracion is not None
    assert suspendida.configuracion.modalidad == "MIXTO"
    assert suspendida.configuracion.acceso_suspendido is True
    assert suspendida.configuracion.revision == 2
    assert suspendida.configuracion.actualizado_en.year > 2000
    assert [
        (fila.modalidad_anterior, fila.modalidad_nueva)
        for fila in listar_historial_modalidad(db)
    ] == [
        (None, "MIXTO")
    ]

    repetida = cambiar_estado_acceso_estacionamiento(
        db,
        True,
        revision_esperada=2,
    )
    assert repetida.cambio_realizado is False
    assert repetida.configuracion is not None
    assert repetida.configuracion.revision == 2
    assert (
        repetida.configuracion.actualizado_en
        == suspendida.configuracion.actualizado_en
    )
    assert len(listar_historial_modalidad(db)) == 1

    reanudada = cambiar_estado_acceso_estacionamiento(
        db,
        False,
        revision_esperada=2,
    )
    assert reanudada.cambio_realizado is True
    assert reanudada.configuracion is not None
    assert reanudada.configuracion.modalidad == "MIXTO"
    assert reanudada.configuracion.acceso_suspendido is False
    assert reanudada.configuracion.revision == 3
    assert len(listar_historial_modalidad(db)) == 1


def test_suspension_requiere_modalidad_y_rechaza_revision_obsoleta(
    db: Session,
) -> None:
    reanudada_sin_configurar = cambiar_estado_acceso_estacionamiento(
        db,
        False,
        revision_esperada=0,
    )
    assert reanudada_sin_configurar.configuracion is None
    assert reanudada_sin_configurar.cambio_realizado is False
    with pytest.raises(EstacionamientoSinModalidadError):
        cambiar_estado_acceso_estacionamiento(
            db,
            True,
            revision_esperada=0,
        )
    assert obtener_configuracion_estacionamiento(db) is None

    cambiar_modalidad_estacionamiento(db, "PRIVADO", revision_esperada=0)
    with pytest.raises(ConfiguracionDesactualizadaError):
        cambiar_estado_acceso_estacionamiento(
            db,
            True,
            revision_esperada=0,
        )
    estado = obtener_configuracion_estacionamiento(db)
    assert estado is not None
    assert estado.acceso_suspendido is False
    assert estado.revision == 1


def test_modalidad_no_cambia_mientras_el_acceso_esta_suspendido(db: Session) -> None:
    cambiar_modalidad_estacionamiento(db, "PRIVADO", revision_esperada=0)
    cambiar_estado_acceso_estacionamiento(db, True, revision_esperada=1)

    with pytest.raises(AccesoEstacionamientoSuspendidoError):
        cambiar_modalidad_estacionamiento(
            db,
            "PUBLICO",
            revision_esperada=2,
        )

    estado = obtener_configuracion_estacionamiento(db)
    assert estado is not None
    assert estado.modalidad == "PRIVADO"
    assert estado.acceso_suspendido is True
    assert estado.revision == 2
    assert [
        (fila.modalidad_anterior, fila.modalidad_nueva)
        for fila in listar_historial_modalidad(db)
    ] == [
        (None, "PRIVADO")
    ]


def test_cambios_confirmados_persisten_al_renovar_la_sesion(db: Session) -> None:
    cambiar_modalidad_estacionamiento(db, "PRIVADO", revision_esperada=0)
    db.rollback()

    configuracion = obtener_configuracion_estacionamiento(db)
    historial = listar_historial_modalidad(db)
    assert configuracion is not None
    assert configuracion.modalidad == "PRIVADO"
    assert len(historial) == 1


def test_modalidad_invalida_es_rechazada_por_el_servicio(db: Session) -> None:
    with pytest.raises(ModalidadEstacionamientoInvalidaError):
        cambiar_modalidad_estacionamiento(db, "privado", revision_esperada=0)

    assert obtener_configuracion_estacionamiento(db) is None


def test_restricciones_de_base_rechazan_singleton_y_historial_invalidos(
    db: Session,
) -> None:
    with pytest.raises(IntegrityError):
        db.add(
            ConfiguracionEstacionamiento(
                id=2,
                modalidad="PRIVADO",
                revision=1,
            )
        )
        db.flush()
    db.rollback()

    with pytest.raises(IntegrityError):
        db.add(
            ConfiguracionEstacionamiento(
                id=1,
                modalidad="privado",
                revision=1,
            )
        )
        db.flush()
    db.rollback()

    db.add(
        ConfiguracionEstacionamiento(
            id=1,
            modalidad="PRIVADO",
            revision=1,
        )
    )
    db.flush()
    with pytest.raises(IntegrityError):
        db.add(
            HistorialModalidadEstacionamiento(
                configuracion_id=1,
                revision=2,
                modalidad_anterior=None,
                modalidad_nueva="PUBLICO",
            )
        )
        db.flush()
    db.rollback()


def test_error_de_persistencia_restaura_modalidad_e_historial(
    db: Session,
) -> None:
    with patch.object(db, "flush", side_effect=SQLAlchemyError("fallo sintetico")):
        with pytest.raises(SQLAlchemyError):
            cambiar_modalidad_estacionamiento(
                db,
                "PUBLICO",
                revision_esperada=0,
            )

    assert obtener_configuracion_estacionamiento(db) is None
    assert listar_historial_modalidad(db) == []


def test_dos_inicializaciones_concurrentes_exigen_confirmar_estado_vigente(
    db: Session,
) -> None:
    db.rollback()
    fabrica = sessionmaker(
        bind=db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    barrera = Barrier(2)

    def configurar(modalidad: str) -> str:
        with fabrica() as sesion:
            barrera.wait(timeout=10)
            try:
                cambiar_modalidad_estacionamiento(
                    sesion,
                    modalidad,
                    revision_esperada=0,
                )
                return "cambiada"
            except ConfiguracionDesactualizadaError:
                return "desactualizada"

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        resultados = list(ejecutor.map(configurar, ["PRIVADO", "PUBLICO"]))

    assert sorted(resultados) == ["cambiada", "desactualizada"]
    configuracion = obtener_configuracion_estacionamiento(db)
    historial = listar_historial_modalidad(db)
    assert configuracion is not None
    assert configuracion.revision == 1
    assert configuracion.modalidad in {"PRIVADO", "PUBLICO"}
    assert len(historial) == 1


def test_cli_muestra_estado_historial_y_regresa_al_menu_principal(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    respuestas = iter(["2", "0", "0"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(respuestas))
    monkeypatch.setattr(gestionar_admins, "get_settings", lambda: None)
    monkeypatch.setattr(gestionar_admins, "limpiar_pantalla", lambda: None)
    assert gestionar_admins.main(db=db) == 0

    salida = capsys.readouterr()
    assert "CONFIGURACIÓN DEL ESTACIONAMIENTO" in salida.out
    assert "Modalidad actual: SIN CONFIGURAR" in salida.out
    assert "SMART PARKING — ADMINISTRACIÓN LOCAL" in salida.out


def test_cli_rechaza_entradas_vacias_y_cancelar_no_crea_configuracion(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ejecutar_cli(db, monkeypatch, ["", "1", "", "0", "0"]) == 0

    salida = capsys.readouterr()
    assert salida.err.count("Opción no válida.") == 2
    assert "Modalidad actual: SIN CONFIGURAR" in salida.out
    assert obtener_configuracion_estacionamiento(db) is None
    assert listar_historial_modalidad(db) == []


def test_cli_exige_confirmacion_antes_de_persistir(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert ejecutar_cli(db, monkeypatch, ["1", "1", "2", "0"]) == 0

    assert obtener_configuracion_estacionamiento(db) is None
    assert listar_historial_modalidad(db) == []


def test_cli_persiste_modalidad_solo_en_sesion_aislada_y_muestra_exito(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ejecutar_cli(db, monkeypatch, ["1", "2", "1", "", "0"]) == 0

    salida = capsys.readouterr()
    assert "Modalidad guardada: PUBLICO" in salida.out
    configuracion = obtener_configuracion_estacionamiento(db)
    historial = listar_historial_modalidad(db)
    assert configuracion is not None
    assert configuracion.modalidad == "PUBLICO"
    assert [(fila.modalidad_anterior, fila.modalidad_nueva) for fila in historial] == [
        (None, "PUBLICO")
    ]


def test_cli_muestra_bloqueo_seguro_al_cambiar_modalidad_suspendida(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cambiar_modalidad_estacionamiento(db, "PRIVADO", revision_esperada=0)
    cambiar_estado_acceso_estacionamiento(db, True, revision_esperada=1)

    assert ejecutar_cli(db, monkeypatch, ["1", "2", "1", "", "0"]) == 0

    salida = capsys.readouterr()
    assert (
        "No se puede cambiar la modalidad mientras el acceso está suspendido."
        in salida.out
    )
    assert "Traceback" not in salida.out + salida.err
    estado = obtener_configuracion_estacionamiento(db)
    assert estado is not None
    assert estado.modalidad == "PRIVADO"
    assert estado.revision == 2


def test_cli_historial_es_reciente_y_no_muestra_identidades(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cambiar_modalidad_estacionamiento(db, "PRIVADO", revision_esperada=0)
    cambiar_modalidad_estacionamiento(db, "PUBLICO", revision_esperada=1)

    assert ejecutar_cli(db, monkeypatch, ["2", "", "0"]) == 0

    salida = capsys.readouterr().out
    assert "PRIVADO — Privado empresarial → PUBLICO" in salida
    assert "SIN CONFIGURAR → PRIVADO" in salida
    assert "ADMIN" not in salida
    assert "usuario" not in salida.casefold()


def test_cli_recarga_y_requiere_nueva_seleccion_si_cambia_la_revision(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cambiar_modalidad_estacionamiento(db, "PRIVADO", revision_esperada=0)
    cambiar_real = cambiar_modalidad_estacionamiento

    def cambiar_durante_confirmacion(
        sesion: Session,
        modalidad: str,
        *,
        revision_esperada: int,
    ):
        cambiar_real(sesion, "MIXTO", revision_esperada=revision_esperada)
        return cambiar_real(
            sesion,
            modalidad,
            revision_esperada=revision_esperada,
        )

    monkeypatch.setattr(
        cli,
        "cambiar_modalidad_estacionamiento",
        cambiar_durante_confirmacion,
    )
    assert ejecutar_cli(db, monkeypatch, ["1", "2", "1", "0"]) == 0

    salida = capsys.readouterr().out
    assert "La configuración cambió mientras confirmabas." in salida
    assert "Modalidad actual: MIXTO" in salida
    configuracion = obtener_configuracion_estacionamiento(db)
    assert configuracion is not None
    assert configuracion.modalidad == "MIXTO"
    assert configuracion.revision == 2


def test_cli_muestra_error_seguro_si_falla_la_conexion(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fallar_lectura(_db: Session):
        raise SQLAlchemyError("password=secreto")

    monkeypatch.setattr(cli, "obtener_configuracion_estacionamiento", fallar_lectura)
    assert ejecutar_cli(db, monkeypatch, [""]) == 1

    salida = capsys.readouterr()
    assert (
        "No fue posible consultar la configuración del estacionamiento." in salida.err
    )
    assert "password" not in salida.out + salida.err
    assert "Traceback" not in salida.out + salida.err


def test_historial_respeta_el_limite_de_veinte_registros(db: Session) -> None:
    modalidad = "PRIVADO"
    revision = 0
    for _ in range(22):
        siguiente = "PUBLICO" if modalidad == "PRIVADO" else "PRIVADO"
        cambiar_modalidad_estacionamiento(
            db,
            siguiente,
            revision_esperada=revision,
        )
        modalidad = siguiente
        revision += 1

    filas = listar_historial_modalidad(db)
    assert len(filas) == 20
    assert filas[0].modalidad_nueva == modalidad
