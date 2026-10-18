"""Runtime único, headless y compartido para capturar, inferir y publicar Vision."""

from __future__ import annotations

import os
import json
import sys
import threading
import time
from urllib.parse import urlsplit
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Literal
from uuid import UUID

import cv2
import numpy as np
import torch

from capture import open_http_source, read_frame
from detect import (
    detections_from_result,
    load_model_from_path,
    predict,
    render_frame,
)
from simulation_playback import build_simulation_sequence, next_frame_index
from smart_parking_client import (
    ConfiguracionRemota,
    SmartParkingClient,
    VisionAPIError,
)
from temporal_validation import (
    FrameQualityGuard,
    OccupancyState,
    ParkingZone,
    TemporalOccupancyValidator,
)

TipoFrame = Literal["raw", "annotated"]
MAXIMA_DIMENSION_ANNOTADA = 960
MAXIMA_DIMENSION_CRUDA = 1280
MAXIMO_BYTES_JPEG = 1_048_576
CALIDAD_JPEG = 75
MAXIMA_ANTIGUEDAD_RUNTIME_SEGUNDOS = 5.0
MAXIMO_TIEMPO_SIN_FRAME_ANOTADO_SEGUNDOS = 5.0
INTERVALO_CONFIGURACION_SEGUNDOS = 1.0


def ajustar_cursor_inferencia(
    session_id: UUID,
    sesion_cursor: UUID | None,
    ultima_secuencia: int,
) -> tuple[UUID, int]:
    """Reinicia el cursor local cuando la API abre una sesion con secuencias nuevas."""

    if session_id != sesion_cursor:
        return session_id, 0
    return session_id, ultima_secuencia


@dataclass(frozen=True, slots=True)
class FramePendiente:
    session_id: UUID
    revision: int
    sequence: int
    frame: np.ndarray
    capturado_monotono: float


@dataclass(frozen=True, slots=True)
class EstadoRuntime:
    source_connected: bool
    processing: bool
    error_code: str | None
    actualizado_monotono: float
    source_fps: float
    inference_fps: float


def _crear_zonas(configuracion: ConfiguracionRemota) -> tuple[ParkingZone, ...]:
    """Convierte la configuración canónica en polígonos para la validación."""

    resultado: list[ParkingZone] = []
    for zona in configuracion.zones:
        resultado.append(
            ParkingZone(
                f"C{zona['numero']}",
                tuple((float(x), float(y)) for x, y in zona["polygon"]),
            )
        )
    return tuple(resultado)


def limitar_dimension(frame: np.ndarray, dimension_maxima: int) -> np.ndarray:
    """Reduce una imagen al límite indicado y conserva su relación de aspecto."""

    alto, ancho = frame.shape[:2]
    mayor = max(ancho, alto)
    if mayor <= dimension_maxima:
        return frame
    escala = dimension_maxima / mayor
    return cv2.resize(
        frame,
        (max(1, round(ancho * escala)), max(1, round(alto * escala))),
        interpolation=cv2.INTER_AREA,
    )


def codificar_jpeg(frame: np.ndarray, calidad: int = CALIDAD_JPEG) -> bytes | None:
    """Codifica una sola vez y descarta resultados fuera del límite de bytes."""

    correcto, contenido = cv2.imencode(
        ".jpg",
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, calidad],
    )
    if not correcto:
        return None
    jpeg = contenido.tobytes()
    if not 4 <= len(jpeg) <= MAXIMO_BYTES_JPEG:
        return None
    return jpeg


class VisionRuntimeBus:
    """Almacena dos imágenes latest-only y la última observación válida."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session_id: UUID | None = None
        self._configuracion: ConfiguracionRemota | None = None
        self._secuencias: dict[TipoFrame, int] = {"raw": 0, "annotated": 0}
        self._frames: dict[TipoFrame, FramePendiente] = {}
        self._observaciones: tuple | None = None
        self._observaciones_version = 0
        self._capturas_monotono: deque[float] = deque(maxlen=31)
        self._nueva_actualizacion = threading.Event()
        self._nuevo_frame_crudo = threading.Event()
        self._estado = EstadoRuntime(
            False,
            False,
            "SOURCE_UNAVAILABLE",
            time.monotonic(),
            0.0,
            0.0,
        )

    def actualizar_contexto(
        self,
        session_id: UUID,
        configuracion: ConfiguracionRemota,
    ) -> None:
        """Frena la publicación anterior al renovar sesión o calibración."""

        with self._lock:
            self._session_id = session_id
            self._configuracion = configuracion
            self._secuencias = {"raw": 0, "annotated": 0}
            self._frames.clear()
            self._observaciones = None
            self._observaciones_version += 1
            self._nueva_actualizacion.set()
            self._nuevo_frame_crudo.set()

    def actualizar_configuracion(self, configuracion: ConfiguracionRemota) -> bool:
        """Aplica geometría nueva sin reiniciar la sesión ni la captura."""

        with self._lock:
            if self._configuracion is None:
                return False
            if configuracion.revision < self._configuracion.revision:
                return False
            if configuracion.revision == self._configuracion.revision:
                return True
            self._configuracion = configuracion
            self._frames.pop("annotated", None)
            self._observaciones = None
            self._observaciones_version += 1
            self._nueva_actualizacion.set()
            self._nuevo_frame_crudo.set()
            return True

    def obtener_contexto(self) -> tuple[UUID | None, ConfiguracionRemota | None]:
        with self._lock:
            return self._session_id, self._configuracion

    def ofrecer_frame(
        self,
        tipo: TipoFrame,
        frame: np.ndarray,
        *,
        session_id: UUID | None = None,
        revision: int | None = None,
    ) -> bool:
        with self._lock:
            contexto_sesion = self._session_id
            contexto_configuracion = self._configuracion
            if contexto_sesion is None or contexto_configuracion is None:
                return False
            if session_id is not None and session_id != contexto_sesion:
                return False
            if revision is not None and revision != contexto_configuracion.revision:
                return False
            capturado = time.monotonic()
            self._secuencias[tipo] += 1
            self._frames[tipo] = FramePendiente(
                session_id=contexto_sesion,
                revision=contexto_configuracion.revision,
                sequence=self._secuencias[tipo],
                frame=frame,
                capturado_monotono=capturado,
            )
            if tipo == "raw":
                self._capturas_monotono.append(capturado)
                if len(self._capturas_monotono) > 1:
                    intervalo = self._capturas_monotono[-1] - self._capturas_monotono[0]
                    source_fps = (
                        (len(self._capturas_monotono) - 1) / intervalo
                        if intervalo > 0
                        else 0.0
                    )
                    self._estado = EstadoRuntime(
                        self._estado.source_connected,
                        self._estado.processing,
                        self._estado.error_code,
                        capturado,
                        source_fps,
                        self._estado.inference_fps,
                    )
            if tipo == "raw":
                self._nuevo_frame_crudo.set()
            else:
                self._nueva_actualizacion.set()
            return True

    def ofrecer_observaciones(self, snapshots: tuple) -> None:
        with self._lock:
            self._observaciones = snapshots
            self._observaciones_version += 1
            self._nueva_actualizacion.set()

    def actualizar_fuente(
        self, *, conectada: bool, error_code: str | None = None
    ) -> None:
        """Actualiza la disponibilidad de captura sin alterar el estado YOLO."""

        with self._lock:
            cambio = self._estado.source_connected != conectada
            codigo = error_code
            if conectada and self._estado.error_code == "SOURCE_UNAVAILABLE":
                codigo = None
            elif conectada:
                codigo = self._estado.error_code
            self._estado = EstadoRuntime(
                conectada,
                self._estado.processing,
                codigo,
                time.monotonic(),
                self._estado.source_fps,
                self._estado.inference_fps,
            )
            if cambio or error_code is not None:
                self._nueva_actualizacion.set()

    def actualizar_estado(
        self,
        *,
        source_connected: bool,
        processing: bool,
        error_code: str | None,
        inference_fps: float | None = None,
    ) -> None:
        with self._lock:
            self._estado = EstadoRuntime(
                source_connected=source_connected,
                processing=processing,
                error_code=error_code,
                actualizado_monotono=time.monotonic(),
                source_fps=self._estado.source_fps,
                inference_fps=(
                    self._estado.inference_fps
                    if inference_fps is None
                    else inference_fps
                ),
            )
            self._nueva_actualizacion.set()

    def limpiar_notificacion(self) -> None:
        self._nueva_actualizacion.clear()

    def esperar_actualizacion(self, timeout: float) -> None:
        self._nueva_actualizacion.wait(timeout)

    def limpiar_notificacion_frame_crudo(self) -> None:
        self._nuevo_frame_crudo.clear()

    def esperar_frame_crudo(self, timeout: float) -> None:
        self._nuevo_frame_crudo.wait(timeout)

    def obtener_snapshot(self) -> tuple:
        with self._lock:
            return (
                self._session_id,
                self._configuracion,
                dict(self._frames),
                self._observaciones,
                self._observaciones_version,
                self._estado,
            )


class CapturadorRuntime(threading.Thread):
    """Lee la fuente en una hebra separada de YOLO y conserva solo el frame reciente."""

    def __init__(
        self,
        bus: VisionRuntimeBus,
        detener: threading.Event,
        *,
        modo: str,
        source_url: str,
        simulation_dir: Path,
        frame_duration: float,
    ) -> None:
        super().__init__(name="vision-frame-capture", daemon=True)
        self.bus = bus
        self.detener = detener
        self.modo = modo
        self.source_url = source_url
        self.simulation_dir = simulation_dir
        self.frame_duration = frame_duration

    def _publicar(self, frame: np.ndarray) -> None:
        self.bus.actualizar_fuente(conectada=True)
        self.bus.ofrecer_frame("raw", frame)

    def _capturar_simulacion(self) -> None:
        try:
            secuencia = build_simulation_sequence(
                self.simulation_dir, self.frame_duration
            )
        except OSError, ValueError:
            secuencia = ()
        imagenes = tuple(
            cv2.imread(str(elemento.path), cv2.IMREAD_COLOR) for elemento in secuencia
        )

        indice = -1
        proximo_cambio = 0.0
        while not self.detener.is_set():
            ahora = time.monotonic()
            if not secuencia:
                self.bus.actualizar_fuente(
                    conectada=False, error_code="SOURCE_UNAVAILABLE"
                )
                self.detener.wait(1.0)
                continue
            if indice < 0 or ahora >= proximo_cambio:
                indice = (
                    next_frame_index(indice, len(secuencia), loop=True)
                    if indice >= 0
                    else 0
                )
                assert indice is not None
                proximo_cambio = ahora + secuencia[indice].duration_seconds
                frame = imagenes[indice]
                if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
                    self.bus.actualizar_fuente(
                        conectada=False, error_code="FRAME_INVALID"
                    )
                else:
                    self._publicar(frame)
            self.detener.wait(max(0.001, min(0.05, proximo_cambio - time.monotonic())))

    def _capturar_camara(self) -> None:
        captura = None
        while not self.detener.is_set():
            if captura is None:
                try:
                    captura, _, _, frame_pendiente = open_http_source(self.source_url)
                    captura.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    self._publicar(frame_pendiente)
                except RuntimeError, cv2.error, OSError:
                    if captura is not None:
                        captura.release()
                    captura = None
                    self.bus.actualizar_fuente(
                        conectada=False,
                        error_code="SOURCE_UNAVAILABLE",
                    )
                    self.detener.wait(2.0)
                    continue
            try:
                frame = read_frame(captura, "vision source")
                self._publicar(frame)
            except RuntimeError, cv2.error, OSError:
                captura.release()
                captura = None
                self.bus.actualizar_fuente(
                    conectada=False,
                    error_code="SOURCE_UNAVAILABLE",
                )
                self.detener.wait(1.0)
        if captura is not None:
            captura.release()

    def run(self) -> None:
        if self.modo == "simulation":
            self._capturar_simulacion()
        else:
            self._capturar_camara()


class PublicadorVistaPrevia(threading.Thread):
    """Publica frames crudos en paralelo y descarta los que no alcanzan el siguiente envío."""

    def __init__(
        self,
        cliente: SmartParkingClient,
        bus: VisionRuntimeBus,
        detener: threading.Event,
        display_fps: float,
    ) -> None:
        super().__init__(name="vision-preview-publisher", daemon=True)
        self.cliente = cliente
        self.bus = bus
        self.detener = detener
        self.display_fps = display_fps
        self.ultima_sesion: UUID | None = None
        self.ultima_secuencia = 0
        self.proximo_envio = 0.0
        self.frames_descartados = 0
        self._error_reportado = False

    def run(self) -> None:
        while not self.detener.is_set():
            self.bus.limpiar_notificacion_frame_crudo()
            session_id, _, frames, _, _, _ = self.bus.obtener_snapshot()
            pendiente = frames.get("raw")
            if session_id != self.ultima_sesion:
                self.ultima_sesion = session_id
                self.ultima_secuencia = 0
                self.proximo_envio = 0.0
            if (
                session_id is None
                or self.cliente.session_id != session_id
                or pendiente is None
                or pendiente.session_id != session_id
                or pendiente.sequence <= self.ultima_secuencia
            ):
                self.bus.esperar_frame_crudo(0.25)
                continue

            ahora = time.monotonic()
            if ahora < self.proximo_envio:
                self.bus.esperar_frame_crudo(min(0.05, self.proximo_envio - ahora))
                continue

            jpeg = codificar_jpeg(
                limitar_dimension(pendiente.frame, MAXIMA_DIMENSION_CRUDA)
            )
            if jpeg is None:
                self.ultima_secuencia = pendiente.sequence
                continue
            try:
                self.cliente.publicar_frame(
                    "raw",
                    pendiente.session_id,
                    pendiente.revision,
                    pendiente.sequence,
                    jpeg,
                )
            except VisionAPIError as error:
                if not self._error_reportado:
                    codigo = (
                        "sin respuesta"
                        if error.status_code is None
                        else f"HTTP {error.status_code}"
                    )
                    print(
                        f"Vision no pudo publicar la vista previa ({codigo}).",
                        file=sys.stderr,
                    )
                    self._error_reportado = True
                self.bus.esperar_frame_crudo(0.25)
                continue
            except Exception as error:  # noqa: BLE001
                print(
                    f"Publicador de vista previa no disponible ({type(error).__name__}).",
                    file=sys.stderr,
                )
                self.bus.esperar_frame_crudo(0.5)
                continue

            self.frames_descartados += max(
                0,
                pendiente.sequence - self.ultima_secuencia - 1,
            )
            self.ultima_secuencia = pendiente.sequence
            self.proximo_envio = time.monotonic() + 1.0 / self.display_fps
            self._error_reportado = False


class PublicadorRuntime(threading.Thread):
    """Publica en una hebra aparte sin esperar en el ciclo de inferencia."""

    def __init__(
        self,
        cliente: SmartParkingClient,
        bus: VisionRuntimeBus,
        modo: str,
        detener: threading.Event,
        display_fps: float = 25.0,
    ) -> None:
        super().__init__(name="vision-api-publisher", daemon=True)
        self.cliente = cliente
        self.bus = bus
        self.modo = modo
        self.detener = detener
        self.display_fps = display_fps
        self.secuencia_estado = 0
        self.ultimas_secuencias: dict[TipoFrame, int] = {"raw": 0, "annotated": 0}
        self.version_observaciones = 0
        self.frames_descartados = {"raw": 0, "annotated": 0}
        self.annotated_upload_attempts = 0
        self.annotated_upload_failures = 0
        self.annotated_encode_failures = 0
        self.annotated_published_sequence = 0
        self.annotated_generation_stalls = 0
        self.annotated_last_failure_stage: str | None = None
        self._annotated_error_reportado: str | None = None
        self._proximo_intento_anotado = 0.0
        self._espera_error_anotado = 0.25
        self._sesion_diagnostico_anotado: UUID | None = None
        self._secuencia_cruda_diagnostico = 0
        self._secuencia_anotada_diagnostico = 0
        self._ultimo_avance_crudo_diagnostico = 0.0
        self._ultimo_avance_anotado_diagnostico = 0.0
        self._anotacion_frenada_reportada = False
        ahora = time.monotonic()
        self.proximo_heartbeat = ahora
        self.proxima_configuracion = ahora + INTERVALO_CONFIGURACION_SEGUNDOS
        self.proximo_estado = ahora
        self.espera_error = 0.5
        self._error_reportado: str | None = None

    def _establecer_contexto(self) -> None:
        if self.cliente.session_id is None or self.cliente.configuracion is None:
            self.cliente.cargar_configuracion()
            self.cliente.iniciar_sesion()
        assert self.cliente.session_id is not None
        assert self.cliente.configuracion is not None
        self.bus.actualizar_contexto(
            self.cliente.session_id, self.cliente.configuracion
        )
        self.ultimas_secuencias = {"raw": 0, "annotated": 0}
        self.annotated_published_sequence = 0
        self.annotated_last_failure_stage = None
        self._annotated_error_reportado = None
        self._proximo_intento_anotado = 0.0
        self.version_observaciones = 0
        ahora = time.monotonic()
        self.proximo_heartbeat = ahora
        self.proxima_configuracion = (
            ahora + INTERVALO_CONFIGURACION_SEGUNDOS
        )
        self.secuencia_estado = 0

    def _renovar_sesion(self) -> None:
        self.cliente.session_id = None
        self.cliente._ultimo_estado_publicado = None
        self.cliente.cargar_configuracion()
        self.cliente.iniciar_sesion()
        self._establecer_contexto()

    def _aplicar_configuracion(self, actual: ConfiguracionRemota) -> None:
        if self.bus.actualizar_configuracion(actual):
            self.cliente._ultimo_estado_publicado = None
            self.version_observaciones = 0
            self._proximo_intento_anotado = 0.0
            self._espera_error_anotado = 0.25

    def _actualizar_configuracion(self) -> None:
        revision_anterior = (
            self.cliente.configuracion.revision
            if self.cliente.configuracion is not None
            else None
        )
        actual = self.cliente.cargar_configuracion()
        self.proxima_configuracion = (
            time.monotonic() + INTERVALO_CONFIGURACION_SEGUNDOS
        )
        if self.cliente.session_id is None:
            self.cliente.iniciar_sesion()
            self._establecer_contexto()
        elif revision_anterior is not None and actual.revision != revision_anterior:
            self._aplicar_configuracion(actual)

    def _resolver_conflicto(self) -> None:
        """Aplica la revision vigente antes de renovar una sesion realmente obsoleta."""

        revision_anterior = (
            self.cliente.configuracion.revision
            if self.cliente.configuracion is not None
            else None
        )
        self._actualizar_configuracion()
        configuracion_actual = self.cliente.configuracion
        if (
            revision_anterior is None
            or configuracion_actual is None
            or configuracion_actual.revision == revision_anterior
        ):
            self._renovar_sesion()
            return

        try:
            self.cliente.heartbeat()
        except VisionAPIError as error:
            if error.status_code != 409:
                raise
            self._renovar_sesion()

    def _publicar_frames(
        self, session_id: UUID, frames: dict[TipoFrame, FramePendiente]
    ) -> None:
        assert self.cliente.session_id is not None
        if time.monotonic() < self._proximo_intento_anotado:
            return
        for tipo in ("annotated",):
            pendiente = frames.get(tipo)
            if (
                pendiente is None
                or pendiente.session_id != session_id
                or pendiente.sequence <= self.ultimas_secuencias[tipo]
                or pendiente.session_id != self.cliente.session_id
            ):
                continue
            dimension = MAXIMA_DIMENSION_ANNOTADA
            try:
                jpeg = codificar_jpeg(
                    limitar_dimension(pendiente.frame, dimension)
                )
            except (cv2.error, TypeError, ValueError) as error:
                self.annotated_encode_failures += 1
                self.annotated_last_failure_stage = "encode"
                self.ultimas_secuencias[tipo] = pendiente.sequence
                firma = f"encode_{type(error).__name__}"
                self._registrar_error_frame_anotado(firma)
                continue
            if jpeg is None:
                self.annotated_encode_failures += 1
                self.annotated_last_failure_stage = "encode"
                self.ultimas_secuencias[tipo] = pendiente.sequence
                self._registrar_error_frame_anotado("encode_rejected")
                continue
            self.annotated_upload_attempts += 1
            try:
                self.cliente.publicar_frame(
                    tipo,
                    pendiente.session_id,
                    pendiente.revision,
                    pendiente.sequence,
                    jpeg,
                )
            except VisionAPIError as error:
                if error.status_code == 409:
                    raise
                self.annotated_upload_failures += 1
                self.annotated_last_failure_stage = "upload"
                firma = (
                    "upload_no_response"
                    if error.status_code is None
                    else f"upload_http_{error.status_code}"
                )
                self._registrar_error_frame_anotado(firma)
                self._programar_reintento_anotado()
                return
            except (OSError, TimeoutError) as error:
                self.annotated_upload_failures += 1
                self.annotated_last_failure_stage = "upload"
                self._registrar_error_frame_anotado(
                    f"upload_{type(error).__name__}"
                )
                self._programar_reintento_anotado()
                return
            self.frames_descartados[tipo] += max(
                0,
                pendiente.sequence - self.ultimas_secuencias[tipo] - 1,
            )
            self.ultimas_secuencias[tipo] = pendiente.sequence
            self.annotated_published_sequence = pendiente.sequence
            self.annotated_last_failure_stage = None
            self._annotated_error_reportado = None
            self._espera_error_anotado = 0.25
            self._proximo_intento_anotado = 0.0

    def _registrar_error_frame_anotado(self, firma: str) -> None:
        if firma != self._annotated_error_reportado:
            print(
                f"Vision no pudo procesar el frame anotado ({firma}).",
                file=sys.stderr,
                flush=True,
            )
            self._annotated_error_reportado = firma

    def _programar_reintento_anotado(self) -> None:
        self._proximo_intento_anotado = time.monotonic() + self._espera_error_anotado
        self._espera_error_anotado = min(4.0, self._espera_error_anotado * 2.0)

    def _diagnosticar_generacion_anotada(
        self,
        session_id: UUID,
        frames: dict[TipoFrame, FramePendiente],
        *,
        processing: bool,
        ahora: float | None = None,
    ) -> None:
        """Distingue una falla de inferencia/render de una falla de upload."""

        instante = time.monotonic() if ahora is None else ahora
        if session_id != self._sesion_diagnostico_anotado:
            self._sesion_diagnostico_anotado = session_id
            frame_crudo = frames.get("raw")
            frame_anotado = frames.get("annotated")
            self._secuencia_cruda_diagnostico = (
                frame_crudo.sequence if frame_crudo is not None else 0
            )
            self._secuencia_anotada_diagnostico = (
                frame_anotado.sequence if frame_anotado is not None else 0
            )
            self._ultimo_avance_crudo_diagnostico = instante
            self._ultimo_avance_anotado_diagnostico = instante
            self._anotacion_frenada_reportada = False
            return

        frame_crudo = frames.get("raw")
        if (
            frame_crudo is not None
            and frame_crudo.session_id == session_id
            and frame_crudo.sequence > self._secuencia_cruda_diagnostico
        ):
            self._secuencia_cruda_diagnostico = frame_crudo.sequence
            self._ultimo_avance_crudo_diagnostico = instante

        frame_anotado = frames.get("annotated")
        if (
            frame_anotado is not None
            and frame_anotado.session_id == session_id
            and frame_anotado.sequence > self._secuencia_anotada_diagnostico
        ):
            self._secuencia_anotada_diagnostico = frame_anotado.sequence
            self._ultimo_avance_anotado_diagnostico = instante
            self._anotacion_frenada_reportada = False
            if self.annotated_last_failure_stage == "inference_render":
                self.annotated_last_failure_stage = None

        captura_activa = (
            instante - self._ultimo_avance_crudo_diagnostico <= 1.0
        )
        anotacion_estancada = (
            instante - self._ultimo_avance_anotado_diagnostico
            >= MAXIMO_TIEMPO_SIN_FRAME_ANOTADO_SEGUNDOS
        )
        if (
            processing
            and captura_activa
            and anotacion_estancada
            and not self._anotacion_frenada_reportada
        ):
            self.annotated_generation_stalls += 1
            self.annotated_last_failure_stage = "inference_render"
            self._anotacion_frenada_reportada = True
            print(
                "Vision no genera frames anotados "
                f"(raw_sequence={self._secuencia_cruda_diagnostico}, "
                f"annotated_local_sequence={self._secuencia_anotada_diagnostico}).",
                file=sys.stderr,
                flush=True,
            )

    def run(self) -> None:
        while not self.detener.is_set():
            self.bus.limpiar_notificacion()
            try:
                ahora = time.monotonic()
                if self.cliente.session_id is None:
                    self._establecer_contexto()

                if ahora >= self.proxima_configuracion:
                    self._actualizar_configuracion()

                session_id, _, frames, observaciones, version, estado = (
                    self.bus.obtener_snapshot()
                )
                if session_id is None or self.cliente.session_id is None:
                    self.detener.wait(0.25)
                    continue

                self._diagnosticar_generacion_anotada(
                    session_id,
                    frames,
                    processing=estado.processing,
                )
                # La vista anotada avanza aunque falle una publicación de estado.
                self._publicar_frames(session_id, frames)

                if ahora >= self.proximo_estado:
                    self.secuencia_estado += 1
                    self.cliente.publicar_estado_runtime(
                        session_id=session_id,
                        revision=(
                            self.cliente.configuracion.revision
                            if self.cliente.configuracion is not None
                            else 0
                        ),
                        sequence=self.secuencia_estado,
                        mode=self.modo,
                        source_connected=(
                            estado.source_connected
                            and ahora - estado.actualizado_monotono
                            <= MAXIMA_ANTIGUEDAD_RUNTIME_SEGUNDOS
                        ),
                        processing=(
                            estado.processing
                            and ahora - estado.actualizado_monotono
                            <= MAXIMA_ANTIGUEDAD_RUNTIME_SEGUNDOS
                        ),
                        error_code=(
                            estado.error_code
                            if ahora - estado.actualizado_monotono
                            <= MAXIMA_ANTIGUEDAD_RUNTIME_SEGUNDOS
                            else "SOURCE_UNAVAILABLE"
                        ),
                        source_fps=estado.source_fps,
                        inference_fps=estado.inference_fps,
                        zone_states=observaciones or (),
                    )
                    self.proximo_estado = ahora + 1.0
                if (
                    observaciones is not None
                    and version != self.version_observaciones
                    and all(snapshot.is_ready for snapshot in observaciones)
                ):
                    if self.cliente.publicar_observaciones(observaciones):
                        self.version_observaciones = version

                if ahora >= self.proximo_heartbeat:
                    self.cliente.heartbeat()
                    self.proximo_heartbeat = ahora + 10.0

                self._error_reportado = None
                self.espera_error = 0.5
                proximo_evento = min(
                    self.proximo_estado,
                    self.proxima_configuracion,
                    self.proximo_heartbeat,
                )
                self.bus.esperar_actualizacion(
                    max(0.001, min(1.0, proximo_evento - time.monotonic()))
                )
            except VisionAPIError as error:
                if error.status_code == 409:
                    try:
                        self._resolver_conflicto()
                        continue
                    except VisionAPIError as error_renovacion:
                        error = error_renovacion
                firma = (
                    "sin respuesta"
                    if error.status_code is None
                    else f"HTTP {error.status_code}"
                )
                if firma != self._error_reportado:
                    print(
                        f"Vision no pudo publicar telemetría ({firma}); se conserva el último estado validado.",
                        file=sys.stderr,
                    )
                    self._error_reportado = firma
                self.detener.wait(self.espera_error)
                self.espera_error = min(15.0, self.espera_error * 2)
            except Exception as error:  # noqa: BLE001
                if self._error_reportado != "interno":
                    print(
                        f"Publicador Vision no disponible ({type(error).__name__}).",
                        file=sys.stderr,
                    )
                    self._error_reportado = "interno"
                self.detener.wait(self.espera_error)
                self.espera_error = min(15.0, self.espera_error * 2)


class VisionRuntime:
    """Coordina una sola inferencia y reutiliza los algoritmos existentes."""

    def __init__(
        self, api_url: str, *, modo: str, detener: threading.Event | None = None
    ) -> None:
        if modo not in {"simulation", "camera"}:
            raise ValueError("VISION_SOURCE_MODE debe ser simulation o camera.")
        self.api_url = api_url
        self.modo = modo
        self.detener = detener or threading.Event()
        self.inference_fps = self._leer_fps("VISION_INFERENCE_FPS", 25.0)
        self.display_fps = self._leer_fps("VISION_DISPLAY_FPS", 25.0)
        self.torch_num_threads = self._leer_entero(
            "VISION_TORCH_NUM_THREADS",
            3,
            minimo=1,
            maximo=16,
        )
        self.torch_num_interop_threads = self._leer_entero(
            "VISION_TORCH_NUM_INTEROP_THREADS",
            1,
            minimo=1,
            maximo=16,
        )
        self.opencv_num_threads = self._leer_entero(
            "VISION_OPENCV_NUM_THREADS",
            1,
            minimo=1,
            maximo=16,
        )
        self.dimension_imgsz = self._leer_entero(
            "VISION_IMAGE_SIZE", 640, minimo=32, maximo=1920
        )
        self.frame_duration = self._leer_fps("VISION_FRAME_DURATION_SECONDS", 3.0)
        self.simulation_dir = Path(
            os.environ.get(
                "VISION_SIMULATION_DIR", str(Path(__file__).parent / "simulations")
            )
        )
        self.source_url = os.environ.get("VISION_SOURCE_URL", "").strip()
        if self.modo == "camera":
            self._validar_url_fuente(self.source_url)
        self.model_path = Path(
            os.environ.get(
                "VISION_MODEL_PATH",
                str(Path(__file__).parent / "models" / "yolo26n.pt"),
            )
        )
        timeout = self._leer_fps("VISION_API_TIMEOUT_SECONDS", 2.0)
        self.cliente = SmartParkingClient(api_url, timeout=timeout)
        self.bus = VisionRuntimeBus()
        self.publicador: PublicadorRuntime | None = None
        self.publicador_preview: PublicadorVistaPrevia | None = None
        self.capturador: CapturadorRuntime | None = None

    @staticmethod
    def _validar_url_fuente(url: str) -> None:
        """Exige una URL HTTP explícita cuando el runtime usa una cámara."""

        try:
            origen = urlsplit(url)
            puerto = origen.port
        except ValueError as error:
            raise ValueError(
                "VISION_SOURCE_URL debe ser una URL HTTP válida."
            ) from error
        if (
            origen.scheme.lower() != "http"
            or not origen.hostname
            or origen.username is not None
            or origen.password is not None
            or (puerto is not None and puerto < 1)
        ):
            raise ValueError("VISION_SOURCE_URL debe ser una URL HTTP válida.")

    @staticmethod
    def _leer_fps(nombre: str, predeterminado: float) -> float:
        try:
            valor = float(os.environ.get(nombre, str(predeterminado)))
        except ValueError:
            return predeterminado
        return valor if np.isfinite(valor) and valor > 0 else predeterminado

    @staticmethod
    def _leer_entero(
        nombre: str, predeterminado: int, *, minimo: int, maximo: int
    ) -> int:
        try:
            valor = int(os.environ.get(nombre, str(predeterminado)))
        except ValueError:
            return predeterminado
        return min(maximo, max(minimo, valor))

    def _conectar_api(self) -> None:
        espera = 0.5
        while not self.detener.is_set():
            try:
                self.cliente.cargar_configuracion()
                self.cliente.iniciar_sesion()
                assert self.cliente.session_id is not None
                assert self.cliente.configuracion is not None
                self.bus.actualizar_contexto(
                    self.cliente.session_id,
                    self.cliente.configuracion,
                )
                return
            except VisionAPIError as error:
                codigo = (
                    "sin respuesta"
                    if error.status_code is None
                    else f"HTTP {error.status_code}"
                )
                print(
                    f"Vision espera la API ({codigo}); reintento en {espera:g}s.",
                    file=sys.stderr,
                )
                self.detener.wait(espera)
                espera = min(15.0, espera * 2)

    def ejecutar(self) -> int:
        torch.set_num_interop_threads(self.torch_num_interop_threads)
        self._conectar_api()
        if self.detener.is_set():
            return 0

        self.capturador = CapturadorRuntime(
            self.bus,
            self.detener,
            modo=self.modo,
            source_url=self.source_url,
            simulation_dir=self.simulation_dir,
            frame_duration=self.frame_duration,
        )
        self.publicador = PublicadorRuntime(
            self.cliente,
            self.bus,
            self.modo,
            self.detener,
            display_fps=self.display_fps,
        )
        self.publicador_preview = PublicadorVistaPrevia(
            self.cliente,
            self.bus,
            self.detener,
            self.display_fps,
        )
        self.publicador.start()
        self.publicador_preview.start()
        self.capturador.start()

        guarda_calidad = FrameQualityGuard()
        modelo = None
        hilos_inferencia_configurados = False
        proximo_intento_modelo = 0.0
        ultima_revision = -1
        validador: TemporalOccupancyValidator | None = None
        proximo_inferencia = 0.0
        proximo_frame_anotado = 0.0
        sesion_cursor_inferencia: UUID | None = None
        ultima_secuencia_inferida = 0
        tiempos_inferencia: deque[float] = deque(maxlen=31)
        metricas: deque[dict[str, float]] = deque(maxlen=60)
        frames_descartados_inferencia = 0
        proximo_reporte = time.monotonic() + 10.0

        try:
            while not self.detener.is_set():
                ahora = time.monotonic()
                if modelo is None and ahora >= proximo_intento_modelo:
                    try:
                        modelo = load_model_from_path(self.model_path)
                    except (OSError, RuntimeError, ValueError) as error:
                        if proximo_intento_modelo == 0.0:
                            print(
                                f"Checkpoint Vision no disponible ({type(error).__name__}); se conserva el modo seguro.",
                                file=sys.stderr,
                            )
                        proximo_intento_modelo = ahora + 30.0

                session_id, configuracion = self.bus.obtener_contexto()
                if session_id is None or configuracion is None:
                    self.detener.wait(0.1)
                    continue
                sesion_cursor_inferencia, ultima_secuencia_inferida = (
                    ajustar_cursor_inferencia(
                        session_id,
                        sesion_cursor_inferencia,
                        ultima_secuencia_inferida,
                    )
                )
                if configuracion.revision != ultima_revision:
                    validador = TemporalOccupancyValidator(_crear_zonas(configuracion))
                    guarda_calidad = FrameQualityGuard()
                    ultima_revision = configuracion.revision

                if modelo is None:
                    _, _, _, _, _, estado = self.bus.obtener_snapshot()
                    self.bus.actualizar_estado(
                        source_connected=estado.source_connected,
                        processing=False,
                        error_code="MODEL_UNAVAILABLE",
                    )
                    self.detener.wait(0.25)
                    continue

                _, _, frames, _, _, _ = self.bus.obtener_snapshot()
                frame_actual = frames.get("raw")
                if (
                    frame_actual is None
                    or frame_actual.sequence <= ultima_secuencia_inferida
                ):
                    self.detener.wait(0.01)
                    continue

                ahora = time.monotonic()
                if ahora < proximo_inferencia:
                    self.detener.wait(proximo_inferencia - ahora)
                    continue
                proximo_inferencia = ahora + 1.0 / self.inference_fps
                frames_descartados_inferencia += max(
                    0,
                    frame_actual.sequence - ultima_secuencia_inferida - 1,
                )
                ultima_secuencia_inferida = frame_actual.sequence
                frame = frame_actual.frame

                valido, _ = guarda_calidad.inspect(
                    frame,
                    allow_repeated=self.modo == "simulation",
                )
                if not valido:
                    self.bus.actualizar_estado(
                        source_connected=True,
                        processing=False,
                        error_code="FRAME_INVALID",
                    )
                    continue

                try:
                    resultado, predict_call_ms, inferencia_ms = predict(
                        modelo,
                        frame,
                        self.dimension_imgsz,
                        0.30,
                    )
                    if not hilos_inferencia_configurados:
                        torch.set_num_threads(self.torch_num_threads)
                        cv2.setNumThreads(self.opencv_num_threads)
                        hilos_inferencia_configurados = True
                    inicio_detecciones = time.monotonic()
                    detecciones = detections_from_result(resultado)
                    detecciones_ms = (time.monotonic() - inicio_detecciones) * 1000.0
                except Exception as error:  # noqa: BLE001
                    if self.publicador is not None:
                        self.bus.actualizar_estado(
                            source_connected=True,
                            processing=False,
                            error_code="MODEL_UNAVAILABLE",
                        )
                    print(
                        f"Inferencia Vision no disponible ({type(error).__name__}).",
                        file=sys.stderr,
                    )
                    self.detener.wait(0.5)
                    continue

                assert validador is not None
                alto, ancho = frame.shape[:2]
                inicio_validacion = time.monotonic()
                snapshots = validador.process_frame(
                    detecciones, ancho, alto, valid=True
                )
                validacion_ms = (time.monotonic() - inicio_validacion) * 1000.0
                terminado_monotono = time.monotonic()
                tiempos_inferencia.append(terminado_monotono)
                fps_inferencia = (
                    (len(tiempos_inferencia) - 1)
                    / max(0.001, tiempos_inferencia[-1] - tiempos_inferencia[0])
                    if len(tiempos_inferencia) > 1
                    else 0.0
                )
                self.bus.ofrecer_observaciones(snapshots)
                self.bus.actualizar_estado(
                    source_connected=True,
                    processing=True,
                    error_code=None,
                    inference_fps=fps_inferencia,
                )

                ahora = time.monotonic()
                render_ms = 0.0
                if ahora >= proximo_frame_anotado:
                    inicio_render = time.monotonic()
                    anotado, _ = render_frame(
                        frame,
                        resultado,
                        snapshots,
                        source_fps=0.0,
                        processed_fps=fps_inferencia,
                        inference_ms=inferencia_ms,
                        end_to_end_ms=(
                            terminado_monotono - frame_actual.capturado_monotono
                        )
                        * 1000.0,
                        validation_ms=validacion_ms,
                        minimum_confidence=0.30,
                        imgsz=self.dimension_imgsz,
                        confidence=0.30,
                        input_status=None,
                        detections=detecciones,
                        simulation_status=(
                            "SECUENCIA DE SIMULACIÓN",
                            "No es una cámara en vivo",
                        )
                        if self.modo == "simulation"
                        else None,
                    )
                    render_ms = (time.monotonic() - inicio_render) * 1000.0
                    self.bus.ofrecer_frame(
                        "annotated",
                        anotado,
                        session_id=session_id,
                        revision=configuracion.revision,
                    )
                    proximo_frame_anotado = ahora + 1.0 / self.display_fps

                metricas.append(
                    {
                        "yolo_model_ms": inferencia_ms,
                        "predict_call_ms": predict_call_ms,
                        "detection_conversion_ms": detecciones_ms,
                        "validation_ms": validacion_ms,
                        "render_ms": render_ms,
                        "capture_to_result_ms": (
                            terminado_monotono - frame_actual.capturado_monotono
                        )
                        * 1000.0,
                    }
                )
                if time.monotonic() >= proximo_reporte:
                    _, _, frames_actuales, _, _, estado_actual = (
                        self.bus.obtener_snapshot()
                    )
                    muestras = tuple(metricas)
                    print(
                        "vision_performance="
                        + json.dumps(
                            {
                                "mode": self.modo,
                                "torch_threads": torch.get_num_threads(),
                                "torch_interop_threads": torch.get_num_interop_threads(),
                                "opencv_threads": cv2.getNumThreads(),
                                "source_fps": round(estado_actual.source_fps, 2),
                                "inference_fps": round(fps_inferencia, 2),
                                "raw_capture_sequence": (
                                    frames_actuales["raw"].sequence
                                    if "raw" in frames_actuales
                                    else 0
                                ),
                                "annotated_local_sequence": (
                                    frames_actuales["annotated"].sequence
                                    if "annotated" in frames_actuales
                                    else 0
                                ),
                                "annotated_published_sequence": (
                                    self.publicador.annotated_published_sequence
                                ),
                                "annotated_upload_attempts": (
                                    self.publicador.annotated_upload_attempts
                                ),
                                "annotated_upload_failures": (
                                    self.publicador.annotated_upload_failures
                                ),
                                "annotated_encode_failures": (
                                    self.publicador.annotated_encode_failures
                                ),
                                "annotated_generation_stalls": (
                                    self.publicador.annotated_generation_stalls
                                ),
                                "annotated_last_failure_stage": (
                                    self.publicador.annotated_last_failure_stage
                                ),
                                "inference_frames_skipped": frames_descartados_inferencia,
                                "raw_frames_skipped_before_upload": self.publicador_preview.frames_descartados,
                                **{
                                    f"{nombre}_avg_ms": round(
                                        fmean(muestra[nombre] for muestra in muestras),
                                        2,
                                    )
                                    for nombre in (
                                        "yolo_model_ms",
                                        "predict_call_ms",
                                        "detection_conversion_ms",
                                        "validation_ms",
                                        "render_ms",
                                        "capture_to_result_ms",
                                    )
                                },
                            },
                            separators=(",", ":"),
                        ),
                        flush=True,
                    )
                    proximo_reporte = time.monotonic() + 10.0

        except KeyboardInterrupt:
            return 0
        finally:
            self.detener.set()
            if self.capturador is not None:
                self.capturador.join(timeout=2.5)
            if self.publicador_preview is not None:
                self.publicador_preview.join(timeout=2.5)
            if self.publicador is not None:
                self.publicador.join(timeout=2.5)
        return 0


def main() -> int:
    modo = os.environ.get("VISION_SOURCE_MODE", "camera").lower()
    api_url = os.environ.get("VISION_API_BASE_URL", "http://127.0.0.1:8000")
    try:
        runtime = VisionRuntime(api_url, modo=modo)
        return runtime.ejecutar()
    except (ValueError, VisionAPIError) as error:
        print(
            f"No se pudo iniciar Vision ({type(error).__name__}): {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MAXIMA_DIMENSION_ANNOTADA",
    "MAXIMA_DIMENSION_CRUDA",
    "MAXIMO_BYTES_JPEG",
    "CapturadorRuntime",
    "PublicadorVistaPrevia",
    "PublicadorRuntime",
    "VisionRuntime",
    "VisionRuntimeBus",
    "codificar_jpeg",
    "limitar_dimension",
    "main",
]
