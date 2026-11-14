"""Obtiene imágenes desde la cámara o dirección elegida sin buscar otras fuentes."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

# Evita mostrar la dirección privada si falla la conexión con la cámara.
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")
import cv2

CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720
CAPTURE_SIZE = (CAPTURE_WIDTH, CAPTURE_HEIGHT)
DEFAULT_HTTP_URL = "http://127.0.0.1:4747/video"
HTTP_OPEN_TIMEOUT_MS = 5000
HTTP_READ_TIMEOUT_MS = 5000


def resolver_url_http(url: str | None) -> str:
    """Elige la dirección indicada, la de un archivo privado o la predeterminada.

    Rechaza direcciones que incluyan datos de acceso.
    """
    if url is None:
        ruta = os.environ.get("VISION_HTTP_URL_FILE")
        if ruta:
            try:
                lineas = Path(ruta).read_text(encoding="utf-8").splitlines()
            except OSError as error:
                raise RuntimeError("No se pudo leer el archivo privado de fuente HTTP.") from error
            if len(lineas) != 1 or not lineas[0].strip():
                raise ValueError("El archivo de fuente HTTP debe contener una sola linea.")
            url = lineas[0].strip()
        else:
            url = DEFAULT_HTTP_URL
    try:
        partes = urlsplit(url)
        # Los datos de acceso en la dirección podrían aparecer en mensajes de error.
        if partes.scheme.lower() not in ("http", "https") or not partes.hostname:
            raise ValueError
        if partes.username is not None or partes.password is not None:
            raise ValueError
        _ = partes.port
    except ValueError as error:
        raise ValueError("La fuente debe ser una URL HTTP(S) valida sin credenciales incrustadas.") from error
    return url


def validar_dispositivo(device: str | Path | None) -> str:
    """Acepta solo una ruta completa de dispositivo elegida dentro de /dev."""
    if device is None:
        raise ValueError("La fuente camera requiere --device con un nodo V4L2 explicito.")
    ruta = Path(device)
    if not ruta.is_absolute() or not ruta.is_relative_to("/dev") or ".." in ruta.parts:
        raise ValueError("El dispositivo V4L2 debe ser una ruta absoluta dentro de /dev.")
    return str(ruta)


def validate_frame(frame: object, source_name: str) -> None:
    if frame is None or not hasattr(frame, "shape") or len(frame.shape) != 3:
        raise RuntimeError(f"{source_name}: cuadro vacio o malformado.")
    if frame.shape[2] != 3 or frame.shape[0] < 1 or frame.shape[1] < 1:
        raise RuntimeError(f"{source_name}: se esperaba una imagen BGR de tres canales.")


def read_frame(capture: cv2.VideoCapture, source_name: str) -> object:
    try:
        ok, frame = capture.read()
    except cv2.error as error:
        raise RuntimeError(f"{source_name}: error de lectura.") from error
    if not ok:
        raise RuntimeError(f"{source_name}: lectura interrumpida.")
    validate_frame(frame, source_name)
    return frame


def open_http_source(url: str) -> tuple[cv2.VideoCapture, str, str, object]:
    """Conecta con la dirección elegida y obtiene la primera imagen.

    Si no puede hacerlo, cierra la conexión antes de informar el error.
    """
    url = resolver_url_http(url)
    capture = cv2.VideoCapture()
    try:
        opened = capture.open(
            url,
            cv2.CAP_FFMPEG,
            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, HTTP_OPEN_TIMEOUT_MS,
             cv2.CAP_PROP_READ_TIMEOUT_MSEC, HTTP_READ_TIMEOUT_MS],
        )
        if not opened or not capture.isOpened():
            raise RuntimeError("No se pudo abrir la fuente HTTP seleccionada.")
        frame = read_frame(capture, "Fuente HTTP")
        return capture, "Fuente HTTP", "FFmpeg", frame
    except Exception as error:
        capture.release()
        if isinstance(error, RuntimeError):
            raise
        raise RuntimeError("No se pudo abrir la fuente HTTP seleccionada.") from error


def open_camera(device: str | Path) -> tuple[cv2.VideoCapture, str, str, object]:
    """Abre únicamente la cámara indicada y obtiene su primera imagen.

    Si falla la lectura, libera la cámara antes de informar el error.
    """
    ruta = validar_dispositivo(device)
    try:
        capture = cv2.VideoCapture(ruta, cv2.CAP_V4L2)
    except cv2.error as error:
        raise RuntimeError("No se pudo abrir el dispositivo V4L2 seleccionado.") from error
    try:
        if not capture.isOpened():
            raise RuntimeError("No se pudo abrir el dispositivo V4L2 seleccionado.")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
        frame = read_frame(capture, "Fuente V4L2")
        fps = capture.get(cv2.CAP_PROP_FPS)
        print(f"V4L2 negociado: {frame.shape[1]}x{frame.shape[0]}, {fps:.2f} FPS.")
        return capture, "Fuente V4L2", "V4L2", frame
    except Exception:
        capture.release()
        raise


def open_video_source(source: str, http_url: str | None, device: str | None,
                      backend: str | None = None) -> tuple[cv2.VideoCapture, str, str, object]:
    """Abre la cámara o dirección seleccionada sin buscar otras por su cuenta."""
    if source == "http":
        return open_http_source(resolver_url_http(http_url))
    if source == "camera":
        return open_camera(validar_dispositivo(device))
    raise ValueError("Fuente desconocida; seleccione http o camera.")


# Una sola parte del programa abre, lee y cierra la cámara.
# Las demás consultan la imagen más reciente sin manejar la cámara directamente.
@dataclass(frozen=True)
class MuestraCaptura:
    """Reúne la imagen más reciente, cuándo llegó y el estado de la conexión."""
    estado: str
    revision: int
    generacion: int
    momento: float | None
    cuadro: object | None
    backend: str | None


class CapturadorReciente:
    """Lee imágenes continuamente y conserva la más reciente para evitar imágenes antiguas."""

    def __init__(self, source: str, http_url: str | None, device: str | None,
                 *, pausa_reconexion: float = 0.5) -> None:
        self.source = source
        self.http_url = http_url
        self.device = device
        self.pausa_reconexion = pausa_reconexion
        self._condicion = threading.Condition()
        self._terminar = threading.Event()
        self._estado = "conectando"
        self._revision = 0
        self._generacion = 0
        self._momento = None
        self._cuadro = None
        self._backend = None
        self._formato = None
        self._liberacion_correcta = True
        self._hilo = threading.Thread(target=self._leer_continuamente,
                                      name="vision-captura", daemon=True)

    def iniciar(self) -> None:
        """Comienza a leer imágenes de la cámara o dirección configurada."""
        self._hilo.start()

    def _instantanea_bajo_lock(self) -> MuestraCaptura:
        return MuestraCaptura(self._estado, self._revision, self._generacion,
                              self._momento, self._cuadro, self._backend)

    def instantanea(self) -> MuestraCaptura:
        """Entrega la última imagen junto con el estado actual de la conexión."""
        with self._condicion:
            return self._instantanea_bajo_lock()

    def esperar(self, revision: int, segundos: float = 0.1) -> MuestraCaptura:
        """Espera un cambio de imagen o conexión, el cierre o el tiempo indicado.

        Después entrega la información más reciente, aunque no haya habido cambios.
        """
        with self._condicion:
            self._condicion.wait_for(
                lambda: self._revision != revision or self._terminar.is_set(),
                timeout=segundos,
            )
            return self._instantanea_bajo_lock()

    def _publicar(self, cuadro: object, backend: str, *, nueva_conexion: bool) -> None:
        # La edad de la imagen se cuenta desde que llega, antes de buscar vehículos.
        momento = time.monotonic()
        formato = (tuple(cuadro.shape), str(cuadro.dtype))
        with self._condicion:
            if nueva_conexion or formato != self._formato:
                self._generacion += 1
            self._formato = formato
            self._cuadro = cuadro.copy()
            self._momento = momento
            self._backend = backend
            self._estado = "conectada"
            self._revision += 1
            self._condicion.notify_all()

    def _interrumpir(self) -> None:
        with self._condicion:
            self._cuadro = None
            self._momento = None
            self._estado = "interrumpida"
            self._revision += 1
            self._condicion.notify_all()

    def aplicar_si_vigente(self, muestra: MuestraCaptura, max_edad: float,
                           accion: Callable[[], None], *, misma_revision: bool = False) -> bool:
        """Aplica el resultado solo si la conexión sigue siendo la misma y la imagen es reciente.

        También puede exigir que no haya llegado otra imagen durante la revisión.
        """
        with self._condicion:
            if (self._estado != "conectada" or self._generacion != muestra.generacion
                    or (misma_revision and self._revision != muestra.revision)
                    or muestra.momento is None
                    or time.monotonic() - muestra.momento > max_edad):
                return False
            accion()
            return True

    def _leer_continuamente(self) -> None:
        while not self._terminar.is_set():
            captura = None
            try:
                captura, nombre, backend, cuadro = open_video_source(
                    self.source, self.http_url, self.device, None)
                if self._terminar.is_set():
                    break
                self._publicar(cuadro, backend, nueva_conexion=True)
                while not self._terminar.is_set():
                    cuadro = read_frame(captura, nombre)
                    if not self._terminar.is_set():
                        self._publicar(cuadro, backend, nueva_conexion=False)
            except Exception:
                self._interrumpir()
            finally:
                if captura is not None:
                    try:
                        captura.release()
                    except Exception:
                        self._liberacion_correcta = False
            if not self._terminar.is_set():
                self._terminar.wait(self.pausa_reconexion)
        with self._condicion:
            self._cuadro = None
            self._momento = None
            self._estado = "detenida"
            self._revision += 1
            self._condicion.notify_all()

    def detener(self, timeout: float = 12.0) -> bool:
        """Pide detener la lectura y espera el tiempo indicado.

        Indica si terminó y si la cámara pudo liberarse correctamente.
        """
        self._terminar.set()
        with self._condicion:
            self._condicion.notify_all()
        self._hilo.join(timeout=timeout)
        return not self._hilo.is_alive() and self._liberacion_correcta
