"""Cliente HTTP y helpers de contrato para la aceptación RFID 1."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from http.cookiejar import CookieJar


class Respuesta:
    def __init__(self, estado: int, cuerpo: bytes, encabezados) -> None:
        self.estado = estado
        self.cuerpo = cuerpo
        self.encabezados = encabezados

    def json(self):
        return json.loads(self.cuerpo) if self.cuerpo else None


class ClienteHttp:
    def __init__(self, base_url: str, cookie: str | None = None, bearer: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookies = CookieJar()
        self.abridor = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.cookie = cookie
        self.bearer = bearer

    def solicitar(self, metodo: str, ruta: str, cuerpo=None, encabezados=None) -> Respuesta:
        headers = {"Accept": "application/json"}
        if cuerpo is not None:
            headers["Content-Type"] = "application/json"
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.bearer:
            headers["Authorization"] = f"Bearer {self.bearer}"
        if encabezados:
            headers.update(encabezados)
        datos = None if cuerpo is None else json.dumps(cuerpo, separators=(",", ":")).encode()
        solicitud = urllib.request.Request(
            self.base_url + ruta,
            data=datos,
            headers=headers,
            method=metodo,
        )
        try:
            with self.abridor.open(solicitud, timeout=5) as respuesta:
                return Respuesta(respuesta.status, respuesta.read(8192), respuesta.headers)
        except urllib.error.HTTPError as error:
            return Respuesta(error.code, error.read(8192), error.headers)


def exigir(condicion: bool, nombre: str) -> None:
    if not condicion:
        raise RuntimeError(f"FAIL: {nombre}")
    print(f"PASS: {nombre}")


def csrf(cliente: ClienteHttp, ruta: str = "/api/v1/csrf") -> str:
    respuesta = cliente.solicitar("GET", ruta)
    exigir(respuesta.estado == 200, "obtener token CSRF")
    token = respuesta.json().get("token")
    exigir(isinstance(token, str) and bool(token), "respuesta CSRF completa")
    return token


def clave_idempotencia() -> str:
    return str(uuid.uuid4())


def clave_lectura(captura_id: str, request_id: str) -> str:
    return str(uuid.uuid5(uuid.UUID(hex=captura_id), request_id.upper()))


def crear_captura(cliente: ClienteHttp, token_csrf: str, tipo: str, codigo: str, clave: str | None = None):
    return cliente.solicitar(
        "POST",
        "/api/v1/rfid-1/capturas",
        {"tipoEntidad": tipo, "codigoPersona": codigo},
        {
            "X-CSRF-TOKEN": token_csrf,
            "Idempotency-Key": clave or clave_idempotencia(),
        },
    )


def leer_tarjeta(cliente: ClienteHttp, captura_id: str, request_id: str, uid: str):
    return cliente.solicitar(
        "POST",
        "/api/v1/dispositivos/rfid-1/lecturas",
        {"capturaId": captura_id, "requestId": request_id, "uid": uid},
        {"Idempotency-Key": clave_lectura(captura_id, request_id)},
    )
