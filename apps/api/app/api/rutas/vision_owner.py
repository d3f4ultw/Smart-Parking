"""Façade OWNER para la monitorizacion y calibracion de Vision."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, NoReturn
from urllib.parse import urlsplit
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect
from starlette.types import Receive, Scope, Send

from app.api.dependencias import (
    CABECERA_NO_CACHE,
    exigir_owner,
    exigir_vision,
    exigir_vision_owner_autorizado,
)
from app.core.config import Settings, get_settings
from app.core.database import SessionLocal, get_db
from app.esquemas.vision import (
    EstadoVisualizadorMonitoreoVision,
    EstadoZonaRuntimeVision,
    RespuestaAutorizacionVision,
    RespuestaConfiguracionVision,
    RespuestaEstadoLeaseCalibracionVision,
    RespuestaEstadoMonitoreoVision,
    RespuestaLeaseCalibracionVision,
    RespuestaLiberacionLeaseCalibracionVision,
    SolicitudAutorizacionVision,
    SolicitudConfiguracionVision,
    SolicitudEstadoRuntimeVision,
    SolicitudLeaseCalibracionVision,
)
from app.models import VisionConfiguration
from app.seguridad.limitador import LimitadorAutenticacion
from app.seguridad.sesiones import hash_token_sesion
from app.servicios.autorizacion_vision import (
    VisionAutorizacionInvalidaError,
    autorizar_sesion_vision,
    obtener_estado_autorizacion_vision,
    sesion_tiene_autorizacion_vision,
)
from app.servicios.autorizacion_vision import (
    revocar_autorizacion_vision as revocar_autorizacion_vision_sesion,
)
from app.servicios.vision import (
    VisionConfiguracionError,
    VisionConflictoError,
    cargar_configuracion_vision,
    guardar_configuracion_vision,
)
from app.servicios.vision_calibration_lease import (
    DURACION_LEASE_SEGUNDOS,
    VisionCalibracionLeaseError,
    adquirir_lease,
    consultar_disponibilidad,
    liberar_lease,
    liberar_lease_de_sesion,
    renovar_lease,
)
from app.servicios.vision_frames import (
    MAXIMA_DIMENSION_FRAME_VISION,
    MAXIMO_BYTES_FRAME_VISION,
    MAXIMO_PIXELES_FRAME_VISION,
    FrameVision,
    ReservaVisualizador,
    TipoFrameVision,
    VisionFrameHub,
    dimensiones_jpeg,
)

RUTA_ADMIN_VISION = "/api/admin/vision"
RUTA_VISION_FRAMES = "/api/vision"
MAXIMA_EDAD_FRAME_SEGUNDOS = 3.0
MAXIMA_ANTIGUEDAD_ESTADO_SEGUNDOS = 5.0
CABECERAS_PRIVADAS = {
    **CABECERA_NO_CACHE,
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "X-Accel-Buffering": "no",
}
limitador_autorizacion_vision = LimitadorAutenticacion(
    limite_origen=30,
    limite_correo=5,
)


class RespuestaStreamMjpegVision(StreamingResponse):
    """Libera la reserva aun si la respuesta falla antes de cerrar el cuerpo."""

    def __init__(
        self,
        content: AsyncIterator[bytes],
        *,
        reserva: ReservaVisualizador,
        media_type: str,
        headers: dict[str, str],
    ) -> None:
        self._reserva = reserva
        super().__init__(content=content, media_type=media_type, headers=headers)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        motivo = "response_complete"
        try:
            await super().__call__(scope, receive, send)
        except ClientDisconnect:
            motivo = "downstream_disconnect"
            raise
        except asyncio.CancelledError:
            motivo = "response_cancelled"
            raise
        except BaseException:
            motivo = "response_exception"
            raise
        finally:
            with anyio.CancelScope(shield=True):
                await self._reserva.liberar(motivo)

router = APIRouter(prefix=RUTA_ADMIN_VISION, tags=["admin-vision"])
router_vision = APIRouter(
    prefix=RUTA_VISION_FRAMES,
    tags=["vision-frames"],
    dependencies=[Depends(exigir_vision)],
)


def _denegar(codigo: int, detalle: str) -> NoReturn:
    raise HTTPException(
        status_code=codigo,
        detail=detalle,
        headers=CABECERAS_PRIVADAS,
    )


def _exigir_mismo_origen(request: Request, settings: Settings) -> None:
    origen = request.headers.get("origin")
    esperado = settings.app_public_url.rstrip("/")
    try:
        url = urlsplit(esperado)
        esperado = f"{url.scheme}://{url.netloc}"
    except ValueError:
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")
    if origen != esperado:
        _denegar(status.HTTP_403_FORBIDDEN, "Origen no permitido")


def _obtener_token_sesion(request: Request) -> str:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        _denegar(status.HTTP_401_UNAUTHORIZED, "No autenticado")
    return token


def _obtener_hub(request: Request) -> VisionFrameHub:
    hub = getattr(request.app.state, "vision_frame_hub", None)
    if not isinstance(hub, VisionFrameHub):
        _denegar(status.HTTP_503_SERVICE_UNAVAILABLE, "Vision no disponible")
    return hub


def _validar_sesion_vision_actual(
    db: Session,
    session_id: UUID,
    revision: int,
) -> None:
    configuracion = db.get(VisionConfiguration, 1)
    if configuracion is None or configuracion.current_session_id != session_id:
        _denegar(status.HTTP_409_CONFLICT, "La sesion Vision ya no es vigente")
    if configuracion.revision != revision:
        _denegar(status.HTTP_409_CONFLICT, "La revision de Vision ya no es vigente")


def _validar_jpeg(datos: bytes, *, tipo: TipoFrameVision) -> None:
    dimensiones = dimensiones_jpeg(datos)
    if dimensiones is None:
        _denegar(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "JPEG invalido")
    ancho, alto = dimensiones
    dimension_maxima = 960 if tipo == "annotated" else MAXIMA_DIMENSION_FRAME_VISION
    if (
        ancho > dimension_maxima
        or alto > dimension_maxima
        or ancho * alto > MAXIMO_PIXELES_FRAME_VISION
    ):
        _denegar(status.HTTP_413_CONTENT_TOO_LARGE, "Frame fuera de limite")


async def _leer_frame_limitado(request: Request, *, tipo: TipoFrameVision) -> bytes:
    tipo_contenido = request.headers.get("content-type", "").lower()
    if tipo_contenido != "image/jpeg":
        _denegar(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Solo se aceptan frames JPEG")
    raw_length = request.headers.get("content-length")
    if raw_length is None or not raw_length.isascii() or not raw_length.isdecimal():
        _denegar(status.HTTP_411_LENGTH_REQUIRED, "Content-Length requerido")
    largo = int(raw_length)
    if largo < 4 or largo > MAXIMO_BYTES_FRAME_VISION:
        _denegar(status.HTTP_413_CONTENT_TOO_LARGE, "Frame fuera de limite")

    datos = bytearray()
    async for bloque in request.stream():
        datos.extend(bloque)
        if len(datos) > MAXIMO_BYTES_FRAME_VISION or len(datos) > largo:
            _denegar(status.HTTP_413_CONTENT_TOO_LARGE, "Frame fuera de limite")
    if len(datos) != largo:
        _denegar(status.HTTP_400_BAD_REQUEST, "Frame incompleto")
    resultado = bytes(datos)
    _validar_jpeg(resultado, tipo=tipo)
    return resultado


def _escribir_headers_privados(response: Response) -> None:
    response.headers.update(CABECERAS_PRIVADAS)


@router.get(
    "/authorization",
    response_model=RespuestaAutorizacionVision,
    dependencies=[Depends(exigir_owner)],
)
def consultar_autorizacion_vision(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    usuario_id: Annotated[int, Depends(exigir_owner)],
) -> RespuestaAutorizacionVision:
    _escribir_headers_privados(response)
    try:
        estado = obtener_estado_autorizacion_vision(
            db,
            usuario_id=usuario_id,
            token_sesion=_obtener_token_sesion(request),
        )
        return RespuestaAutorizacionVision(
            authorized=estado.authorized,
        )
    except SQLAlchemyError:
        db.rollback()
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")


@router.post(
    "/authorization",
    response_model=RespuestaAutorizacionVision,
    dependencies=[Depends(exigir_owner)],
)
def verificar_autorizacion_vision(
    solicitud: SolicitudAutorizacionVision,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    usuario_id: Annotated[int, Depends(exigir_owner)],
) -> RespuestaAutorizacionVision:
    _escribir_headers_privados(response)
    _exigir_mismo_origen(request, get_settings())
    token = _obtener_token_sesion(request)
    origen = request.client.host if request.client is not None else "desconocido"
    if not limitador_autorizacion_vision.permitir(
        origen,
        hash_token_sesion(token),
    ):
        _denegar(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos")
    try:
        autorizar_sesion_vision(
            db,
            usuario_id=usuario_id,
            token_sesion=token,
            contrasena_admin=solicitud.contrasena_admin,
        )
    except VisionAutorizacionInvalidaError:
        _denegar(
            status.HTTP_401_UNAUTHORIZED,
            "Credenciales administrativas invalidas",
        )
    except SQLAlchemyError:
        db.rollback()
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")
    return RespuestaAutorizacionVision(authorized=True)


@router.delete(
    "/authorization",
    response_model=RespuestaAutorizacionVision,
    dependencies=[Depends(exigir_owner)],
)
def revocar_autorizacion_vision(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    usuario_id: Annotated[int, Depends(exigir_owner)],
) -> RespuestaAutorizacionVision:
    _escribir_headers_privados(response)
    _exigir_mismo_origen(request, get_settings())
    token = _obtener_token_sesion(request)
    try:
        revocar_autorizacion_vision_sesion(
            db,
            usuario_id=usuario_id,
            token_sesion=token,
        )
        liberar_lease_de_sesion(
            db,
            token_sesion_hash=hash_token_sesion(token),
        )
    except SQLAlchemyError:
        db.rollback()
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")
    return RespuestaAutorizacionVision(authorized=False)


@router.get(
    "/calibration-lease",
    response_model=RespuestaEstadoLeaseCalibracionVision,
    dependencies=[Depends(exigir_vision_owner_autorizado)],
)
def consultar_lease_calibracion_vision(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaEstadoLeaseCalibracionVision:
    _escribir_headers_privados(response)
    try:
        return RespuestaEstadoLeaseCalibracionVision(
            available=consultar_disponibilidad(db),
            lease_duration_seconds=DURACION_LEASE_SEGUNDOS,
        )
    except SQLAlchemyError:
        db.rollback()
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")


@router.post(
    "/calibration-lease/acquire",
    response_model=RespuestaLeaseCalibracionVision,
    dependencies=[Depends(exigir_vision_owner_autorizado)],
)
def adquirir_lease_calibracion_vision(
    solicitud: SolicitudLeaseCalibracionVision,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaLeaseCalibracionVision:
    _escribir_headers_privados(response)
    _exigir_mismo_origen(request, get_settings())
    try:
        adquirir_lease(
            db,
            token_sesion_hash=hash_token_sesion(_obtener_token_sesion(request)),
            editor_instance_id=solicitud.editor_instance_id,
        )
    except VisionCalibracionLeaseError as error:
        _denegar(status.HTTP_409_CONFLICT, str(error))
    except SQLAlchemyError:
        db.rollback()
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")
    return RespuestaLeaseCalibracionVision(
        lease_duration_seconds=DURACION_LEASE_SEGUNDOS,
    )


@router.post(
    "/calibration-lease/renew",
    response_model=RespuestaLeaseCalibracionVision,
    dependencies=[Depends(exigir_vision_owner_autorizado)],
)
def renovar_lease_calibracion_vision(
    solicitud: SolicitudLeaseCalibracionVision,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaLeaseCalibracionVision:
    _escribir_headers_privados(response)
    _exigir_mismo_origen(request, get_settings())
    try:
        renovar_lease(
            db,
            token_sesion_hash=hash_token_sesion(_obtener_token_sesion(request)),
            editor_instance_id=solicitud.editor_instance_id,
        )
    except VisionCalibracionLeaseError as error:
        _denegar(status.HTTP_409_CONFLICT, str(error))
    except SQLAlchemyError:
        db.rollback()
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")
    return RespuestaLeaseCalibracionVision(
        lease_duration_seconds=DURACION_LEASE_SEGUNDOS,
    )


@router.post(
    "/calibration-lease/release",
    response_model=RespuestaLiberacionLeaseCalibracionVision,
    dependencies=[Depends(exigir_owner)],
)
def liberar_lease_calibracion_vision(
    solicitud: SolicitudLeaseCalibracionVision,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaLiberacionLeaseCalibracionVision:
    _escribir_headers_privados(response)
    _exigir_mismo_origen(request, get_settings())
    try:
        liberado = liberar_lease(
            db,
            token_sesion_hash=hash_token_sesion(_obtener_token_sesion(request)),
            editor_instance_id=solicitud.editor_instance_id,
        )
    except SQLAlchemyError:
        db.rollback()
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")
    return RespuestaLiberacionLeaseCalibracionVision(released=liberado)


@router.get(
    "/configuration",
    response_model=RespuestaConfiguracionVision,
    dependencies=[Depends(exigir_vision_owner_autorizado)],
)
def obtener_configuracion_vision_owner(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaConfiguracionVision:
    _escribir_headers_privados(response)
    try:
        return RespuestaConfiguracionVision.model_validate(
            cargar_configuracion_vision(db)
        )
    except SQLAlchemyError:
        db.rollback()
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")


@router.put(
    "/configuration",
    response_model=RespuestaConfiguracionVision,
    dependencies=[Depends(exigir_vision_owner_autorizado)],
)
def guardar_configuracion_vision_owner(
    solicitud: SolicitudConfiguracionVision,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    editor_instance_id: Annotated[
        UUID | None,
        Header(alias="X-Vision-Editor-Instance"),
    ] = None,
) -> RespuestaConfiguracionVision:
    _escribir_headers_privados(response)
    _exigir_mismo_origen(request, get_settings())
    if editor_instance_id is None:
        _denegar(
            status.HTTP_409_CONFLICT,
            "Se requiere el lease activo del editor de calibración.",
        )
    try:
        resultado = guardar_configuracion_vision(
            db,
            solicitud,
            token_sesion_hash=hash_token_sesion(_obtener_token_sesion(request)),
            editor_instance_id=editor_instance_id,
        )
    except VisionCalibracionLeaseError as error:
        _denegar(status.HTTP_409_CONFLICT, str(error))
    except VisionConflictoError as error:
        _denegar(status.HTTP_409_CONFLICT, str(error))
    except VisionConfiguracionError as error:
        _denegar(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    except SQLAlchemyError:
        db.rollback()
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")
    anyio.from_thread.run(
        _obtener_hub(request).actualizar_revision,
        resultado["revision"],
    )
    return RespuestaConfiguracionVision.model_validate(resultado)


@router.get(
    "/monitor/status",
    response_model=RespuestaEstadoMonitoreoVision,
    dependencies=[Depends(exigir_vision_owner_autorizado)],
)
async def obtener_estado_monitoreo_vision(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RespuestaEstadoMonitoreoVision:
    _escribir_headers_privados(response)
    try:
        configuracion = cargar_configuracion_vision(db)
        zonas_count = len(configuracion["zones"])
        hub = _obtener_hub(request)
        frame = await hub.obtener_frame("raw")
        frame_anotado = await hub.obtener_frame("annotated")
        estado = await _obtener_hub(request).obtener_estado()
    except SQLAlchemyError:
        db.rollback()
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")

    ahora = time.monotonic()
    edad_frame = (
        max(0.0, ahora - frame.recibido_monotono) if frame is not None else None
    )
    edad_frame_anotado = (
        max(0.0, ahora - frame_anotado.recibido_monotono)
        if frame_anotado is not None
        else None
    )
    edad_estado = (
        max(0.0, ahora - estado.actualizado_monotono)
        if estado is not None and estado.actualizado_monotono is not None
        else None
    )
    estado_reciente = (
        edad_estado is not None and edad_estado <= MAXIMA_ANTIGUEDAD_ESTADO_SEGUNDOS
    )
    frame_fresco = edad_frame is not None and edad_frame <= MAXIMA_EDAD_FRAME_SEGUNDOS
    frame_anotado_fresco = bool(
        frame_anotado is not None
        and edad_frame_anotado is not None
        and edad_frame_anotado <= MAXIMA_EDAD_FRAME_SEGUNDOS
        and frame_anotado.revision == configuracion["revision"]
    )
    conectado = bool(estado and estado.source_connected and estado_reciente)
    procesando = bool(estado and estado.processing and estado_reciente)
    codigo_error = estado.error_code if estado_reciente and estado else None
    if conectado and not frame_fresco and codigo_error is None:
        codigo_error = "SOURCE_UNAVAILABLE"
    visualizadores_activos, liberaciones_recientes = (
        await hub.obtener_detalle_visualizadores()
    )
    return RespuestaEstadoMonitoreoVision(
        mode=estado.mode if estado is not None else get_settings().vision_source_mode,
        source_connected=conectado,
        processing=procesando,
        source_fps=round(estado.source_fps, 2) if estado_reciente and estado else 0.0,
        inference_fps=round(estado.inference_fps, 2)
        if estado_reciente and estado
        else 0.0,
        zone_states=(
            [
                EstadoZonaRuntimeVision(numero=numero, estado=estado_zona)
                for numero, estado_zona in estado.zone_states
            ]
            if estado is not None
            and conectado
            and frame_fresco
            and frame_anotado_fresco
            and estado.revision == configuracion["revision"]
            and procesando
            and estado_reciente
            else []
        ),
        source_sequence=frame.sequence if frame is not None else 0,
        annotated_sequence=(
            frame_anotado.sequence if frame_anotado_fresco and frame_anotado else 0
        ),
        configuration_revision=configuracion["revision"],
        applied_revision=(
            frame_anotado.revision if frame_anotado_fresco and frame_anotado else None
        ),
        active_viewers=len(visualizadores_activos),
        active_viewer_details=[
            EstadoVisualizadorMonitoreoVision(
                diagnostic_id=detalle.diagnostic_id,
                stream_type=detalle.stream_type,
                reserved_at=detalle.reserved_at,
                connection_age_seconds=detalle.connection_age_seconds,
                last_emitted_sequence=detalle.last_emitted_sequence,
                last_emitted_at=detalle.last_emitted_at,
                jpeg_parts_emitted=detalle.jpeg_parts_emitted,
                jpeg_bytes_emitted=detalle.jpeg_bytes_emitted,
                released_at=detalle.released_at,
                release_reason=detalle.release_reason,
            )
            for detalle in visualizadores_activos
        ],
        recent_viewer_releases=[
            EstadoVisualizadorMonitoreoVision(
                diagnostic_id=detalle.diagnostic_id,
                stream_type=detalle.stream_type,
                reserved_at=detalle.reserved_at,
                connection_age_seconds=detalle.connection_age_seconds,
                last_emitted_sequence=detalle.last_emitted_sequence,
                last_emitted_at=detalle.last_emitted_at,
                jpeg_parts_emitted=detalle.jpeg_parts_emitted,
                jpeg_bytes_emitted=detalle.jpeg_bytes_emitted,
                released_at=detalle.released_at,
                release_reason=detalle.release_reason,
            )
            for detalle in liberaciones_recientes
        ],
        frame_fresh=frame_fresco,
        annotated_frame_fresh=frame_anotado_fresco,
        frame_age_seconds=round(edad_frame, 3) if edad_frame is not None else None,
        annotated_frame_age_seconds=(
            round(edad_frame_anotado, 3)
            if edad_frame_anotado is not None
            else None
        ),
        last_frame_at=frame.recibido_en if frame is not None else None,
        last_annotated_frame_at=(
            frame_anotado.recibido_en if frame_anotado is not None else None
        ),
        error_code=codigo_error,
        zones_count=zonas_count,
    )


@router.get(
    "/monitor/snapshot",
    dependencies=[Depends(exigir_vision_owner_autorizado)],
)
async def obtener_snapshot_vision(
    request: Request,
    response: Response,
) -> Response:
    """Entrega solo el frame reciente de la captura compartida."""

    _escribir_headers_privados(response)
    frame = await _obtener_hub(request).obtener_frame("raw")
    if (
        frame is None
        or time.monotonic() - frame.recibido_monotono > MAXIMA_EDAD_FRAME_SEGUNDOS
    ):
        _denegar(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No hay un frame reciente de cámara",
        )
    return Response(
        content=frame.jpeg,
        media_type="image/jpeg",
        headers=CABECERAS_PRIVADAS,
    )


def _comprobar_autorizacion_stream(token: str) -> bool:
    try:
        with SessionLocal() as db:
            return sesion_tiene_autorizacion_vision(db, token_sesion=token)
    except SQLAlchemyError:
        return False


async def _partes_mjpeg(
    *,
    hub: VisionFrameHub,
    token_sesion: str,
    session_id: UUID,
    tipo: TipoFrameVision,
    limite: int,
    boundary: str,
    reserva: ReservaVisualizador,
) -> AsyncIterator[bytes]:
    secuencia = 0
    proxima_revision = 0.0
    motivo_liberacion = "stream_complete"
    try:
        while True:
            ahora = time.monotonic()
            if ahora >= proxima_revision:
                autorizado = await asyncio.to_thread(
                    _comprobar_autorizacion_stream,
                    token_sesion,
                )
                if not autorizado:
                    motivo_liberacion = "authorization_revoked"
                    return
                proxima_revision = ahora + 1.0

            frame: FrameVision | None = await hub.esperar_siguiente_frame(
                tipo,
                session_id=session_id,
                secuencia_anterior=secuencia,
                timeout=min(0.25, max(0.01, proxima_revision - time.monotonic())),
            )
            if frame is None:
                estado = await hub.obtener_estado()
                if estado is None or estado.session_id is None:
                    if await hub.esta_cerrado():
                        motivo_liberacion = "hub_shutdown"
                        return
                    continue
                if estado.session_id != session_id:
                    session_id = estado.session_id
                    secuencia = 0
                continue
            if time.monotonic() - frame.recibido_monotono > MAXIMA_EDAD_FRAME_SEGUNDOS:
                secuencia = frame.sequence
                continue
            if len(frame.jpeg) > limite:
                continue
            secuencia = frame.sequence
            parte = (
                (
                    f"--{boundary}\r\n"
                    "Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(frame.jpeg)}\r\n\r\n"
                ).encode("ascii")
                + frame.jpeg
                + b"\r\n"
            )
            await reserva.registrar_parte(frame.sequence, len(frame.jpeg))
            yield parte
    except GeneratorExit:
        motivo_liberacion = "generator_closed"
        raise
    except asyncio.CancelledError:
        motivo_liberacion = "request_cancelled"
        raise
    except BaseException:
        motivo_liberacion = "generator_exception"
        raise
    finally:
        with anyio.CancelScope(shield=True):
            await reserva.liberar(motivo_liberacion)


@router.get(
    "/monitor/stream",
    dependencies=[Depends(exigir_vision_owner_autorizado)],
)
async def transmitir_monitoreo_vision(
    request: Request,
) -> StreamingResponse:
    tipo_solicitado = request.query_params.get("tipo", "annotated")
    if tipo_solicitado not in {"annotated", "raw"}:
        _denegar(status.HTTP_400_BAD_REQUEST, "Tipo de frame no permitido")
    tipo: TipoFrameVision = "annotated" if tipo_solicitado == "annotated" else "raw"
    token = _obtener_token_sesion(request)
    hub = _obtener_hub(request)
    reserva = await hub.reservar_visualizador(tipo)
    if reserva is None:
        _denegar(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Limite de visualizadores alcanzado",
        )

    try:
        estado = await hub.obtener_estado()
        if estado is None or estado.session_id is None:
            _denegar(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Vision no esta transmitiendo",
            )

        boundary = f"vision-{secrets.token_hex(18)}"
        return RespuestaStreamMjpegVision(
            _partes_mjpeg(
                hub=hub,
                token_sesion=token,
                session_id=estado.session_id,
                tipo=tipo,
                limite=MAXIMO_BYTES_FRAME_VISION,
                boundary=boundary,
                reserva=reserva,
            ),
            reserva=reserva,
            media_type=f"multipart/x-mixed-replace; boundary={boundary}",
            headers=CABECERAS_PRIVADAS,
        )
    except BaseException:
        with anyio.CancelScope(shield=True):
            await reserva.liberar("request_setup_failed")
        raise


@router_vision.post("/frames/annotated", status_code=status.HTTP_202_ACCEPTED)
async def recibir_frame_anotado(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    x_vision_session: Annotated[UUID, Header()],
    x_vision_revision: Annotated[int, Header(ge=0)],
    x_vision_sequence: Annotated[int, Header(ge=1)],
) -> dict[str, bool]:
    _escribir_headers_privados(response)
    datos = await _leer_frame_limitado(request, tipo="annotated")
    try:
        _validar_sesion_vision_actual(db, x_vision_session, x_vision_revision)
        hub = _obtener_hub(request)
        aceptado = await hub.publicar_frame(
            "annotated",
            session_id=x_vision_session,
            revision=x_vision_revision,
            sequence=x_vision_sequence,
            jpeg=datos,
            recibido_en=datetime.now(UTC),
        )
    except SQLAlchemyError:
        db.rollback()
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")
    if not aceptado:
        _denegar(status.HTTP_409_CONFLICT, "Secuencia de frame no vigente")
    return {"accepted": True}


@router_vision.post("/frames/raw", status_code=status.HTTP_202_ACCEPTED)
async def recibir_frame_crudo(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    x_vision_session: Annotated[UUID, Header()],
    x_vision_revision: Annotated[int, Header(ge=0)],
    x_vision_sequence: Annotated[int, Header(ge=1)],
) -> dict[str, bool]:
    _escribir_headers_privados(response)
    datos = await _leer_frame_limitado(request, tipo="raw")
    try:
        _validar_sesion_vision_actual(db, x_vision_session, x_vision_revision)
        aceptado = await _obtener_hub(request).publicar_frame(
            "raw",
            session_id=x_vision_session,
            revision=x_vision_revision,
            sequence=x_vision_sequence,
            jpeg=datos,
            recibido_en=datetime.now(UTC),
        )
    except SQLAlchemyError:
        db.rollback()
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")
    if not aceptado:
        _denegar(status.HTTP_409_CONFLICT, "Secuencia de frame no vigente")
    return {"accepted": True}


@router_vision.post("/runtime-status", status_code=status.HTTP_202_ACCEPTED)
async def recibir_estado_runtime_vision(
    solicitud: SolicitudEstadoRuntimeVision,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    _escribir_headers_privados(response)
    try:
        _validar_sesion_vision_actual(
            db,
            solicitud.session_id,
            solicitud.revision,
        )
        aceptado = await _obtener_hub(request).publicar_estado(
            session_id=solicitud.session_id,
            revision=solicitud.revision,
            sequence=solicitud.sequence,
            mode=solicitud.mode,
            source_connected=solicitud.source_connected,
            processing=solicitud.processing,
            error_code=solicitud.error_code,
            source_fps=solicitud.source_fps,
            inference_fps=solicitud.inference_fps,
            zone_states=tuple(
                (zona.numero, zona.estado) for zona in solicitud.zone_states
            ),
        )
    except SQLAlchemyError:
        db.rollback()
        _denegar(status.HTTP_500_INTERNAL_SERVER_ERROR, "Error interno")
    if not aceptado:
        _denegar(status.HTTP_409_CONFLICT, "Estado de runtime no vigente")
    return {"accepted": True}


__all__ = [
    "RUTA_ADMIN_VISION",
    "limitador_autorizacion_vision",
    "router",
    "router_vision",
]
