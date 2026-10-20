"""Limita solicitudes publicas de registro antes de parsear el cuerpo JSON."""

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.rutas.autenticacion_clientes import RUTA_LOGIN_CLIENTE
from app.api.rutas.contrasena_clientes import RUTA_CAMBIO_CONTRASENA_CLIENTE
from app.api.rutas.cuentas_clientes import RUTA_REGISTRO_CLIENTE

TAMANO_MAXIMO_REGISTRO_BYTES = 8 * 1024
DETALLE_CUERPO_REGISTRO_INVALIDO = "Solicitud invalida"


class _CuerpoRegistroDemasiadoGrande(Exception):
    """Interrumpe el parser cuando el cuerpo supera el limite de registro."""


class LimitarCuerpoRegistroCliente:
    """Limita y valida cuerpos de JSON de autenticacion/cuenta cliente."""

    RUTAS_PROTEGIDAS = frozenset(
        {
            RUTA_REGISTRO_CLIENTE,
            RUTA_LOGIN_CLIENTE,
            RUTA_CAMBIO_CONTRASENA_CLIENTE,
        }
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] not in self.RUTAS_PROTEGIDAS
        ):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if scope.get("query_string"):
            await self._responder(scope, receive, send, 422)
            return
        if not self._es_json(headers.get("content-type")):
            await self._responder(scope, receive, send, 415)
            return

        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                tamano_declarado = int(content_length)
            except ValueError:
                await self._responder(scope, receive, send, 400)
                return
            if tamano_declarado < 0:
                await self._responder(scope, receive, send, 400)
                return
            if tamano_declarado > TAMANO_MAXIMO_REGISTRO_BYTES:
                await self._responder(scope, receive, send, 413)
                return

        tamano_recibido = 0

        async def recibir_con_limite() -> Message:
            nonlocal tamano_recibido
            mensaje = await receive()
            if mensaje["type"] == "http.request":
                tamano_recibido += len(mensaje.get("body", b""))
                if tamano_recibido > TAMANO_MAXIMO_REGISTRO_BYTES:
                    raise _CuerpoRegistroDemasiadoGrande
            return mensaje

        try:
            await self.app(scope, recibir_con_limite, send)
        except _CuerpoRegistroDemasiadoGrande:
            await self._responder(scope, receive, send, 413)

    @staticmethod
    def _es_json(content_type: str | None) -> bool:
        if content_type is None:
            return False
        tipo_base = content_type.split(";", maxsplit=1)[0].strip().lower()
        return tipo_base == "application/json"

    @staticmethod
    async def _responder(
        scope: Scope,
        receive: Receive,
        send: Send,
        codigo: int,
    ) -> None:
        respuesta = JSONResponse(
            status_code=codigo,
            content={"detail": DETALLE_CUERPO_REGISTRO_INVALIDO},
            headers={"Cache-Control": "no-store"},
        )
        await respuesta(scope, receive, send)


__all__ = ["LimitarCuerpoRegistroCliente", "TAMANO_MAXIMO_REGISTRO_BYTES"]
