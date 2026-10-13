"""Submenu local para consultar y configurar la modalidad del estacionamiento."""

from __future__ import annotations

import sys
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.cli.presentacion import (
    ANSI_AMARILLO,
    ANSI_CIAN_BRILLANTE,
    ANSI_ROJO,
    ANSI_VERDE,
    _estilizar,
    limpiar_pantalla,
)
from app.core.database import SessionLocal
from app.servicios.configuracion_estacionamiento import (
    LIMITE_HISTORIAL_MODALIDAD,
    AccesoEstacionamientoSuspendidoError,
    ConfiguracionDesactualizadaError,
    ConfiguracionEstacionamientoDTO,
    HistorialModalidadDTO,
    ModalidadEstacionamiento,
    cambiar_modalidad_estacionamiento,
    listar_historial_modalidad,
    obtener_configuracion_estacionamiento,
)

_MODALIDADES_MENU: dict[str, tuple[ModalidadEstacionamiento, str]] = {
    "1": ("PRIVADO", "Privado empresarial"),
    "2": ("PUBLICO", "Público comercial"),
    "3": ("MIXTO", "Mixto"),
}


def _nombre_modalidad(modalidad: str | None) -> str:
    if modalidad is None:
        return "SIN CONFIGURAR"
    return {
        "PRIVADO": "PRIVADO — Privado empresarial",
        "PUBLICO": "PUBLICO — Público comercial",
        "MIXTO": "MIXTO — Mixto",
    }.get(modalidad, modalidad)


def _revision(configuracion: ConfiguracionEstacionamientoDTO | None) -> int:
    return configuracion.revision if configuracion is not None else 0


def _mostrar_menu(configuracion: ConfiguracionEstacionamientoDTO | None) -> None:
    print(_estilizar("SMART PARKING", ANSI_CIAN_BRILLANTE))
    print(_estilizar("CONFIGURACIÓN DEL ESTACIONAMIENTO", ANSI_CIAN_BRILLANTE))
    modalidad_actual = configuracion.modalidad if configuracion else None
    print(f"\nModalidad actual: {_nombre_modalidad(modalidad_actual)}")
    print("\n1. Configurar o cambiar modalidad")
    print("2. Consultar historial")
    print("0. Volver")


def _leer_opcion(prompt: str, opciones: set[str]) -> str | None:
    opcion = input(prompt).strip()
    if opcion not in opciones:
        print(_estilizar("Opción no válida.", ANSI_ROJO), file=sys.stderr)
        return None
    return opcion


def _pausar() -> None:
    input("Presiona Enter para continuar...")


def _informar_error_consulta(db: Session) -> None:
    db.rollback()
    print(
        _estilizar(
            "No fue posible consultar la configuración del estacionamiento.",
            ANSI_ROJO,
        ),
        file=sys.stderr,
    )


def _seleccionar_modalidad(
    db: Session,
    configuracion_actual: ConfiguracionEstacionamientoDTO | None,
) -> None:
    while True:
        print("\nSelecciona la modalidad:")
        for opcion, (_modalidad, etiqueta) in _MODALIDADES_MENU.items():
            print(f"{opcion}. {etiqueta}")
        print("0. Volver")
        opcion = input("Opción: ").strip()
        if opcion == "0":
            return
        if opcion not in _MODALIDADES_MENU:
            print(_estilizar("Opción no válida.", ANSI_ROJO), file=sys.stderr)
            continue

        modalidad_nueva, _etiqueta = _MODALIDADES_MENU[opcion]
        modalidad_actual = (
            configuracion_actual.modalidad if configuracion_actual else None
        )
        print(f"\nModalidad actual: {_nombre_modalidad(modalidad_actual)}")
        print(f"Nueva modalidad: {_nombre_modalidad(modalidad_nueva)}")
        while True:
            print("\nConfirmar cambio:")
            print("1. Sí")
            print("2. No")
            confirmacion = input("Opción: ").strip()
            if confirmacion == "2":
                return
            if confirmacion == "1":
                break
            print(_estilizar("Opción no válida.", ANSI_ROJO), file=sys.stderr)

        try:
            resultado = cambiar_modalidad_estacionamiento(
                db,
                modalidad_nueva,
                revision_esperada=_revision(configuracion_actual),
            )
        except AccesoEstacionamientoSuspendidoError:
            db.rollback()
            print(
                _estilizar(
                    "No se puede cambiar la modalidad mientras el acceso está "
                    "suspendido.",
                    ANSI_AMARILLO,
                )
            )
            _pausar()
            return
        except ConfiguracionDesactualizadaError as error:
            db.rollback()
            print(
                _estilizar(
                    "La configuración cambió mientras confirmabas. "
                    "Revisa el estado actual y confirma de nuevo.",
                    ANSI_AMARILLO,
                )
            )
            if error.configuracion_actual is not None:
                print(
                    "Modalidad actual: "
                    f"{_nombre_modalidad(error.configuracion_actual.modalidad)}"
                )
            return
        except SQLAlchemyError:
            _informar_error_consulta(db)
            _pausar()
            return

        if resultado.cambio_realizado:
            print(
                _estilizar(
                    "Modalidad guardada: "
                    f"{_nombre_modalidad(resultado.configuracion.modalidad)}.",
                    ANSI_VERDE,
                )
            )
        else:
            print(
                _estilizar(
                    "La modalidad seleccionada ya está activa. "
                    "No se realizaron cambios.",
                    ANSI_AMARILLO,
                )
            )
        _pausar()
        return


def _fecha_historial(fecha: datetime) -> str:
    return fecha.isoformat(timespec="seconds")


def _mostrar_historial(filas: list[HistorialModalidadDTO]) -> None:
    print(_estilizar("\nHISTORIAL DE MODALIDADES", ANSI_CIAN_BRILLANTE))
    if not filas:
        print("No hay cambios registrados.")
        return

    for fila in filas:
        anterior = _nombre_modalidad(fila.modalidad_anterior)
        nueva = _nombre_modalidad(fila.modalidad_nueva)
        print(f"{_fecha_historial(fila.cambiado_en)} | {anterior} → {nueva}")
    print(f"\nSe muestran hasta {LIMITE_HISTORIAL_MODALIDAD} cambios recientes.")


def _consultar_historial(db: Session) -> None:
    try:
        historial = listar_historial_modalidad(db)
    except SQLAlchemyError:
        _informar_error_consulta(db)
        _pausar()
        return
    _mostrar_historial(historial)
    _pausar()


def main(*, db: Session | None = None) -> int:
    """Ejecuta el submenu usando la sesion compartida del CLI administrativo."""

    db_propia = db is None
    sesion = db if db is not None else SessionLocal()
    try:
        while True:
            limpiar_pantalla()
            try:
                configuracion = obtener_configuracion_estacionamiento(sesion)
            except SQLAlchemyError:
                _informar_error_consulta(sesion)
                _pausar()
                return 1

            _mostrar_menu(configuracion)
            opcion = _leer_opcion("Opción: ", {"0", "1", "2"})
            if opcion is None:
                continue
            if opcion == "0":
                return 0
            if opcion == "1":
                _seleccionar_modalidad(sesion, configuracion)
            else:
                _consultar_historial(sesion)
    except KeyboardInterrupt, EOFError:
        sesion.rollback()
        print(_estilizar("\nConfiguración cancelada.", ANSI_AMARILLO), file=sys.stderr)
        return 1
    finally:
        if db_propia:
            sesion.close()


if __name__ == "__main__":
    raise SystemExit(main())
