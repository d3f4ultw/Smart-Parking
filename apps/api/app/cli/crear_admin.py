"""CLI interactiva para crear un ADMIN y entregar su enlace de activacion."""

from __future__ import annotations

import sys

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.cli.invitaciones_admin import crear_callback_entrega_admin
from app.cli.presentacion import (
    ANSI_CIAN_BRILLANTE,
    ANSI_ROJO,
    ANSI_VERDE,
    _estilizar,
    limpiar_pantalla,
)
from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.correo.errores import (
    ConfiguracionSMTPInvalidaError,
    ErrorCorreo,
)
from app.correo.smtp import TransporteCorreo
from app.seguridad.correos import CorreoInvalidoError
from app.servicios.usuarios import (
    CorreoDuplicadoError,
    DatosAdmin,
    ErrorCreacionAdmin,
    correo_esta_registrado,
    crear_admin_pendiente,
    preparar_datos_admin,
)


def _pedir_datos_personales(db: Session) -> DatosAdmin:
    nombre = input("Nombre: ")
    apellido_paterno = input("Apellido paterno: ")
    apellido_materno = input("Apellido materno: ")

    while True:
        correo = input("Correo: ")

        try:
            datos = preparar_datos_admin(
                nombre=nombre,
                apellido_paterno=apellido_paterno,
                apellido_materno=apellido_materno,
                correo=correo,
            )
        except CorreoInvalidoError as error:
            print(
                _estilizar(
                    f"Error: {error} Ingresa un correo valido.",
                    ANSI_ROJO,
                ),
                file=sys.stderr,
            )
            continue

        if correo_esta_registrado(db, datos.correo):
            print(
                _estilizar(
                    "Error: el correo ya esta registrado. Ingresa otro correo.",
                    ANSI_ROJO,
                ),
                file=sys.stderr,
            )
            continue
        return datos


def main(
    *,
    db: Session | None = None,
    transporte: TransporteCorreo | None = None,
    settings: Settings | None = None,
) -> int:
    """Crea un ADMIN pendiente y entrega un enlace de un solo uso."""

    db_propia = db is None
    sesion = db if db is not None else SessionLocal()
    settings_efectivos = settings or get_settings()
    try:
        limpiar_pantalla()
        print(
            _estilizar(
                "SMART PARKING — CREAR ADMINISTRADOR",
                ANSI_CIAN_BRILLANTE,
            )
        )
        datos = _pedir_datos_personales(sesion)
        crear_admin_pendiente(
            sesion,
            nombre=datos.nombre,
            apellido_paterno=datos.apellido_paterno,
            apellido_materno=datos.apellido_materno,
            correo=datos.correo,
            entregar_invitacion=crear_callback_entrega_admin(
                settings=settings_efectivos,
                transporte=transporte,
            ),
            duracion_token_horas=settings_efectivos.activation_token_ttl_hours,
        )
        print(_estilizar("ADMIN creado. Correo de activacion enviado.", ANSI_VERDE))
        return 0
    except KeyboardInterrupt, EOFError:
        print(
            _estilizar("\nCreacion cancelada.", ANSI_ROJO),
            file=sys.stderr,
        )
        return 1
    except CorreoDuplicadoError:
        print(
            _estilizar("Error: el correo ya esta registrado.", ANSI_ROJO),
            file=sys.stderr,
        )
        return 1
    except (CorreoInvalidoError, ErrorCreacionAdmin) as error:
        print(_estilizar(f"Error: {error}", ANSI_ROJO), file=sys.stderr)
        return 1
    except ConfiguracionSMTPInvalidaError, ErrorCorreo:
        print(
            _estilizar(
                "No fue posible completar la entrega de la invitacion ADMIN.",
                ANSI_ROJO,
            ),
            file=sys.stderr,
        )
        return 1
    except SQLAlchemyError:
        print(
            _estilizar("No fue posible crear el ADMIN.", ANSI_ROJO),
            file=sys.stderr,
        )
        return 1
    finally:
        if db_propia:
            sesion.close()


if __name__ == "__main__":
    raise SystemExit(main())
