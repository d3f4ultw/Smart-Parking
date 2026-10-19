"""Conserva un solo frame reciente por tipo, sin colas ni persistencia."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

TipoFrameVision = Literal["annotated", "raw"]
MAXIMO_BYTES_FRAME_VISION = 1_048_576
MAXIMO_VISUALIZADORES_VISION = 4
MAXIMA_DIMENSION_FRAME_VISION = 1920
MAXIMO_PIXELES_FRAME_VISION = MAXIMA_DIMENSION_FRAME_VISION * 1080
MAXIMO_LIBERACIONES_RECIENTES = 32
logger = logging.getLogger(__name__)


def dimensiones_jpeg(datos: bytes) -> tuple[int, int] | None:
    """Lee ancho y alto JPEG sin cargar un segundo decodificador de imagen."""

    if len(datos) < 4 or datos[:2] != b"\xff\xd8" or datos[-2:] != b"\xff\xd9":
        return None

    marcadores_sof = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    posicion = 2
    while posicion + 4 <= len(datos) - 2:
        if datos[posicion] != 0xFF:
            return None
        while posicion < len(datos) and datos[posicion] == 0xFF:
            posicion += 1
        if posicion >= len(datos):
            return None
        marcador = datos[posicion]
        posicion += 1
        if marcador in {0xD8, 0xD9, 0x01} or 0xD0 <= marcador <= 0xD7:
            continue
        if posicion + 2 > len(datos):
            return None
        largo = int.from_bytes(datos[posicion : posicion + 2], "big")
        if largo < 2 or posicion + largo > len(datos):
            return None
        if marcador in marcadores_sof:
            if largo < 7:
                return None
            alto = int.from_bytes(datos[posicion + 3 : posicion + 5], "big")
            ancho = int.from_bytes(datos[posicion + 5 : posicion + 7], "big")
            return (ancho, alto) if ancho > 0 and alto > 0 else None
        if marcador == 0xDA:
            return None
        posicion += largo
    return None


@dataclass(frozen=True, slots=True)
class FrameVision:
    session_id: UUID
    revision: int
    sequence: int
    jpeg: bytes
    recibido_monotono: float
    recibido_en: datetime


@dataclass(frozen=True, slots=True)
class EstadoRuntimeVision:
    session_id: UUID | None
    revision: int
    sequence: int
    mode: str
    source_connected: bool
    processing: bool
    error_code: str | None
    actualizado_monotono: float | None
    source_fps: float
    inference_fps: float
    zone_states: tuple[tuple[int, str], ...]


@dataclass(frozen=True, slots=True)
class DetalleVisualizadorVision:
    diagnostic_id: str
    stream_type: TipoFrameVision
    reserved_at: datetime
    connection_age_seconds: float
    last_emitted_sequence: int | None
    last_emitted_at: datetime | None
    jpeg_parts_emitted: int
    jpeg_bytes_emitted: int
    released_at: datetime | None
    release_reason: str | None


class ReservaVisualizador:
    """Representa un cupo que puede liberarse de forma idempotente."""

    def __init__(self, hub: VisionFrameHub, tipo: TipoFrameVision) -> None:
        self._hub = hub
        self.diagnostic_id = uuid4().hex
        self.stream_type: TipoFrameVision = tipo
        self.reserved_at = datetime.now(UTC)
        self.reserved_monotonic = time.monotonic()
        self.last_emitted_sequence: int | None = None
        self.last_emitted_at: datetime | None = None
        self.jpeg_parts_emitted = 0
        self.jpeg_bytes_emitted = 0
        self.released_at: datetime | None = None
        self.release_reason: str | None = None

    async def registrar_parte(self, sequence: int, jpeg_bytes: int) -> None:
        await self._hub.registrar_parte_visualizador(self, sequence, jpeg_bytes)

    async def liberar(self, motivo: str = "response_complete") -> None:
        await self._hub.liberar_visualizador(self, motivo)


class VisionFrameHub:
    """Entrega solo el valor mas reciente a cada consumidor de frames."""

    def __init__(
        self,
        *,
        maximo_bytes: int = MAXIMO_BYTES_FRAME_VISION,
        maximos_visualizadores: int = MAXIMO_VISUALIZADORES_VISION,
    ) -> None:
        self.maximo_bytes = maximo_bytes
        self.maximos_visualizadores = maximos_visualizadores
        self._condicion = asyncio.Condition()
        self._candado_visualizadores = asyncio.Lock()
        self._sesion_actual: UUID | None = None
        self._revision_actual: int | None = None
        self._frames: dict[TipoFrameVision, FrameVision] = {}
        self._estado: EstadoRuntimeVision | None = None
        self._visualizadores = 0
        self._reservas_visualizadores: set[ReservaVisualizador] = set()
        self._liberaciones_recientes: deque[DetalleVisualizadorVision] = deque(
            maxlen=MAXIMO_LIBERACIONES_RECIENTES
        )
        self._cerrado = False

    async def nueva_sesion(self, session_id: UUID, revision: int = 0) -> None:
        """Invalida frames anteriores cuando Vision recibe una nueva sesion."""

        async with self._condicion:
            self._sesion_actual = session_id
            self._revision_actual = revision
            self._frames.clear()
            self._estado = None
            self._condicion.notify_all()

    async def actualizar_revision(self, revision: int) -> bool:
        """Cambia la revisión vigente sin cerrar captura ni lectores MJPEG."""

        async with self._condicion:
            if self._revision_actual is None or revision < self._revision_actual:
                return False
            if revision == self._revision_actual:
                return True
            self._revision_actual = revision
            self._frames.pop("annotated", None)
            self._condicion.notify_all()
            return True

    async def publicar_frame(
        self,
        tipo: TipoFrameVision,
        *,
        session_id: UUID,
        revision: int = 0,
        sequence: int,
        jpeg: bytes,
        recibido_en: datetime,
    ) -> bool:
        """Reemplaza el frame de ese tipo y descarta secuencias repetidas."""

        if len(jpeg) > self.maximo_bytes:
            return False
        async with self._condicion:
            if (
                self._sesion_actual != session_id
                or self._revision_actual != revision
            ):
                return False
            anterior = self._frames.get(tipo)
            if anterior is not None and sequence <= anterior.sequence:
                return False
            self._frames[tipo] = FrameVision(
                session_id=session_id,
                revision=revision,
                sequence=sequence,
                jpeg=jpeg,
                recibido_monotono=time.monotonic(),
                recibido_en=recibido_en,
            )
            self._condicion.notify_all()
            return True

    async def publicar_estado(
        self,
        *,
        session_id: UUID,
        revision: int = 0,
        sequence: int,
        mode: str,
        source_connected: bool,
        processing: bool,
        error_code: str | None,
        source_fps: float = 0.0,
        inference_fps: float = 0.0,
        zone_states: tuple[tuple[int, str], ...] = (),
    ) -> bool:
        """Actualiza un estado sanitizado solo para la sesion Vision vigente."""

        async with self._condicion:
            if (
                self._sesion_actual != session_id
                or self._revision_actual != revision
            ):
                return False
            anterior = self._estado
            if anterior is not None and sequence <= anterior.sequence:
                return False
            self._estado = EstadoRuntimeVision(
                session_id=session_id,
                revision=revision,
                sequence=sequence,
                mode=mode,
                source_connected=source_connected,
                processing=processing,
                error_code=error_code,
                actualizado_monotono=time.monotonic(),
                source_fps=source_fps,
                inference_fps=inference_fps,
                zone_states=zone_states,
            )
            self._condicion.notify_all()
            return True

    async def obtener_frame(self, tipo: TipoFrameVision) -> FrameVision | None:
        async with self._condicion:
            return self._frames.get(tipo)

    async def esperar_siguiente_frame(
        self,
        tipo: TipoFrameVision,
        *,
        session_id: UUID,
        secuencia_anterior: int,
        timeout: float,
    ) -> FrameVision | None:
        """Espera una secuencia nueva; el consumidor lento omite frames."""

        try:
            async with asyncio.timeout(timeout):
                async with self._condicion:
                    await self._condicion.wait_for(
                        lambda: (
                            self._cerrado
                            or self._sesion_actual != session_id
                            or (
                                (frame := self._frames.get(tipo)) is not None
                                and frame.sequence > secuencia_anterior
                            )
                        )
                    )
                    if self._sesion_actual != session_id or self._cerrado:
                        return None
                    return self._frames.get(tipo)
        except TimeoutError:
            return None

    async def obtener_estado(self) -> EstadoRuntimeVision | None:
        async with self._condicion:
            return self._estado

    async def esta_cerrado(self) -> bool:
        async with self._condicion:
            return self._cerrado

    async def reservar_visualizador(
        self,
        tipo: TipoFrameVision = "annotated",
    ) -> ReservaVisualizador | None:
        async with self._candado_visualizadores:
            if self._cerrado or self._visualizadores >= self.maximos_visualizadores:
                return None
            self._visualizadores += 1
            reserva = ReservaVisualizador(self, tipo)
            self._reservas_visualizadores.add(reserva)
            logger.info(
                "vision_mjpeg_viewer_reserved id=%s type=%s reserved_at=%s active=%s",
                reserva.diagnostic_id,
                reserva.stream_type,
                reserva.reserved_at.isoformat(),
                self._visualizadores,
            )
            return reserva

    async def registrar_parte_visualizador(
        self,
        reserva: ReservaVisualizador,
        sequence: int,
        jpeg_bytes: int,
    ) -> None:
        async with self._candado_visualizadores:
            if reserva not in self._reservas_visualizadores:
                return
            reserva.last_emitted_sequence = sequence
            reserva.last_emitted_at = datetime.now(UTC)
            reserva.jpeg_parts_emitted += 1
            reserva.jpeg_bytes_emitted += jpeg_bytes

    @staticmethod
    def _detalle_reserva(
        reserva: ReservaVisualizador,
        *,
        edad: float,
    ) -> DetalleVisualizadorVision:
        return DetalleVisualizadorVision(
            diagnostic_id=reserva.diagnostic_id,
            stream_type=reserva.stream_type,
            reserved_at=reserva.reserved_at,
            connection_age_seconds=round(max(0.0, edad), 3),
            last_emitted_sequence=reserva.last_emitted_sequence,
            last_emitted_at=reserva.last_emitted_at,
            jpeg_parts_emitted=reserva.jpeg_parts_emitted,
            jpeg_bytes_emitted=reserva.jpeg_bytes_emitted,
            released_at=reserva.released_at,
            release_reason=reserva.release_reason,
        )

    async def obtener_detalle_visualizadores(
        self,
    ) -> tuple[list[DetalleVisualizadorVision], list[DetalleVisualizadorVision]]:
        ahora_monotono = time.monotonic()
        async with self._candado_visualizadores:
            activos = [
                self._detalle_reserva(
                    reserva,
                    edad=ahora_monotono - reserva.reserved_monotonic,
                )
                for reserva in self._reservas_visualizadores
            ]
            activos.sort(key=lambda detalle: detalle.reserved_at)
            liberados = list(self._liberaciones_recientes)
            return activos, liberados

    async def liberar_visualizador(
        self,
        reserva: ReservaVisualizador,
        motivo: str = "response_complete",
    ) -> None:
        async with self._candado_visualizadores:
            if reserva in self._reservas_visualizadores:
                self._reservas_visualizadores.remove(reserva)
                self._visualizadores -= 1
                reserva.released_at = datetime.now(UTC)
                reserva.release_reason = motivo[:64]
                detalle = self._detalle_reserva(
                    reserva,
                    edad=time.monotonic() - reserva.reserved_monotonic,
                )
                self._liberaciones_recientes.appendleft(detalle)
                logger.info(
                    "vision_mjpeg_viewer_released id=%s type=%s age_seconds=%.3f "
                    "last_sequence=%s parts=%s jpeg_bytes=%s reason=%s active=%s",
                    reserva.diagnostic_id,
                    reserva.stream_type,
                    detalle.connection_age_seconds,
                    reserva.last_emitted_sequence,
                    reserva.jpeg_parts_emitted,
                    reserva.jpeg_bytes_emitted,
                    reserva.release_reason,
                    self._visualizadores,
                )

    async def obtener_cantidad_visualizadores(self) -> int:
        async with self._candado_visualizadores:
            return self._visualizadores

    async def cerrar(self) -> None:
        async with self._condicion:
            self._cerrado = True
            self._frames.clear()
            self._estado = None
            self._condicion.notify_all()
        async with self._candado_visualizadores:
            reservas = list(self._reservas_visualizadores)
        for reserva in reservas:
            await reserva.liberar("hub_shutdown")


__all__ = [
    "MAXIMA_DIMENSION_FRAME_VISION",
    "MAXIMO_BYTES_FRAME_VISION",
    "MAXIMO_VISUALIZADORES_VISION",
    "DetalleVisualizadorVision",
    "EstadoRuntimeVision",
    "FrameVision",
    "ReservaVisualizador",
    "TipoFrameVision",
    "VisionFrameHub",
    "dimensiones_jpeg",
]
