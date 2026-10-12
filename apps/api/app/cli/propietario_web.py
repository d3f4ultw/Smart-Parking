"""Emite el acceso local a la gestion Web temporal de OWNER."""

from __future__ import annotations

import sys
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.servicios.gestion_propietario import emitir_sesion_gestion

RUTA_GESTION_PROPIETARIO = "/admin/gestion-propietario"


def _construir_url_gestion(base_url: str, ticket: str) -> str:
    """Agrega el ticket como fragmento sin aceptar redirects o query externos."""

    origen = urlsplit(base_url)
    if (
        origen.scheme not in {"http", "https"}
        or not origen.netloc
        or origen.username is not None
        or origen.password is not None
        or origen.query
        or origen.fragment
    ):
        raise ValueError("APP_PUBLIC_URL no es un origen publico valido.")
    base_path = origen.path.rstrip("/")
    ruta = f"{base_path}{RUTA_GESTION_PROPIETARIO}"
    return urlunsplit((origen.scheme, origen.netloc, ruta, "", ticket))


def _formatear_codigo(codigo: str) -> str:
    return "-".join(codigo[indice : indice + 4] for indice in range(0, len(codigo), 4))


def main(
    *,
    db: Session | None = None,
    settings: Settings | None = None,
) -> int:
    """Emite una URL reutilizable y su codigo separado de apareamiento."""

    sesion_local = db or SessionLocal()
    cerrar_sesion = db is None
    valores = settings or get_settings()
    try:
        resultado = emitir_sesion_gestion(sesion_local)
        if resultado.estado == "activa":
            print("STATUS=ACTIVE")
            print("La sesion Web de OWNER existente sigue activa.")
            return 0
        if resultado.ticket is None or resultado.codigo_apareamiento is None:
            print("STATUS=ERROR")
            print("No se pudo emitir el acceso Web de OWNER.")
            return 1
        url = _construir_url_gestion(valores.app_public_url, resultado.ticket)
        print("STATUS=READY")
        print(f"URL={url}")
        print(f"PAIRING_CODE={_formatear_codigo(resultado.codigo_apareamiento)}")
        return 0
    except SQLAlchemyError, ValueError:
        print("STATUS=ERROR")
        print("No se pudo preparar el acceso Web de OWNER.")
        return 1
    finally:
        if cerrar_sesion:
            sesion_local.close()


if __name__ == "__main__":
    sys.exit(main())
