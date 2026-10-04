"""CLI interactiva para consultar y gestionar ADMIN existentes."""

from __future__ import annotations

import sys

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.cli.invitaciones_admin import crear_callback_entrega_admin
from app.cli.presentacion import (
    ANSI_AMARILLO,
    ANSI_CIAN,
    ANSI_CIAN_BRILLANTE,
    ANSI_DIM,
    ANSI_REINICIO,
    ANSI_ROJO,
    ANSI_VERDE,
    _estilizar,
    limpiar_pantalla,
)
from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.correo.errores import ConfiguracionSMTPInvalidaError, ErrorCorreo
from app.correo.smtp import TransporteCorreo
from app.servicios.administradores import (
    AdministradorDTO,
    AdministradorNoEncontradoError,
    AdministradorNoPendienteError,
    AdministradorYaActivoError,
    AdministradorYaInactivoError,
    CooldownReenvioAdministradorError,
    ErrorGestionAdministrador,
    desactivar_administrador,
    listar_administradores,
    obtener_administrador,
    reactivar_administrador,
    reenviar_invitacion_administrador,
)

__all__ = [
    "ANSI_AMARILLO",
    "ANSI_CIAN",
    "ANSI_CIAN_BRILLANTE",
    "ANSI_DIM",
    "ANSI_REINICIO",
    "ANSI_ROJO",
    "ANSI_VERDE",
    "limpiar_pantalla",
]


def _campo_alineado(
    texto: str,
    ancho: int,
    *,
    codigo: str | None = None,
) -> str:
    """Rellena primero el texto y despues aplica color para no romper columnas."""

    return _estilizar(texto.ljust(ancho), codigo)


def _color_activacion(estado: str) -> str | None:
    return ANSI_AMARILLO if "Pendiente" in estado else None


def _mensaje_cooldown(segundos_restantes: int) -> str:
    palabra = "segundo" if segundos_restantes == 1 else "segundos"
    return (
        f"Debes esperar {segundos_restantes} {palabra} antes de reenviar "
        "otra activación."
    )


def _pausar() -> None:
    input("Presiona Enter para continuar...")


def _nombre_completo(administrador: AdministradorDTO) -> str:
    partes = (
        administrador.nombre,
        administrador.apellido_paterno,
        administrador.apellido_materno,
    )
    return " ".join(parte for parte in partes if parte) or "(sin nombre)"


COLUMNAS_TABLA_ADMIN = (
    "id",
    "nombre",
    "correo",
    "estado",
    "verificacion",
    "activacion",
)
ENCABEZADOS_TABLA_ADMIN = {
    "id": "ID",
    "nombre": "Nombre",
    "correo": "Correo",
    "estado": "Estado",
    "verificacion": "Verificacion",
    "activacion": "Activacion",
}
# Perfil compartido para que el detalle no estreche columnas por mostrar una
# sola fila. Los valores que excedan este minimo expanden la tabla.
ANCHOS_BASE_TABLA_ADMIN = {
    "id": 3,
    "nombre": 31,
    "correo": 24,
    "estado": 26,
    "verificacion": 13,
    "activacion": 26,
}


def _fila_administrador(administrador: AdministradorDTO) -> dict[str, str]:
    return {
        "id": str(administrador.id),
        "nombre": _nombre_completo(administrador),
        "correo": administrador.correo,
        "estado": _estado_administrador(administrador),
        "verificacion": (
            "Verificado" if administrador.correo_verificado else "No verificado"
        ),
        "activacion": administrador.estado_activacion,
    }


def _estado_administrador(administrador: AdministradorDTO) -> str:
    if not administrador.esta_activo:
        return "Inactivo"
    elif administrador.correo_verificado and not administrador.debe_cambiar_contrasena:
        return "Acceso habilitado"
    return "Pendiente de activación"


def _anchos_tabla_administradores(filas: list[dict[str, str]]) -> dict[str, int]:
    return {
        clave: max(
            ANCHOS_BASE_TABLA_ADMIN[clave],
            len(ENCABEZADOS_TABLA_ADMIN[clave]),
            *(len(fila[clave]) for fila in filas),
        )
        for clave in COLUMNAS_TABLA_ADMIN
    }


def _mostrar_tabla_administradores(
    administradores: list[AdministradorDTO],
    *,
    titulo: str,
) -> None:
    print(_estilizar(f"\n{titulo}", ANSI_CIAN_BRILLANTE))
    if not administradores:
        print("No hay ADMIN registrados.")
        return

    filas = [_fila_administrador(administrador) for administrador in administradores]
    anchos = _anchos_tabla_administradores(filas)
    encabezado = " | ".join(
        _campo_alineado(ENCABEZADOS_TABLA_ADMIN[clave], anchos[clave])
        for clave in COLUMNAS_TABLA_ADMIN
    )
    separador = "-" * len(encabezado)
    print(_estilizar(encabezado, ANSI_CIAN))
    print(_estilizar(separador, ANSI_DIM))

    for fila in filas:
        colores = {
            "estado": (
                ANSI_VERDE
                if fila["estado"] == "Acceso habilitado"
                else ANSI_AMARILLO
                if fila["estado"] == "Pendiente de activación"
                else ANSI_ROJO
            ),
            "verificacion": (
                ANSI_VERDE if fila["verificacion"] == "Verificado" else ANSI_AMARILLO
            ),
            "activacion": _color_activacion(fila["activacion"]),
        }
        print(
            " | ".join(
                _campo_alineado(
                    fila[clave],
                    anchos[clave],
                    codigo=colores.get(clave),
                )
                for clave in COLUMNAS_TABLA_ADMIN
            )
        )

    print(_estilizar(separador, ANSI_DIM))


def _mostrar_menu() -> None:
    print(_estilizar("SMART PARKING — GESTIÓN DE ADMINISTRADORES", ANSI_CIAN_BRILLANTE))
    print("1. Ver administradores")
    print(_estilizar("0. Salir", ANSI_DIM))


def _mostrar_lista(administradores: list[AdministradorDTO]) -> None:
    _mostrar_tabla_administradores(
        administradores,
        titulo="SMART PARKING — ADMIN registrados",
    )
    print(_estilizar("0. Volver", ANSI_DIM))


def _mostrar_detalle(administrador: AdministradorDTO) -> None:
    _mostrar_tabla_administradores(
        [administrador],
        titulo="SMART PARKING — ADMIN seleccionado",
    )


def _confirmar(accion: str, administrador: AdministradorDTO) -> bool:
    respuesta = input(f"Confirmar {accion} para {administrador.correo}? [s/N]: ")
    return respuesta.strip().casefold() in {"s", "si", "sí"}


def _leer_id(mensaje: str, *, permitir_cero: bool = False) -> int | None:
    valor = input(mensaje).strip()
    if permitir_cero and valor == "0":
        return 0
    try:
        identificador = int(valor)
    except ValueError:
        print(
            _estilizar("Ingresa un ID numerico positivo.", ANSI_ROJO), file=sys.stderr
        )
        return None
    if identificador <= 0:
        print(
            _estilizar("Ingresa un ID numerico positivo.", ANSI_ROJO), file=sys.stderr
        )
        return None
    return identificador


def _mostrar_acciones(administrador: AdministradorDTO) -> None:
    estado = _estado_administrador(administrador)
    if estado == "Inactivo":
        print("1. Reactivar administrador")
    elif estado == "Acceso habilitado":
        print("1. Desactivar administrador")
    else:
        print("1. Reenviar invitación")
        print("2. Desactivar administrador")
    print(_estilizar("0. Volver", ANSI_DIM))


def _opciones_detalle(administrador: AdministradorDTO) -> set[str]:
    if not administrador.esta_activo:
        return {"1", "0"}
    if administrador.correo_verificado:
        return {"1", "0"}
    return {"1", "2", "0"}


def _informar_error_consulta() -> None:
    print(_estilizar("No fue posible consultar los ADMIN.", ANSI_ROJO), file=sys.stderr)


def _gestionar_reenvio(
    db: Session,
    administrador: AdministradorDTO,
    *,
    transporte: TransporteCorreo | None,
    settings: Settings,
) -> None:
    db.rollback()
    try:
        reenviar_invitacion_administrador(
            db,
            administrador.id,
            cooldown_segundos=settings.activacion_reenvio_cooldown_segundos,
            duracion_token_horas=settings.activation_token_ttl_hours,
            entregar_invitacion=crear_callback_entrega_admin(
                settings=settings,
                transporte=transporte,
            ),
        )
    except CooldownReenvioAdministradorError as error:
        print(_estilizar(_mensaje_cooldown(error.segundos_restantes), ANSI_AMARILLO))
        _pausar()
        return
    except AdministradorNoPendienteError:
        print(
            _estilizar("El ADMIN ya no tiene una invitacion pendiente.", ANSI_ROJO),
            file=sys.stderr,
        )
        _pausar()
        return
    except ConfiguracionSMTPInvalidaError, ErrorCorreo:
        print(
            _estilizar(
                "No se pudo entregar la invitacion; la invitacion anterior "
                "se conserva.",
                ANSI_ROJO,
            ),
            file=sys.stderr,
        )
        _pausar()
        return
    except SQLAlchemyError:
        db.rollback()
        print(
            _estilizar("No fue posible reenviar la activacion.", ANSI_ROJO),
            file=sys.stderr,
        )
        _pausar()
        return

    print(_estilizar("Invitacion reenviada correctamente.", ANSI_VERDE))
    _pausar()


def _gestionar_detalle(
    db: Session,
    administrador_id: int,
    *,
    transporte: TransporteCorreo | None,
    settings: Settings,
) -> None:
    while True:
        limpiar_pantalla()
        db.rollback()
        try:
            administrador = obtener_administrador(db, administrador_id)
        except AdministradorNoEncontradoError:
            print(
                _estilizar("No se encontro el ADMIN solicitado.", ANSI_ROJO),
                file=sys.stderr,
            )
            _pausar()
            return
        except SQLAlchemyError:
            _informar_error_consulta()
            _pausar()
            return

        _mostrar_detalle(administrador)
        _mostrar_acciones(administrador)
        opcion = input("Opcion: ").strip()
        if opcion == "0":
            return
        if opcion not in _opciones_detalle(administrador):
            print(_estilizar("Opcion no valida.", ANSI_ROJO), file=sys.stderr)
            continue

        if not administrador.esta_activo:
            if not _confirmar("la reactivacion", administrador):
                continue
            db.rollback()
            try:
                reactivar_administrador(db, administrador.id)
            except AdministradorYaActivoError:
                print(_estilizar("El ADMIN ya esta activo.", ANSI_AMARILLO))
            except AdministradorNoEncontradoError:
                print(
                    _estilizar(
                        "El ADMIN ya no existe o cambio de estado.",
                        ANSI_ROJO,
                    ),
                    file=sys.stderr,
                )
            except SQLAlchemyError:
                db.rollback()
                print(
                    _estilizar("No fue posible reactivar el ADMIN.", ANSI_ROJO),
                    file=sys.stderr,
                )
            else:
                print(_estilizar("ADMIN reactivado correctamente.", ANSI_VERDE))
            _pausar()
            continue

        if opcion == "1" and not administrador.correo_verificado:
            _gestionar_reenvio(
                db,
                administrador,
                transporte=transporte,
                settings=settings,
            )
            continue

        if not _confirmar("la desactivacion", administrador):
            continue
        db.rollback()
        try:
            desactivar_administrador(db, administrador.id)
        except AdministradorYaInactivoError:
            print(_estilizar("El ADMIN ya esta inactivo.", ANSI_AMARILLO))
        except AdministradorNoEncontradoError:
            print(
                _estilizar("El ADMIN ya no existe o cambio de estado.", ANSI_ROJO),
                file=sys.stderr,
            )
        except SQLAlchemyError:
            db.rollback()
            print(
                _estilizar("No fue posible desactivar el ADMIN.", ANSI_ROJO),
                file=sys.stderr,
            )
        else:
            print(_estilizar("ADMIN desactivado correctamente.", ANSI_VERDE))
        _pausar()


def _flujo_lista(
    db: Session,
    *,
    transporte: TransporteCorreo | None,
    settings: Settings,
) -> None:
    while True:
        limpiar_pantalla()
        db.rollback()
        try:
            administradores = listar_administradores(db)
        except SQLAlchemyError:
            _informar_error_consulta()
            _pausar()
            return
        _mostrar_lista(administradores)
        identificador = _leer_id(
            "Selecciona un ADMIN por ID (0 para volver): ",
            permitir_cero=True,
        )
        if identificador is None:
            continue
        if identificador == 0:
            return
        _gestionar_detalle(
            db,
            identificador,
            transporte=transporte,
            settings=settings,
        )


def main(
    *,
    db: Session | None = None,
    transporte: TransporteCorreo | None = None,
    settings: Settings | None = None,
) -> int:
    """Ejecuta el menu y devuelve un codigo de salida apto para wrappers."""

    db_propia = db is None
    sesion = db if db is not None else SessionLocal()
    try:
        settings_efectivos = settings or get_settings()
        while True:
            limpiar_pantalla()
            _mostrar_menu()
            opcion = input("Opcion: ").strip()
            if opcion == "0":
                return 0
            if opcion == "1":
                _flujo_lista(
                    sesion,
                    transporte=transporte,
                    settings=settings_efectivos,
                )
            else:
                print(_estilizar("Opcion no valida.", ANSI_ROJO), file=sys.stderr)
    except KeyboardInterrupt, EOFError:
        print(_estilizar("\nGestion cancelada.", ANSI_ROJO), file=sys.stderr)
        return 1
    except ErrorGestionAdministrador as error:
        print(_estilizar(f"Error: {error}", ANSI_ROJO), file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print(
            _estilizar("No fue posible completar la gestion de ADMIN.", ANSI_ROJO),
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            _estilizar(
                "Ocurrio un error interno durante la gestion de ADMIN.",
                ANSI_ROJO,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if db_propia:
            sesion.close()


if __name__ == "__main__":
    raise SystemExit(main())
