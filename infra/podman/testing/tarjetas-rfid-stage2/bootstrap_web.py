"""Prepara identidades sintéticas para la aceptación Web de Stage 2."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "infra/podman/testing/rfid1-stage2"))

from aceptacion_api import crear_empleado, crear_propietario  # noqa: E402
from http_aceptacion import ClienteHttp, csrf, exigir  # noqa: E402


def crear_cliente_sintetico(base_url: str) -> None:
    correo = os.environ["RFID1_STAGE2_CLIENT_EMAIL"]
    contrasena = os.environ["RFID1_STAGE2_CLIENT_PASSWORD"]
    cliente = ClienteHttp(base_url)
    token = csrf(cliente, "/api/v1/clientes/csrf")
    respuesta = cliente.solicitar(
        "POST",
        "/api/v1/clientes/registro",
        {
            "nombres": "Cliente Stage 2",
            "primerApellido": "Sintetico",
            "segundoApellido": None,
            "correo": correo,
            "contrasena": contrasena,
        },
        {"X-CSRF-TOKEN": token},
    )
    exigir(respuesta.estado == 201, "crear CLIENTE sintético sin membresía")


def main() -> None:
    base_url = os.environ["RFID1_STAGE2_API_URL"]
    dueno, token = crear_propietario(base_url, "tarjetas-stage2")
    crear_cliente_sintetico(base_url)
    crear_empleado(dueno, token, "Stage 2")
    directorio = dueno.solicitar("GET", "/api/v1/clientes/administracion?pagina=1")
    exigir(directorio.estado == 200, "consultar directorio CLIENTE sintético")
    existe = any(
        elemento.get("nombreCompleto") == "Cliente Stage 2 Sintetico"
        for elemento in directorio.json().get("items", [])
    )
    exigir(existe, "confirmar CLIENTE visible para DUENO")
    print("Bootstrap Stage 2 listo: un DUENO, un CLIENTE y un EMPLEADO sintéticos.")


if __name__ == "__main__":
    main()
