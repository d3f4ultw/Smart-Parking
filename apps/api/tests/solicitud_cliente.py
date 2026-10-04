"""Ayudas para solicitudes aisladas con cookies en TestClient."""

from __future__ import annotations

from collections.abc import Mapping
from http.cookies import Morsel
from typing import Any

from fastapi.testclient import TestClient
from httpx2 import Response


def solicitar_con_cookies(
    client: TestClient,
    metodo: str,
    ruta: str,
    *,
    cookies: Mapping[str, Any] | None = None,
    **opciones: Any,
) -> Response:
    """Aplica cookies por una sola solicitud y restaura el jar previo."""

    cookies_previas = list(client.cookies.jar)
    try:
        if cookies is None:
            client.cookies.clear()
        else:
            for nombre, valor in cookies.items():
                valor_cookie = valor.value if isinstance(valor, Morsel) else valor
                client.cookies.set(nombre, str(valor_cookie))
        return client.request(metodo, ruta, **opciones)
    finally:
        client.cookies.clear()
        for cookie in cookies_previas:
            client.cookies.jar.set_cookie(cookie)
