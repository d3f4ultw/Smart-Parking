"""Endpoint SSE autenticado con politicas de eventos por rol."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Callable,
    Coroutine,
)
from dataclasses import dataclass, field
from threading import Lock
from typing import Annotated, Any, NoReturn
from uuid import UUID

from anyio import CancelScope
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.routing import APIRoute
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.servicios.autenticacion import obtener_usuario_por_token
from app.servicios.eventos_operadores import (
    LimiteConexionesSSEError,
    ResultadoLoteEventosSSE,
    SesionTiempoRealNoValidaError,
    admitir_conexion_sse,
    cerrar_conexion_sse,
    consultar_lote_eventos_usuario,
    cursor_necesita_resync,
    obtener_marca_eventos,
    tipos_autorizados_para_rol,
)

RUTA_EVENTOS_TIEMPO_REAL = "/api/eventos"
RUTA_EVENTOS_OPERADORES_COMPATIBILIDAD = "/api/admin/operadores/eventos"
DETALLE_SESION_NO_AUTENTICADA = "No autenticado"
CABECERAS_SSE = {"Cache-Control": "no-store"}
INTERVALO_POLL_SSE = 1.0
INTERVALO_REVALIDACION_SSE = 10.0
INTERVALO_HEARTBEAT_SSE = 15.0
CURSOR_DECIMAL_MAXIMO_DIGITOS = 19
CLAVE_CONTEXTO_STREAM_SSE = "smart_parking.contexto_stream_sse"
CLAVE_RESPUESTA_STREAM_SSE = "smart_parking.respuesta_stream_sse"

logger = logging.getLogger(__name__)
_candado_contextos_stream_sse = Lock()
_contextos_stream_sse_activos: dict[UUID, ContextoStreamTiempoReal] = {}


def _registrar_contexto_stream_sse(contexto: ContextoStreamTiempoReal) -> None:
    """Conserva solo los streams vivos para poder cerrar sus leases al apagar."""

    with _candado_contextos_stream_sse:
        _contextos_stream_sse_activos[contexto.lease_id] = contexto


def _retirar_contexto_stream_sse(lease_id: UUID) -> None:
    """Elimina el contexto al finalizar el stream o su lease."""

    with _candado_contextos_stream_sse:
        _contextos_stream_sse_activos.pop(lease_id, None)


async def cerrar_leases_sse_activas() -> None:
    """Cierra leases del worker cuando Uvicorn cancela streams durante reload."""

    with _candado_contextos_stream_sse:
        contextos = tuple(_contextos_stream_sse_activos.values())

    for contexto in contextos:
        try:
            if not contexto.lease_cerrada:
                await _cerrar_lease_sse(contexto)
        finally:
            _retirar_contexto_stream_sse(contexto.lease_id)


@dataclass(slots=True)
class ContextoStreamTiempoReal:
    """Estado minimo de un stream; el token nunca se representa ni persiste."""

    usuario_id: int
    rol_usuario: str
    token_sesion: str = field(repr=False)
    lease_id: UUID
    cursor: int
    marca_inicial: int
    requiere_resync: bool
    iterador_eventos: AsyncGenerator[ServerSentEvent] | None = field(
        default=None,
        repr=False,
    )
    lease_cerrada: bool = field(default=False, repr=False)


async def _esperar_cierre_sse(
    operacion: Coroutine[Any, Any, None],
    *,
    mensaje_error: str,
) -> bool:
    """Espera una finalizacion protegida y propaga la cancelacion al terminar."""

    cancelada = False
    resultado = True
    with CancelScope(shield=True):
        tarea = asyncio.create_task(operacion)
        while True:
            try:
                await asyncio.shield(tarea)
            except asyncio.CancelledError:
                if tarea.cancelled():
                    raise
                cancelada = True
            except Exception as error:
                logger.warning("%s (%s)", mensaje_error, type(error).__name__)
                resultado = False
                break
            else:
                break

    if cancelada:
        raise asyncio.CancelledError
    return resultado


async def _finalizar_iterador_sse(iterador: AsyncIterable[Any] | None) -> None:
    """Cierra un iterador SSE sin dejar una tarea de limpieza separada."""

    if iterador is None:
        return
    cerrar = getattr(iterador, "aclose", None)
    if cerrar is None:
        return
    await _esperar_cierre_sse(
        cerrar(),
        mensaje_error="No se pudo finalizar un iterador SSE",
    )


async def _cerrar_lease_sse(contexto: ContextoStreamTiempoReal) -> None:
    """Persiste el cierre de una concesion y conserva el fallback por expiracion."""

    cerrada = await _esperar_cierre_sse(
        asyncio.to_thread(_cerrar_lease_en_sesion, contexto),
        mensaje_error="No se pudo cerrar una concesion SSE",
    )
    if cerrada:
        contexto.lease_cerrada = True
        _retirar_contexto_stream_sse(contexto.lease_id)


class RutaSSEConFinalizacion(APIRoute):
    """Finaliza el body y la concesion tras desmontar el productor de FastAPI."""

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        manejador = super().get_route_handler()

        async def manejar_y_conservar_respuesta(request: Request) -> Response:
            respuesta = await manejador(request)
            if (
                isinstance(respuesta, StreamingResponse)
                and respuesta.media_type == "text/event-stream"
            ):
                request.scope[CLAVE_RESPUESTA_STREAM_SSE] = respuesta
            return respuesta

        return manejar_y_conservar_respuesta

    async def handle(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        try:
            await super().handle(scope, receive, send)
        except ClientDisconnect:
            # Un socket que se cierra durante el stream es una salida normal.
            pass
        except BaseExceptionGroup as error:
            desconexiones, restantes = error.split(ClientDisconnect)
            if desconexiones is None or restantes is not None:
                raise
        finally:
            respuesta = scope.pop(CLAVE_RESPUESTA_STREAM_SSE, None)
            contexto = scope.pop(CLAVE_CONTEXTO_STREAM_SSE, None)
            try:
                if isinstance(respuesta, StreamingResponse):
                    await _finalizar_iterador_sse(respuesta.body_iterator)
            finally:
                if isinstance(contexto, ContextoStreamTiempoReal):
                    try:
                        await _finalizar_iterador_sse(contexto.iterador_eventos)
                    finally:
                        try:
                            if not contexto.lease_cerrada:
                                await _cerrar_lease_sse(contexto)
                        finally:
                            tarea = asyncio.current_task()
                            if (
                                contexto.lease_cerrada
                                or tarea is None
                                or tarea.cancelling() == 0
                            ):
                                _retirar_contexto_stream_sse(contexto.lease_id)


router = APIRouter(
    tags=["eventos-tiempo-real"],
    route_class=RutaSSEConFinalizacion,
)


def _error_sesion_no_autenticada() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=DETALLE_SESION_NO_AUTENTICADA,
        headers={"Cache-Control": "no-store"},
    )


def _error_cursor_sse() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Cursor de eventos invalido",
        headers={"Cache-Control": "no-store"},
    )


def _interpretar_cursor_sse(valor: str | None, marca: int) -> int:
    if valor is None:
        return marca
    if (
        not valor
        or len(valor) > CURSOR_DECIMAL_MAXIMO_DIGITOS
        or any(caracter < "0" or caracter > "9" for caracter in valor)
    ):
        _error_cursor_sse()
    cursor = int(valor)
    if cursor > marca:
        _error_cursor_sse()
    return cursor


def _obtener_cursor_solicitado(request: Request) -> tuple[str | None, bool]:
    cabeceras = request.headers.getlist("last-event-id")
    if len(cabeceras) > 1:
        _error_cursor_sse()
    if cabeceras:
        return cabeceras[0], True

    cursores_iniciales = request.query_params.getlist("cursor_eventos")
    if len(cursores_iniciales) > 1:
        _error_cursor_sse()
    if cursores_iniciales:
        return cursores_iniciales[0], True
    return None, False


def _preparar_contexto_stream_tiempo_real(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db, scope="function")],
) -> ContextoStreamTiempoReal:
    """Valida la sesion/rol y reserva la lease antes de enviar headers SSE."""

    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        db.rollback()
        _error_sesion_no_autenticada()

    try:
        usuario = obtener_usuario_por_token(db, token=token)
    except SQLAlchemyError:
        db.rollback()
        _error_sesion_no_autenticada()
    usuario_id = usuario.id if usuario is not None else None
    rol_usuario = usuario.rol if usuario is not None else None
    db.rollback()
    if usuario_id is None or rol_usuario not in {"ADMIN", "OPERADOR"}:
        _error_sesion_no_autenticada()

    valor_cursor, cursor_explicito = _obtener_cursor_solicitado(request)
    try:
        tipos_autorizados = tipos_autorizados_para_rol(rol_usuario)
        marca, primer_evento = obtener_marca_eventos(db, tipos_autorizados)
        db.rollback()
        cursor = _interpretar_cursor_sse(valor_cursor, marca)
        requiere_resync = (
            cursor_explicito
            and bool(tipos_autorizados)
            and cursor_necesita_resync(cursor, marca, primer_evento)
        )
        lease_id = admitir_conexion_sse(
            db,
            usuario_id=usuario_id,
            token_sesion=token,
        )
    except SesionTiempoRealNoValidaError:
        db.rollback()
        _error_sesion_no_autenticada()
    except LimiteConexionesSSEError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Se alcanzo el limite de conexiones en tiempo real.",
            headers={
                "Cache-Control": "no-store",
                "Retry-After": str(error.reintentar_en),
            },
        ) from None
    except RuntimeError, SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno",
            headers={"Cache-Control": "no-store"},
        ) from None

    response.headers.update(CABECERAS_SSE)
    contexto = ContextoStreamTiempoReal(
        usuario_id=usuario_id,
        rol_usuario=rol_usuario,
        token_sesion=token,
        lease_id=lease_id,
        cursor=cursor,
        marca_inicial=marca,
        requiere_resync=requiere_resync,
    )
    contexto.iterador_eventos = _generar_eventos_tiempo_real(contexto)
    _registrar_contexto_stream_sse(contexto)
    request.scope[CLAVE_CONTEXTO_STREAM_SSE] = contexto
    return contexto


def _consultar_lote_en_sesion(
    *,
    contexto: ContextoStreamTiempoReal,
    cursor: int,
    revalidar_sesion: bool,
    renovar_conexion: bool,
) -> ResultadoLoteEventosSSE:
    with SessionLocal() as db:
        return consultar_lote_eventos_usuario(
            db,
            usuario_id=contexto.usuario_id,
            rol_usuario=contexto.rol_usuario,
            token_sesion=contexto.token_sesion,
            lease_id=contexto.lease_id,
            cursor=cursor,
            revalidar_sesion=revalidar_sesion,
            renovar_conexion=renovar_conexion,
        )


def _cerrar_lease_en_sesion(contexto: ContextoStreamTiempoReal) -> None:
    with SessionLocal() as db:
        cerrar_conexion_sse(
            db,
            usuario_id=contexto.usuario_id,
            lease_id=contexto.lease_id,
        )


async def _generar_eventos_tiempo_real(
    contexto: ContextoStreamTiempoReal,
) -> AsyncGenerator[ServerSentEvent]:
    """Emite solo eventos autorizados y cierra la concesion al desconectar."""

    reloj = asyncio.get_running_loop()
    ahora = reloj.time()
    ultima_revalidacion = ahora - INTERVALO_REVALIDACION_SSE
    ultima_renovacion = ahora - INTERVALO_REVALIDACION_SSE
    ultimo_heartbeat = ahora
    cursor_escaneado = contexto.cursor

    try:
        if contexto.requiere_resync:
            cursor_escaneado = contexto.marca_inicial
            yield ServerSentEvent(
                id=str(cursor_escaneado),
                event="resync",
                data={"motivo": "historial_expirado"},
            )

        while True:
            ahora = reloj.time()
            debe_revalidar = ahora - ultima_revalidacion >= INTERVALO_REVALIDACION_SSE
            debe_renovar = ahora - ultima_renovacion >= INTERVALO_REVALIDACION_SSE
            try:
                lote = await asyncio.to_thread(
                    _consultar_lote_en_sesion,
                    contexto=contexto,
                    cursor=cursor_escaneado,
                    revalidar_sesion=debe_revalidar,
                    renovar_conexion=debe_renovar,
                )
            except RuntimeError, SQLAlchemyError:
                return

            ahora = reloj.time()
            if debe_revalidar:
                ultima_revalidacion = ahora
            if debe_renovar:
                ultima_renovacion = ahora
            if not lote.autorizado:
                return

            if lote.requiere_resync:
                cursor_escaneado = lote.marca
                yield ServerSentEvent(
                    id=str(cursor_escaneado),
                    event="resync",
                    data={"motivo": "historial_expirado"},
                )
            else:
                for evento in lote.eventos:
                    cursor_escaneado = evento.id
                    yield ServerSentEvent(
                        id=str(evento.id),
                        event=evento.tipo,
                        data={
                            "recurso_tipo": evento.recurso_tipo,
                            "recurso_id": evento.recurso_id,
                            "ocurrido_en": evento.ocurrido_en,
                        },
                    )
                cursor_escaneado = max(cursor_escaneado, lote.cursor_escaneado)

            ahora = reloj.time()
            if ahora - ultimo_heartbeat >= INTERVALO_HEARTBEAT_SSE:
                ultimo_heartbeat = ahora
                yield ServerSentEvent(comment="keepalive")

            await asyncio.sleep(0 if len(lote.eventos) == 100 else INTERVALO_POLL_SSE)
    finally:
        await _cerrar_lease_sse(contexto)


@router.get(RUTA_EVENTOS_TIEMPO_REAL, response_class=EventSourceResponse)
@router.get(
    RUTA_EVENTOS_OPERADORES_COMPATIBILIDAD,
    response_class=EventSourceResponse,
    include_in_schema=False,
)
async def eventos_tiempo_real_endpoint(
    contexto: Annotated[
        ContextoStreamTiempoReal,
        Depends(_preparar_contexto_stream_tiempo_real, scope="function"),
    ],
) -> AsyncIterator[ServerSentEvent]:
    """Inicia el stream comun para sesiones ADMIN y OPERADOR."""

    if contexto.iterador_eventos is None:
        return
    async for evento in contexto.iterador_eventos:
        yield evento


__all__ = [
    "ContextoStreamTiempoReal",
    "RUTA_EVENTOS_OPERADORES_COMPATIBILIDAD",
    "RUTA_EVENTOS_TIEMPO_REAL",
    "_generar_eventos_tiempo_real",
    "_preparar_contexto_stream_tiempo_real",
    "eventos_tiempo_real_endpoint",
    "router",
]
