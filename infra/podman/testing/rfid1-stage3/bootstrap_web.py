"""Crea exclusivamente las identidades sintéticas para la aceptación Stage 3."""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "infra/podman/testing/rfid1-stage2"))

from aceptacion_api import crear_empleado, crear_propietario  # noqa: E402
from http_aceptacion import ClienteHttp, csrf, exigir  # noqa: E402


def crear_cliente_sintetico(
    base_url: str,
    propietario: ClienteHttp,
    nombre: str,
    correo: str,
    contrasena: str,
) -> None:
    cliente = ClienteHttp(base_url)
    token_cliente = csrf(cliente, "/api/v1/clientes/csrf")
    respuesta = cliente.solicitar(
        "POST",
        "/api/v1/clientes/registro",
        {
            "nombres": nombre,
            "primerApellido": "Sintetico",
            "segundoApellido": None,
            "correo": correo,
            "contrasena": contrasena,
        },
        {"X-CSRF-TOKEN": token_cliente},
    )
    exigir(respuesta.estado == 201, "crear cliente sintético aislado")
    directorio = propietario.solicitar("GET", "/api/v1/clientes/administracion?pagina=1")
    exigir(directorio.estado == 200, "leer directorio de clientes sintéticos")
    existe = any(
        item.get("nombreCompleto") == f"{nombre} Sintetico"
        for item in directorio.json().get("items", [])
    )
    exigir(existe, "confirmar cliente visible en el directorio DUENO")


def main() -> None:
    base_url = os.environ["RFID1_STAGE3_API_URL"]
    os.environ["RFID1_STAGE2_OWNER_EMAIL"] = os.environ["RFID1_STAGE3_OWNER_EMAIL"]
    os.environ["RFID1_STAGE2_OWNER_PASSWORD"] = os.environ["RFID1_STAGE3_OWNER_PASSWORD"]
    os.environ["RFID1_STAGE2_ADMIN_PASSWORD"] = os.environ["RFID1_STAGE3_ADMIN_PASSWORD"]
    propietario, token = crear_propietario(base_url, "stage3")
    crear_empleado(propietario, token, "Stage3")
    crear_empleado(propietario, token, "Fisico")
    crear_cliente_sintetico(
        base_url,
        propietario,
        "Cliente Stage 3",
        os.environ["RFID1_STAGE3_CLIENT_EMAIL"],
        os.environ["RFID1_STAGE3_CLIENT_PASSWORD"],
    )
    sufijo = secrets.token_hex(6)
    crear_cliente_sintetico(
        base_url,
        propietario,
        "Cliente Fisico Stage 3",
        f"cliente-fisico-rfid-stage3-{sufijo}@example.invalid",
        secrets.token_hex(24),
    )
    print("Bootstrap aislado completo: 1 DUENO, 2 CLIENTES y 2 EMPLEADOS sintéticos.")


if __name__ == "__main__":
    main()
