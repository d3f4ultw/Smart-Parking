"""Usa imágenes de una cámara, archivo o simulación para observar las zonas."""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from collections import deque
from pathlib import Path

os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")
import cv2
import numpy as np

from capture import CapturadorReciente, resolver_url_http, validar_dispositivo
from calibrar_zonas import (
    ALTO_CABECERA, COLOR_AVISO, COLOR_FONDO, COLOR_PRINCIPAL, COLOR_SECUNDARIO,
    COLOR_SEPARADOR, componer_marco, dibujar_etiqueta, zone_identity_color,
)
from configuracion_local import verificar_vinculo
from estado_local import EstadoLocal
from publicador_java import PublicadorVision, cargar_configuracion
from simulation_playback import build_simulation_sequence
from temporal_validation import (
    FrameQualityGuard, OccupancyState, VehicleDetection, ZoneSnapshot, load_zones,
)

WINDOW_TITLE = "Smart Parking Vision - Deteccion"
ANCHO_VENTANA_INICIAL = 1540
ALTO_VENTANA_INICIAL = 856
VEHICLE_CLASSES = (2, 3, 5, 7)
DEFAULT_MODEL = Path("/data/models/yolo26n.pt")
DEFAULT_ZONES = Path("/data/config/zones.json")
_CARGAR_MODELO_EN_VIVO = object()


def _crear_ventana() -> None:
    cv2.namedWindow(
        WINDOW_TITLE, cv2.WINDOW_NORMAL | cv2.WINDOW_FREERATIO,
    )
    cv2.resizeWindow(WINDOW_TITLE, ANCHO_VENTANA_INICIAL, ALTO_VENTANA_INICIAL)
    _centrar_ventana()


def _centrar_ventana() -> None:
    """Coloca la ventana en el centro de la pantalla cuando es posible."""
    x11 = None
    display = None
    try:
        x11 = ctypes.CDLL("libX11.so.6")
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XOpenDisplay.restype = ctypes.c_void_p
        display = x11.XOpenDisplay(None)
        if not display:
            return
        x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
        x11.XDefaultScreen.restype = ctypes.c_int
        x11.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x11.XDisplayWidth.restype = ctypes.c_int
        x11.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x11.XDisplayHeight.restype = ctypes.c_int
        pantalla = x11.XDefaultScreen(display)
        ancho_pantalla = x11.XDisplayWidth(display, pantalla)
        alto_pantalla = x11.XDisplayHeight(display, pantalla)
        x = max(0, (ancho_pantalla - ANCHO_VENTANA_INICIAL) // 2)
        y = max(0, (alto_pantalla - ALTO_VENTANA_INICIAL) // 2)
        cv2.moveWindow(WINDOW_TITLE, x, y)
        area = cv2.getWindowImageRect(WINDOW_TITLE)
        if area[2] > 0 and area[3] > 0:
            area_x = max(0, (ancho_pantalla - area[2]) // 2)
            area_y = max(0, (alto_pantalla - area[3]) // 2)
            x += area_x - area[0]
            y += area_y - area[1]
            cv2.moveWindow(WINDOW_TITLE, max(0, x), max(0, y))
    except (AttributeError, OSError, cv2.error):
        return
    finally:
        if x11 is not None and display:
            x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            x11.XCloseDisplay(display)


def _dimensiones_ventana() -> tuple[int, int]:
    try:
        _, _, ancho, alto = cv2.getWindowImageRect(WINDOW_TITLE)
    except (AttributeError, cv2.error):
        return ANCHO_VENTANA_INICIAL, ALTO_VENTANA_INICIAL
    if ancho <= 0 or alto <= 0:
        return ANCHO_VENTANA_INICIAL, ALTO_VENTANA_INICIAL
    return ancho, alto


def _ajustar_interfaz(
    imagen: np.ndarray, ancho_destino: int, alto_destino: int,
) -> tuple[np.ndarray, tuple[int, int, int, int, int, int]]:
    """Ajusta la imagen y sus controles al espacio disponible sin deformarlos."""
    alto_original, ancho_original = imagen.shape[:2]
    escala = min(ancho_destino / ancho_original, alto_destino / alto_original)
    ancho_renderizado = max(1, round(ancho_original * escala))
    alto_renderizado = max(1, round(alto_original * escala))
    margen_x = (ancho_destino - ancho_renderizado) // 2
    margen_y = (alto_destino - alto_renderizado) // 2
    if (ancho_renderizado, alto_renderizado) == (ancho_original, alto_original):
        redimensionada = imagen
    else:
        interpolacion = cv2.INTER_AREA if escala < 1 else cv2.INTER_LINEAR
        redimensionada = cv2.resize(
            imagen, (ancho_renderizado, alto_renderizado), interpolation=interpolacion,
        )
    lienzo = np.full((alto_destino, ancho_destino, 3), COLOR_FONDO, dtype=imagen.dtype)
    lienzo[margen_y:margen_y + alto_renderizado,
           margen_x:margen_x + ancho_renderizado] = redimensionada
    ajuste = (
        ancho_original, alto_original, ancho_renderizado, alto_renderizado, margen_x, margen_y,
    )
    return lienzo, ajuste


def _coordenadas_raton_a_interfaz(
    x: int, y: int, ajuste: tuple[int, int, int, int, int, int] | None,
) -> tuple[int, int]:
    if ajuste is None:
        return x, y
    ancho_original, alto_original, ancho_renderizado, alto_renderizado, margen_x, margen_y = ajuste
    x_interfaz = round((x - margen_x + 0.5) * ancho_original / ancho_renderizado - 0.5)
    y_interfaz = round((y - margen_y + 0.5) * alto_original / alto_renderizado - 0.5)
    return x_interfaz, y_interfaz


def _mostrar_interfaz(imagen: np.ndarray, coordenadas_raton: dict | None = None) -> None:
    ancho, alto = _dimensiones_ventana()
    lienzo, ajuste = _ajustar_interfaz(imagen, ancho, alto)
    if coordenadas_raton is not None:
        coordenadas_raton["ajuste"] = ajuste
    cv2.imshow(WINDOW_TITLE, lienzo)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--image", type=Path)
    grupo.add_argument("--simulation-dir", type=Path)
    grupo.add_argument("--source", choices=("http", "camera"))
    parser.add_argument("--http-url", help="URL explicita; preferir archivo privado")
    parser.add_argument("--device", help="dispositivo V4L2 explicito dentro de /dev")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--zones", type=Path, default=DEFAULT_ZONES)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--permanente", action="store_true",
                        help="runtime permanente headless con interfaz adjuntable")
    parser.add_argument("--control-socket", type=Path,
                        help="socket Unix privado del runtime permanente")
    parser.add_argument("--local-proposal", type=Path,
                        help="copia LOCAL para edicion y guardado locales")
    parser.add_argument(
        "--local-desktop", action="store_true",
        help="abrir monitor y calibracion locales sin publicar ocupacion en Java",
    )
    parser.add_argument(
        "--local-calibration-dir", type=Path,
        help="directorio exclusivo y escribible de la copia local de calibracion",
    )
    parser.add_argument(
        "--publish-java",
        action="store_true",
        help="habilitar explicitamente publicaciones a Java para esta ejecucion",
    )
    parser.add_argument(
        "--wait-for-calibration",
        action="store_true",
        help="esperar una calibracion valida antes de iniciar",
    )
    parser.add_argument("--frame-duration", type=float, default=30.0)
    parser.add_argument("--frame-duration-override", action="append", default=[])
    parser.add_argument("--playback-fps", type=float, default=5.0)
    parser.add_argument("--no-loop", action="store_true")
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--conf", type=float, default=0.30)
    parser.add_argument("--max-frame-age", type=float, default=2.0,
                        help="antiguedad maxima de una observacion viva en segundos")
    args = parser.parse_args()
    if args.imgsz < 32 or not math.isfinite(args.conf) or not 0 <= args.conf <= 1:
        parser.error("--imgsz debe ser >= 32 y --conf debe estar entre 0 y 1")
    if not math.isfinite(args.max_frame_age) or args.max_frame_age <= 0:
        parser.error("--max-frame-age debe ser positivo")
    if not math.isfinite(args.frame_duration) or args.frame_duration <= 0:
        parser.error("--frame-duration debe ser positivo")
    if not math.isfinite(args.playback_fps) or not 0 < args.playback_fps <= 60:
        parser.error("--playback-fps debe estar entre 0 y 60")
    if args.image or args.simulation_dir:
        if args.http_url is not None or args.device is not None:
            parser.error("La imagen o simulacion no se combinan con opciones de camara")
    else:
        args.source = args.source or "http"
        if args.source == "camera" and args.device is None:
            parser.error("--source camera requiere --device")
        if args.source == "camera" and args.http_url is not None:
            parser.error("--http-url solo aplica a la fuente http")
        if args.source == "http" and args.device is not None:
            parser.error("--device solo aplica a la fuente camera")
    if args.wait_for_calibration and (not args.headless or args.image or args.simulation_dir):
        parser.error("--wait-for-calibration requiere captura headless de una fuente persistente")
    if args.local_desktop and (args.publish_java or args.headless or args.image or args.simulation_dir):
        parser.error("--local-desktop requiere captura con ventana y no admite --publish-java")
    if args.local_desktop and args.local_calibration_dir is None:
        parser.error("--local-desktop requiere --local-calibration-dir")
    if args.local_calibration_dir is not None and not args.local_desktop:
        parser.error("--local-calibration-dir requiere --local-desktop")
    if args.permanente and (not args.headless or args.local_desktop or args.image or args.simulation_dir
                            or args.control_socket is None or args.local_proposal is None):
        parser.error("--permanente requiere captura headless, control Unix y propuesta LOCAL")
    if not args.permanente and (args.control_socket is not None or args.local_proposal is not None):
        parser.error("El control y la propuesta LOCAL requieren --permanente")
    return args


def probar_grafica_aislada(display: str) -> bool:
    """Comprueba aparte si es posible abrir una ventana.

    Así un fallo de la pantalla no cierra el programa principal.
    """
    entorno = os.environ.copy()
    entorno["DISPLAY"] = display
    try:
        resultado = subprocess.run(
            [sys.executable, "-c", "import cv2; cv2.namedWindow('Vision - prueba grafica', "
             "cv2.WINDOW_NORMAL); cv2.waitKey(1); cv2.destroyAllWindows()"],
            env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, check=False)
        return resultado.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def load_model_from_path(model_path: str | Path):
    """Comprueba que exista el archivo que permite reconocer vehículos antes de cargarlo.

    El programa no descarga uno nuevo al iniciar.
    """
    checkpoint = Path(model_path).expanduser().resolve()
    if not checkpoint.is_file() or checkpoint.suffix.lower() != ".pt":
        raise FileNotFoundError("El checkpoint .pt explicito no esta disponible.")
    from ultralytics import YOLO
    return YOLO(str(checkpoint))


def predict(model, frame: np.ndarray, imgsz: int, confidence: float):
    """Busca vehículos en la imagen y entrega el resultado junto con el tiempo que tardó."""
    iniciado = time.perf_counter()
    resultados = model.predict(source=frame, imgsz=imgsz, conf=confidence,
                              classes=list(VEHICLE_CLASSES), device="cpu", verbose=False)
    duracion = (time.perf_counter() - iniciado) * 1000
    resultado = resultados[0]
    return resultado, duracion, float(resultado.speed.get("inference", duracion))


def detections_from_result(result) -> list[VehicleDetection]:
    """Reúne los vehículos encontrados, su ubicación y qué tan segura fue cada detección."""
    if result.boxes is None or len(result.boxes) == 0:
        return []
    boxes = result.boxes.xyxy.cpu().tolist()
    classes = result.boxes.cls.cpu().tolist()
    confs = result.boxes.conf.cpu().tolist()
    detections = []
    for box, clase, confidence in zip(boxes, classes, confs):
        clase = int(clase)
        name = str(result.names.get(clase, clase) if isinstance(result.names, dict)
                   else result.names[clase])
        detections.append(VehicleDetection(tuple(float(x) for x in box), float(confidence), name))
    return detections
def draw_vehicle_detections(
    image: np.ndarray, detections: list[VehicleDetection]
) -> np.ndarray:
    """Dibuja un recuadro alrededor de cada vehículo y muestra qué tan segura fue la detección."""
    display = image.copy()
    height, width = display.shape[:2]
    color = (0, 220, 0)
    for detection in detections:
        x1, y1, x2, y2 = (
            int(round(value)) for value in detection.box_xyxy
        )
        x1 = min(max(x1, 0), width - 1)
        x2 = min(max(x2, 0), width - 1)
        y1 = min(max(y1, 0), height - 1)
        y2 = min(max(y2, 0), height - 1)
        if x2 <= x1 or y2 <= y1:
            continue

        cv2.rectangle(display, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
        label = f"{detection.class_name} {detection.confidence * 100:.0f}%"
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.55
        thickness = 2
        (text_width, text_height), baseline = cv2.getTextSize(
            label, font, scale, thickness
        )
        label_height = text_height + baseline + 8
        label_top = y2 + 4
        if label_top + label_height >= height:
            label_top = max(0, y1 - label_height - 4)
        label_left = min(x1, max(0, width - text_width - 8))
        label_right = min(width - 1, label_left + text_width + 8)
        label_bottom = min(height - 1, label_top + label_height)
        cv2.rectangle(
            display,
            (label_left, label_top),
            (label_right, label_bottom),
            color,
            cv2.FILLED,
        )
        cv2.putText(
            display,
            label,
            (label_left + 4, min(height - 1, label_top + text_height + 3)),
            font,
            scale,
            (0, 0, 0),
            thickness,
            cv2.LINE_AA,
        )
    return display


def zone_color(
    state: OccupancyState,
    *,
    ready: bool = True,
) -> tuple[int, int, int]:
    """Elige un color según el estado de ocupación de la zona."""
    if not ready:
        return (150, 150, 150)
    if state is OccupancyState.OCUPADO:
        return (0, 210, 0)
    if state is OccupancyState.CANDIDATO_OCUPADO:
        return (0, 165, 255)
    return (210, 210, 210)


def draw_zone_states(display, snapshots: tuple[ZoneSnapshot, ...], width: int,
                     height: int, compact_labels: bool = False, estados=None) -> None:
    """Dibuja los límites y nombres de las zonas sobre la imagen.

    Si no hay un panel de estados, también muestra el estado junto a cada zona.
    """
    for snapshot in snapshots:
        puntos = [(round(x * (width - 1)), round(y * (height - 1)))
                  for x, y in snapshot.polygon]
        color = zone_identity_color(snapshot.identifier)
        poligono = np.array(puntos, dtype="int32")
        cv2.polylines(display, [poligono], True, COLOR_FONDO, 5, cv2.LINE_AA)
        cv2.polylines(display, [poligono], True, color, 3, cv2.LINE_AA)
        texto = snapshot.identifier if estados is not None else (
            f"{snapshot.identifier}: {snapshot.state.value if snapshot.is_ready else 'DESCONOCIDO'}")
        dibujar_etiqueta(display, texto, poligono, color)


def _edad_compacta(segundos: float) -> str:
    segundos = max(0, int(segundos))
    if segundos < 60:
        return f"{segundos}s"
    if segundos < 3600:
        return f"{segundos // 60}m"
    if segundos < 86400:
        return f"{segundos // 3600}h"
    return f"{segundos // 86400}d"


def distribuir_panel(estados, alto: int, pagina: int = 0):
    """Distribuye las zonas en páginas de hasta dos columnas para poder verlas todas."""
    alto = max(alto, 100)
    filas = max(1, (alto - 35) // 46)
    capacidad = filas * 2
    paginas = max(1, math.ceil(len(estados) / capacidad))
    pagina = min(max(0, pagina), paginas - 1)
    inicio = pagina * capacidad
    visibles = estados[inicio:inicio + capacidad]
    columnas = max(1, math.ceil(len(visibles) / filas))
    entradas = []
    for indice, estado in enumerate(visibles):
        columna, fila = divmod(indice, filas)
        primer_texto = f"{estado.snapshot.identifier}: {estado.efectivo}"
        segundo_texto = ("Ultimo: sin dato" if estado.ultimo is None else
                         f"Ultimo: {estado.ultimo} ({_edad_compacta(estado.antiguedad)})")
        entradas.append((columna * 260 + 10, 52 + fila * 46,
                         primer_texto, segundo_texto,
                         zone_identity_color(estado.snapshot.identifier)))
    return alto, columnas, pagina, paginas, inicio, entradas


def _texto_ajustado(imagen, texto: str, posicion: tuple[int, int], color, max_ancho: int) -> None:
    escala = 0.46
    ancho = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, escala, 1)[0][0]
    if ancho > max_ancho:
        escala *= max_ancho / ancho
    cv2.putText(imagen, texto, posicion, cv2.FONT_HERSHEY_SIMPLEX,
                escala, color, 1, cv2.LINE_AA)


def renderizar(frame, detecciones, estados, mensaje: str, pagina: int = 0,
               *, fuente: str = "Fuente sin especificar", ayuda: str = "Q: cerrar"):
    imagen = draw_vehicle_detections(frame, detecciones)
    draw_zone_states(imagen, tuple(e.snapshot for e in estados), imagen.shape[1],
                     imagen.shape[0], estados=estados)
    alto, columnas, pagina, paginas, inicio, entradas = distribuir_panel(
        estados, imagen.shape[0], pagina)
    ancho_imagen = imagen.shape[1]
    if paginas > 1:
        ayuda += " | A/[ anterior | D/] siguiente"
    color_mensaje = COLOR_AVISO if mensaje.startswith("NO_VERIFICABLE:") else COLOR_PRINCIPAL
    salida = componer_marco(imagen, columnas, "MONITOR", fuente,
                            [(ayuda, COLOR_SECUNDARIO), (mensaje, color_mensaje)])
    encabezado = (f"Zonas {inicio + 1}-{inicio + len(entradas)}/{len(estados)}"
                  if entradas else "Zonas 0/0")
    if paginas > 1:
        encabezado += f" | {pagina + 1}/{paginas}"
    _texto_ajustado(salida, encabezado, (ancho_imagen + 10, ALTO_CABECERA + 22),
                    COLOR_PRINCIPAL, 240)
    colores_estado = {"LIBRE": (128, 200, 78), "OCUPADO": (100, 105, 240),
                      "NO_VERIFICABLE": COLOR_AVISO}
    for entrada, estado in zip(entradas, estados[inicio:inicio + len(entradas)]):
        x, y, _, _, color = entrada
        x += ancho_imagen
        y += ALTO_CABECERA
        cv2.rectangle(salida, (x, y - 10), (x + 5, y - 3), color, cv2.FILLED)
        _texto_ajustado(salida, estado.snapshot.identifier, (x + 12, y), COLOR_PRINCIPAL, 75)
        estado_ancho = cv2.getTextSize(estado.efectivo, cv2.FONT_HERSHEY_SIMPLEX, 0.46, 1)[0][0]
        _texto_ajustado(salida, estado.efectivo, (x + max(92, 240 - estado_ancho), y),
                        colores_estado.get(estado.efectivo, COLOR_SECUNDARIO), 148)
        if estado.ultimo is None:
            historial = "Sin dato confirmado"
        elif estado.antiguedad is None:
            historial = f"Ultimo: {estado.ultimo}"
        elif estado.ultimo == estado.efectivo:
            historial = f"Confirmado hace {_edad_compacta(estado.antiguedad)}"
        else:
            historial = f"Ultimo: {estado.ultimo} ({_edad_compacta(estado.antiguedad)})"
        _texto_ajustado(salida, historial, (x + 12, y + 17), COLOR_SECUNDARIO, 228)
        cv2.line(salida, (x, y + 27), (x + 238, y + 27), COLOR_SEPARADOR, 1)
    return salida


def ventana_cerrada() -> bool:
    try:
        return cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True


_pagina_panel = 0


def presentar(frame, detecciones, estado: EstadoLocal, mensaje: str, headless: bool,
              *, fuente: str = "Fuente sin especificar") -> bool:
    global _pagina_panel
    if headless:
        return True
    estados = estado.estados()
    _, _, pagina, paginas, _, _ = distribuir_panel(estados, frame.shape[0], _pagina_panel)
    _pagina_panel = pagina
    _mostrar_interfaz(renderizar(frame, detecciones, estados, mensaje, pagina, fuente=fuente))
    tecla = cv2.waitKey(1) & 0xff
    if tecla in (ord("["), ord("a"), ord("A")):
        _pagina_panel = max(0, pagina - 1)
    elif tecla in (ord("]"), ord("d"), ord("D")):
        _pagina_panel = min(paginas - 1, pagina + 1)
    return tecla not in (ord("q"), ord("Q")) and not ventana_cerrada()


class MedidorFPS:
    """Calcula cuántas imágenes se han revisado por segundo durante los últimos momentos."""

    def __init__(self, ventana: float = 2.5):
        if ventana <= 0:
            raise ValueError("La ventana de FPS debe ser positiva.")
        self.ventana = ventana
        self.muestras = deque()

    def reiniciar(self):
        self.muestras.clear()

    def registrar(self, instante: float | None = None) -> float | None:
        ahora = time.monotonic() if instante is None else instante
        self.muestras.append(ahora)
        while self.muestras and self.muestras[0] < ahora - self.ventana:
            self.muestras.popleft()
        if len(self.muestras) < 2:
            return None
        duracion = self.muestras[-1] - self.muestras[0]
        return (len(self.muestras) - 1) / duracion if duracion > 0 else None


def inicializar_estado(ruta: Path) -> EstadoLocal:
    """Carga las zonas guardadas y prepara su estado para actualizarlo con cada imagen."""
    if not ruta.is_file():
        raise FileNotFoundError("No existe la calibracion solicitada; calibre antes de monitorear.")
    zonas = load_zones(ruta)
    if not zonas:
        raise ValueError("La calibracion no contiene zonas confirmadas.")
    return EstadoLocal(zonas)


def validar_calibracion_permanente(ruta: Path, tipo_fuente: str, fuente: str | Path) -> None:
    """Comprueba que las zonas guardadas y el tamaño de imagen correspondan al origen elegido."""

    from calibracion_zonas import cargar_calibracion

    datos = json.loads(ruta.read_text(encoding="utf-8"))
    metadata = datos.get("metadata") if isinstance(datos, dict) else None
    if not isinstance(metadata, dict):
        raise ValueError("La calibracion no incluye metadatos canonicos.")
    ancho = metadata.get("source_width")
    alto = metadata.get("source_height")
    if (not isinstance(ancho, int) or isinstance(ancho, bool)
            or not isinstance(alto, int) or isinstance(alto, bool)):
        raise ValueError("La calibracion no incluye dimensiones exactas.")
    calibracion = cargar_calibracion(ruta, ancho, alto)
    identificadores = set(calibracion.zonas)
    if len(set(calibracion.vision_zone_ids.values())) != len(identificadores):
        raise ValueError("Cada zona requiere un UUID Vision unico.")
    verificar_vinculo(ruta, tipo_fuente, fuente, ancho, alto)


def esperar_calibracion_valida(
    ruta: Path,
    tipo_fuente: str = "http",
    fuente: str | Path | None = None,
    dispositivo: str | Path | None = None,
    pausa: float = 2.0,
) -> bool:
    """Espera hasta confirmar las zonas y el origen elegido antes de abrir la cámara."""

    if not math.isfinite(pausa) or pausa <= 0:
        raise ValueError("El intervalo de espera debe ser positivo.")
    while True:
        try:
            fuente_actual = fuente
            if fuente_actual is None:
                fuente_actual = (
                    resolver_url_http(None)
                    if tipo_fuente == "http"
                    else validar_dispositivo(dispositivo)
                )
            validar_calibracion_permanente(ruta, tipo_fuente, fuente_actual)
            print("Calibracion valida; inicia Vision.", flush=True)
            return True
        except (FileNotFoundError, OSError, ValueError) as error:
            print(
                f"Vision espera calibracion/fuente valida ({error.__class__.__name__}).",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(pausa)


def inferir(model, frame, args, guardia: FrameQualityGuard, estado: EstadoLocal,
            *, simulacion: bool = False, confirmar=None, momento_captura=None):
    """Busca vehículos en la imagen y actualiza las zonas solo con resultados vigentes.

    Si la imagen no sirve, falla el reconocimiento o cambia la conexión mientras se revisa,
    descarta el resultado y retira cualquier actualización pendiente de envío.
    """
    publicador = getattr(args, "publicador", None)
    ahora_monotono = time.monotonic()
    momento_observacion = ahora_monotono if momento_captura is None else momento_captura
    observado_en = datetime.now(timezone.utc) - timedelta(
        seconds=max(0.0, ahora_monotono - momento_observacion))
    valido, motivo = guardia.inspect(frame, allow_repeated=simulacion)
    if not valido:
        motivos = {"repeated frame": "repetido sin frescura",
                   "near-black frame": "escena casi oscura",
                   "black frame": "escena negra"}
        estado.invalidar(motivos.get(motivo, str(motivo)))
        if publicador is not None:
            publicador.invalidar()
        return [], None, None
    try:
        resultado, duracion, _ = predict(model, frame, args.imgsz, args.conf)
        detecciones = detections_from_result(resultado)
    except Exception as error:
        estado.invalidar(f"inferencia fallida: {error.__class__.__name__}")
        if publicador is not None:
            publicador.invalidar()
        return [], None, None
    def actualizar():
        estados = estado.avanzar(detecciones, frame.shape[1], frame.shape[0])
        if publicador is not None:
            publicador.ofrecer(estados, observado_en=observado_en,
                               momento_observacion=momento_observacion)
    if confirmar is not None and not confirmar(actualizar):
        estado.invalidar("inferencia desactualizada o fuente interrumpida")
        if publicador is not None:
            publicador.invalidar()
        return [], None, None
    if confirmar is None:
        actualizar()
    return detecciones, duracion, resultado


def ejecutar_imagen(args, model, estado: EstadoLocal) -> int:
    """Revisa una imagen fija después de comprobar que corresponde a las zonas guardadas."""
    frame = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("No se pudo leer la imagen seleccionada.")
    verificar_vinculo(args.zones, "image", args.image, frame.shape[1], frame.shape[0])
    detecciones, duracion, resultado = inferir(model, frame, args, FrameQualityGuard(), estado,
                                               simulacion=True)
    if resultado is None:
        raise RuntimeError(f"No se pudo inferir la imagen: {estado.motivo}")
    print(f"Imagen: {len(detecciones)} detecciones; inferencia {duracion:.1f} ms.")
    for deteccion in detecciones:
        print(f"Vehiculo: {deteccion.class_name}, confianza={deteccion.confidence:.3f}.")
    if not args.headless:
        _crear_ventana()
        while presentar(frame, detecciones, estado, "IMAGEN: una sola muestra", False,
                        fuente="Fuente: imagen fija"):
            pass
    return 0


def ejecutar_simulacion(args, model, estado: EstadoLocal) -> int:
    """Recorre las imágenes de una simulación para observar cómo cambia la ocupación."""
    secuencia = build_simulation_sequence(args.simulation_dir, args.frame_duration,
                                          args.frame_duration_override)
    guardia = FrameQualityGuard()
    total = 0
    inicio = time.perf_counter()
    if not args.headless:
        _crear_ventana()
    while True:
        for escena in secuencia:
            frame = cv2.imread(str(escena.path), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError(f"No se pudo leer la escena {escena.path.name}.")
            verificar_vinculo(args.zones, "simulation", args.simulation_dir,
                              frame.shape[1], frame.shape[0])
            inicio_escena = time.monotonic()
            ciclos = 0
            print(f"SIMULACION: {escena.path.name}.", flush=True)
            # Cada escena se revisa suficientes veces aunque el equipo tarde más de lo previsto.
            while ciclos < 4 or time.monotonic() - inicio_escena < escena.duration_seconds:
                inicio_ciclo = time.monotonic()
                detecciones, duracion, resultado = inferir(model, frame, args, guardia, estado,
                                                           simulacion=True)
                if resultado is None:
                    raise RuntimeError(f"Fallo de simulacion: {estado.motivo}")
                ciclos += 1
                total += 1
                if not presentar(frame, detecciones, estado,
                                 f"SIMULACION {escena.path.name} | ciclo {ciclos}", args.headless,
                                 fuente="Fuente: simulacion"):
                    return 0
                espera = 1.0 / args.playback_fps - (time.monotonic() - inicio_ciclo)
                if espera > 0:
                    if args.headless:
                        time.sleep(espera)
                    else:
                        limite = time.monotonic() + espera
                        while time.monotonic() < limite:
                            if not presentar(frame, detecciones, estado,
                                             f"SIMULACION {escena.path.name} | ciclo {ciclos}", False,
                                             fuente="Fuente: simulacion"):
                                return 0
                            time.sleep(min(0.02, max(0, limite - time.monotonic())))
            print(f"{escena.path.name}: ciclos={ciclos}, detecciones={len(detecciones)}, "
                  + ", ".join(f"{e.snapshot.identifier}={e.efectivo}" for e in estado.estados()),
                  flush=True)
        if args.no_loop:
            break
    transcurrido = max(time.perf_counter() - inicio, 1e-6)
    print(f"Simulacion completa: {len(secuencia)} escenas, {total} inferencias, "
          f"{total / transcurrido:.2f} FPS CPU.")
    return 0


def _raton_en_marco(editor, evento, x, y, flags, datos, cola=None) -> None:
    """Ajusta la posición del ratón y permite terminar de mover un punto fuera de la imagen."""
    if editor is None:
        return
    if (cola is not None and evento == cv2.EVENT_LBUTTONDOWN
            and editor.control.arrastre is None and editor.antes_arrastre is None):
        tecla = editor.tecla_de_boton(x, y)
        if tecla is not None:
            cola.append((editor, tecla))
            return
    y_imagen = y - ALTO_CABECERA
    dentro = 0 <= x < editor.ancho and 0 <= y_imagen < editor.alto
    arrastrando = editor.control.arrastre is not None
    terminando = evento == cv2.EVENT_LBUTTONUP and editor.antes_arrastre is not None
    if dentro or ((arrastrando and evento in (cv2.EVENT_MOUSEMOVE, cv2.EVENT_LBUTTONUP))
                  or terminando):
        editor.raton(evento, x, y_imagen, flags, datos)


def _tecla_calibracion(tecla_fisica, editor, cola):
    if tecla_fisica != 255:
        return tecla_fisica
    while cola:
        destinatario, tecla = cola.popleft()
        if destinatario is editor:
            return tecla
    return 255


def ejecutar_directo(args, model, estado: EstadoLocal) -> int:
    """Lee imágenes de la cámara o dirección elegida y actualiza el estado de las zonas.

    Si se pierde la conexión o la imagen deja de ser reciente, indica que no puede
    confirmar la ocupación y evita enviar información desactualizada.
    """
    url = resolver_url_http(args.http_url) if args.source == "http" else None
    identidad = url if args.source == "http" else validar_dispositivo(args.device)
    capturador = CapturadorReciente(args.source, url, args.device)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    guardia = FrameQualityGuard()
    generacion = 0
    dimensiones = None
    vinculo_valido = False
    revision = -1
    motivo_impreso = None
    medidor_fps = MedidorFPS()
    mensaje = "NO_VERIFICABLE: conectando"
    detecciones = []
    max_edad = getattr(args, "max_frame_age", 2.0)
    carga_modelo = None
    permanente = bool(getattr(args, "permanente", False))
    modo_local = bool(getattr(args, "local_desktop", False)) or permanente
    editor = None
    edicion = None
    control = None
    ventana_activa = False
    display_conectado = None
    coordenadas_raton = {"ajuste": None}
    cola_calibracion = deque()
    if permanente:
        from control_interfaz_local import ControlInterfaz
        from edicion_permanente import EdicionPermanente
        control = ControlInterfaz(args.control_socket)
        control.iniciar()
        edicion = EdicionPermanente(args, identidad)

    def verificar_fuente(frame_actual):
        if permanente:
            from aplicacion_local import validar_archivo_local
            validar_archivo_local(args.zones, args.source, identidad, frame_actual.shape[:2], recuperar=False)
        else:
            verificar_vinculo(args.zones, args.source, identidad,
                              frame_actual.shape[1], frame_actual.shape[0])
    guardia_calibracion = FrameQualityGuard() if modo_local else None
    calidad_calibracion = False
    if not args.headless:
        _crear_ventana()
        if modo_local:
            def procesar_raton(evento, x, y, flags, datos):
                x, y = _coordenadas_raton_a_interfaz(x, y, coordenadas_raton["ajuste"])
                _raton_en_marco(editor, evento, x, y, flags, datos, cola_calibracion)
            cv2.setMouseCallback(WINDOW_TITLE, procesar_raton)
    capturador.iniciar()
    try:
        if model is _CARGAR_MODELO_EN_VIVO:
            # La cámara y la ventana siguen funcionando mientras se prepara el reconocimiento.
            carga_modelo = {"terminado": threading.Event(), "modelo": None, "error": None}
            def cargar_modelo():
                try:
                    carga_modelo["modelo"] = load_model_from_path(args.model)
                except Exception as error:
                    carga_modelo["error"] = error.__class__.__name__
                finally:
                    carga_modelo["terminado"].set()
            threading.Thread(target=cargar_modelo, name="vision-carga-modelo", daemon=True).start()
        while True:
            if permanente:
                pedido = control.siguiente()
                if pedido is not None:
                    aceptado = False
                    display = pedido["display"]
                    if not pedido["cancelado"].is_set() and (display_conectado is None or display == display_conectado):
                        if ventana_activa:
                            aceptado = True
                        elif probar_grafica_aislada(display) and not pedido["cancelado"].is_set():
                            os.environ["DISPLAY"] = display
                            _crear_ventana()
                            def raton_permanente(evento, x, y, flags, datos):
                                x, y = _coordenadas_raton_a_interfaz(
                                    x, y, coordenadas_raton["ajuste"],
                                )
                                _raton_en_marco(
                                    edicion.editor, evento, x, y, flags, datos, cola_calibracion,
                                )
                            cv2.setMouseCallback(WINDOW_TITLE, raton_permanente)
                            ventana_activa = True
                            args.grafica_inicializada = True
                            display_conectado = display
                            aceptado = True
                    control.responder(pedido, aceptado)
                editor = edicion.editor
            muestra = capturador.esperar(revision, 0.1)
            nueva = muestra.revision != revision
            revision = muestra.revision
            vigente = (muestra.estado == "conectada" and muestra.cuadro is not None
                       and muestra.momento is not None
                       and 0 <= time.monotonic() - muestra.momento <= max_edad)
            fuente_visible = f"Fuente camara: {muestra.estado}"
            if muestra.estado == "conectada" and not vigente:
                fuente_visible += " | cuadro sin frescura"
            if editor is not None:
                editor.actualizar_fuente(muestra, max_edad)
            if not vigente:
                medidor_fps.reiniciar()
                motivo = ("fuente interrumpida" if muestra.estado != "conectada"
                          else "cuadro sin frescura")
                estado.invalidar(motivo)
                if getattr(args, "publicador", None) is not None:
                    args.publicador.invalidar()
                mensaje = f"NO_VERIFICABLE: {motivo}"
                detecciones = []
                if motivo != motivo_impreso:
                    print(f"{mensaje}; se espera la misma fuente.", flush=True)
                    motivo_impreso = motivo
            elif nueva:
                frame = muestra.cuadro
                if muestra.generacion != generacion:
                    medidor_fps.reiniciar()
                    if modo_local:
                        guardia_calibracion = FrameQualityGuard()
                    estado.invalidar("fuente reconectada")
                    if getattr(args, "publicador", None) is not None:
                        args.publicador.invalidar()
                    vinculo_valido = False
                    if estado.zones:
                        try:
                            verificar_fuente(frame)
                            vinculo_valido = True
                        except (OSError, ValueError):
                            estado.invalidar("fuente o formato incompatible con la calibracion")
                    generacion = muestra.generacion
                    dimensiones = frame.shape[:2]
                    print(f"Fuente conectada: {muestra.backend}; "
                          f"{frame.shape[1]}x{frame.shape[0]}.", flush=True)
                if modo_local:
                    calidad_calibracion = guardia_calibracion.inspect(frame)[0]
                if frame.shape[:2] != dimensiones:
                    vinculo_valido = False
                    if estado.zones:
                        try:
                            verificar_fuente(frame)
                            vinculo_valido = True
                        except (OSError, ValueError):
                            estado.invalidar("fuente o formato incompatible con la calibracion")
                    dimensiones = frame.shape[:2]
                motivo_impreso = None
                if editor is not None or (permanente and edicion.activa):
                    estado.invalidar("calibracion local en curso")
                    detecciones, duracion, resultado = [], None, None
                elif carga_modelo is not None and not carga_modelo["terminado"].is_set():
                    estado.invalidar("modelo aun no disponible")
                    detecciones, duracion, resultado = [], None, None
                elif carga_modelo is not None and carga_modelo["error"] is not None:
                    estado.invalidar("modelo no disponible")
                    detecciones, duracion, resultado = [], None, None
                elif not vinculo_valido:
                    estado.invalidar("sin calibracion valida para la fuente")
                    detecciones, duracion, resultado = [], None, None
                else:
                    if carga_modelo is not None:
                        model = carga_modelo["modelo"]
                        carga_modelo = None
                        print("Modelo cargado explicitamente; inferencia en CPU.", flush=True)
                    detecciones, duracion, resultado = inferir(
                        model, frame, args, guardia, estado,
                        momento_captura=muestra.momento,
                        confirmar=lambda actualizar: capturador.aplicar_si_vigente(
                            muestra, max_edad, actualizar),
                    )
                if resultado is not None:
                    fps = medidor_fps.registrar()
                    ritmo = "--" if fps is None else f"{fps:.2f}"
                    mensaje = f"CPU: {ritmo} FPS | inferencia {duracion:.0f} ms"
                else:
                    medidor_fps.reiniciar()
                    mensaje = f"NO_VERIFICABLE: {estado.motivo}"
            if permanente:
                if not ventana_activa:
                    continue
                if edicion.activa:
                    pantalla = edicion.editor.pantalla(
                        modo_permanente=True,
                        sincronizacion_pendiente=edicion.paso_pendiente is not None,
                    )
                    _mostrar_interfaz(pantalla, coordenadas_raton)
                else:
                    global _pagina_panel
                    estados = estado.estados()
                    _, _, _pagina_panel, paginas, _, _ = distribuir_panel(
                        estados, frame.shape[0], _pagina_panel)
                    aviso = ("C: calibrar | Q/X: cerrar ventana" if args.publicador is not None
                             else "C: calibrar | Java sin publicacion | Q/X: cerrar ventana")
                    pantalla = renderizar(frame, detecciones, estados, mensaje, _pagina_panel,
                                         fuente=fuente_visible, ayuda=aviso)
                    _mostrar_interfaz(pantalla, coordenadas_raton)
                tecla = cv2.waitKey(1) & 0xff
                cerrar_ventana = ventana_cerrada() or tecla in (
                    ord("q"), ord("Q"), ord("x"), ord("X"),
                )
                if cerrar_ventana:
                    cola_calibracion.clear()
                    if edicion.activa:
                        edicion.cerrar()
                    try:
                        cv2.destroyWindow(WINDOW_TITLE)
                    except cv2.error:
                        pass
                    ventana_activa = False
                    guardia = FrameQualityGuard()
                    medidor_fps.reiniciar()
                    continue
                if not edicion.activa:
                    cola_calibracion.clear()
                if edicion.activa:
                    tecla = _tecla_calibracion(tecla, edicion.editor, cola_calibracion)
                    accion = edicion.tecla(tecla, capturador, max_edad)
                    if accion in ("actualizar", "cancelada"):
                        cola_calibracion.clear()
                        if accion == "actualizar":
                            estado = inicializar_estado(args.zones)
                            generacion = 0
                            vinculo_valido = False
                        else:
                            estado.invalidar("calibracion cancelada")
                        guardia = FrameQualityGuard()
                        guardia_calibracion = FrameQualityGuard()
                        medidor_fps.reiniciar()
                        detecciones = []
                        mensaje = "NO_VERIFICABLE: retomando monitoreo"
                elif tecla in (ord("["), ord("a"), ord("A")):
                    _pagina_panel = max(0, _pagina_panel - 1)
                elif tecla in (ord("]"), ord("d"), ord("D")):
                    _pagina_panel = min(paginas - 1, _pagina_panel + 1)
                elif tecla in (ord("c"), ord("C")):
                    if not vigente or not vinculo_valido or not calidad_calibracion:
                        mensaje = "NO_VERIFICABLE: se requiere fuente y calibracion validas"
                    elif not edicion.iniciar(capturador, max_edad):
                        mensaje = edicion.mensaje
                    else:
                        estado.invalidar("calibracion en curso")
                        guardia = FrameQualityGuard()
                        medidor_fps.reiniciar()
                        detecciones = []
                continue
            if not modo_local:
                if not presentar(frame, detecciones, estado, mensaje, args.headless,
                                 fuente=fuente_visible):
                    return 0
                continue

            if editor is not None:
                _mostrar_interfaz(editor.pantalla(), coordenadas_raton)
            else:
                estados = estado.estados()
                _, _, _pagina_panel, paginas, _, _ = distribuir_panel(
                    estados, frame.shape[0], _pagina_panel)
                pantalla = renderizar(frame, detecciones, estados,
                                     mensaje, _pagina_panel, fuente=fuente_visible,
                                     ayuda="C: calibrar | Q: cerrar | Sin sincronizacion con Java")
                _mostrar_interfaz(pantalla, coordenadas_raton)
            tecla = cv2.waitKey(1) & 0xff
            if tecla in (ord("q"), ord("Q")) or ventana_cerrada():
                cola_calibracion.clear()
                return 0
            if editor is None:
                cola_calibracion.clear()
                if tecla in (ord("["), ord("a"), ord("A")):
                    _pagina_panel = max(0, _pagina_panel - 1)
                elif tecla in (ord("]"), ord("d"), ord("D")):
                    _pagina_panel = min(paginas - 1, _pagina_panel + 1)
                elif tecla in (ord("c"), ord("C")):
                    if not vigente or not vinculo_valido:
                        mensaje = "NO_VERIFICABLE: no hay fuente valida para calibrar"
                        continue
                    if not calidad_calibracion:
                        mensaje = "NO_VERIFICABLE: cuadro sin calidad para calibrar"
                        continue
                    from aplicacion_local import EditorLocal
                    creado = []
                    try:
                        aceptado = capturador.aplicar_si_vigente(
                            muestra, max_edad,
                            lambda: creado.append(EditorLocal(args.zones, args.source, identidad, muestra)),
                        )
                    except (OSError, ValueError) as error:
                        mensaje = f"No se abrio calibracion: {error}"
                        continue
                    if aceptado:
                        editor = creado[0]
                        estado.invalidar("calibracion local en curso")
                        guardia = FrameQualityGuard()
                        medidor_fps.reiniciar()
                        detecciones = []
                    else:
                        mensaje = "NO_VERIFICABLE: la fuente cambio al iniciar calibracion"
            else:
                tecla = _tecla_calibracion(tecla, editor, cola_calibracion)
                accion = editor.tecla(tecla)
                if accion == "guardar":
                    resultado_guardado = editor.guardar(capturador, max_edad)
                    if resultado_guardado is None:
                        continue
                    if resultado_guardado == "guardada":
                        estado = inicializar_estado(args.zones)
                        print("Calibracion LOCAL guardada; no se sincronizo con Java.", flush=True)
                    else:
                        estado.invalidar("calibracion sin cambios")
                        print("Calibracion sin cambios; se conserva la revision.", flush=True)
                    editor = None
                    cola_calibracion.clear()
                    guardia = FrameQualityGuard()
                    guardia_calibracion = FrameQualityGuard()
                    medidor_fps.reiniciar()
                    detecciones = []
                    mensaje = "NO_VERIFICABLE: retomando monitoreo local"
                elif accion == "cancelar":
                    editor = None
                    cola_calibracion.clear()
                    estado.invalidar("calibracion cancelada")
                    guardia = FrameQualityGuard()
                    guardia_calibracion = FrameQualityGuard()
                    medidor_fps.reiniciar()
                    detecciones = []
                    mensaje = "NO_VERIFICABLE: retomando monitoreo local"
    finally:
        if permanente:
            if edicion.activa:
                edicion.permitir_publicar = False
                edicion.cerrar()
            control.cerrar()
        if capturador.detener():
            print("Captura liberada.", flush=True)
        else:
            print("La captura no termino dentro del limite de cierre; "
                  "el contenedor debe detenerse.", file=sys.stderr, flush=True)


def run(args) -> int:
    """Prepara las zonas y el envío de información, y elige qué imágenes revisar.

    Al finalizar, detiene los envíos y cierra la ventana cuando corresponde.
    """
    global _pagina_panel
    inicio_proceso = datetime.now(timezone.utc)
    _pagina_panel = 0
    publicador = None
    args.publicador = None
    args.configuracion_vision = None
    args.grafica_inicializada = False
    try:
        sintetica = bool(args.image or args.simulation_dir)
        publicacion_solicitada = bool(getattr(args, "publish_java", False))
        modo_local = bool(getattr(args, "local_desktop", False))
        if getattr(args, "permanente", False):
            from estado_calibracion import seleccion_activa
            args.ruta_productiva = args.zones
            args.zones, args.seleccion_segura = seleccion_activa(args.zones, args.local_proposal)
            if not args.seleccion_segura:
                print("Publicacion detenida: seleccion LOCAL invalida.", file=sys.stderr, flush=True)
        if modo_local:
            if publicacion_solicitada or args.headless or sintetica:
                raise ValueError("LOCAL requiere captura con ventana y no admite publicacion Java.")
            from aplicacion_local import validar_archivo_local, validar_ruta_local
            validar_ruta_local(getattr(args, "local_calibration_dir", None), args.zones)
            fuente = (resolver_url_http(args.http_url) if args.source == "http"
                      else validar_dispositivo(args.device))
            validar_archivo_local(args.zones, args.source, fuente)
        try:
            estado = inicializar_estado(args.zones)
        except (OSError, ValueError):
            if sintetica or not publicacion_solicitada:
                raise
            estado = EstadoLocal(())
            print("Calibracion no disponible; la ocupacion no es verificable.",
                  file=sys.stderr, flush=True)
        if sintetica:
            model = load_model_from_path(args.model)
            print("Modelo cargado explicitamente; inferencia en CPU.", flush=True)
        else:
            model = _CARGAR_MODELO_EN_VIVO
        publicar_sintetica = os.environ.get("VISION_SIMULACION_JAVA") == "1"
        puede_publicar = publicacion_solicitada and (not sintetica or publicar_sintetica)
        configuracion = None
        if puede_publicar:
            try:
                permanente = bool(getattr(args, "permanente", False))
                configuracion = cargar_configuracion(args.zones, estado.zones)
                if configuracion is not None:
                    args.configuracion_vision = configuracion
                    habilitar = True
                    if permanente:
                        from aplicacion_local import validar_archivo_local
                        from estado_calibracion import activaciones_pendientes
                        fuente = (resolver_url_http(args.http_url) if args.source == "http"
                                  else validar_dispositivo(args.device))
                        try:
                            validar_archivo_local(args.zones, args.source, fuente, recuperar=False)
                            habilitar = (args.seleccion_segura
                                         and not activaciones_pendientes(args.ruta_productiva.parent))
                        except (OSError, ValueError):
                            habilitar = False
                        if not habilitar:
                            print("Publicacion detenida: par activo invalido o activacion pendiente.",
                                  file=sys.stderr, flush=True)
                    if habilitar:
                        publicador = PublicadorVision(configuracion, iniciada_en=inicio_proceso)
                        publicador.iniciar()
                        args.publicador = publicador
            except ValueError as error:
                print(f"Publicacion Vision no disponible: {error} La deteccion local continua.",
                      file=sys.stderr, flush=True)
        elif not publicacion_solicitada:
            print("Publicacion Java deshabilitada; requiere --publish-java.", flush=True)
        elif os.environ.get("VISION_JAVA_URL"):
            print("Imagen o simulacion autonoma: requiere VISION_SIMULACION_JAVA=1.", flush=True)
        if args.image:
            return ejecutar_imagen(args, model, estado)
        if args.simulation_dir:
            return ejecutar_simulacion(args, model, estado)
        return ejecutar_directo(args, model, estado)
    except KeyboardInterrupt:
        print("Vision detenida.")
        return 0
    except (OSError, RuntimeError, ValueError, cv2.error) as error:
        print(f"Vision no pudo continuar ({error.__class__.__name__}): {error}", file=sys.stderr)
        return 1
    finally:
        if args.publicador is not None:
            args.publicador.detener()
        if not getattr(args, "permanente", False) or args.grafica_inicializada:
            cv2.destroyAllWindows()


def main() -> int:
    def detener(_senal, _marco):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, detener)
    args = parse_args()
    try:
        if args.wait_for_calibration:
            esperar_calibracion_valida(args.zones, args.source, args.http_url, args.device)
        return run(args)
    except KeyboardInterrupt:
        print("Vision detenida mientras esperaba calibracion.", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
