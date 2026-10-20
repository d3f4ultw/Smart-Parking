from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.limite_cuerpo_registro import LimitarCuerpoRegistroCliente


@pytest.mark.parametrize(
    "ruta",
    [
        "/api/clientes/registro",
        "/api/clientes/autenticacion/login",
        "/api/clientes/contrasena",
    ],
)
def test_cuerpos_de_cliente_mayores_a_8_kib_se_rechazan_sin_reflejarse(
    ruta: str,
) -> None:
    aplicacion = FastAPI()
    aplicacion.add_middleware(LimitarCuerpoRegistroCliente)
    secreto = b"NoImprimirEsteValor"
    cuerpo = b"{" + b" " * (8 * 1024) + secreto + b"}"

    with TestClient(aplicacion) as cliente:
        respuesta = cliente.post(
            ruta,
            content=cuerpo,
            headers={"content-type": "application/json"},
        )

    assert respuesta.status_code == 413
    assert respuesta.headers["cache-control"] == "no-store"
    assert secreto.decode() not in respuesta.text


@pytest.mark.parametrize(
    "ruta",
    [
        "/api/clientes/registro",
        "/api/clientes/autenticacion/login",
        "/api/clientes/contrasena",
    ],
)
def test_cuerpos_de_cliente_sin_json_se_rechazan_antes_de_procesarse(
    ruta: str,
) -> None:
    aplicacion = FastAPI()
    aplicacion.add_middleware(LimitarCuerpoRegistroCliente)

    with TestClient(aplicacion) as cliente:
        respuesta = cliente.post(
            ruta,
            content=b"correo=privado@example.com&contrasena=NoImprimir1!",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

    assert respuesta.status_code == 415
    assert respuesta.headers["cache-control"] == "no-store"
    assert "privado@example.com" not in respuesta.text
    assert "NoImprimir1!" not in respuesta.text
