"""Permite dibujar y ajustar en la imagen las zonas de los cajones."""

from __future__ import annotations

import argparse
import colorsys
import copy
import json
import os
import sys
import signal
import tempfile
import time
from pathlib import Path

os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")
import cv2
import numpy as np

from calibracion_zonas import (
    CalibracionZonas,
    advertencias_solapamiento,
    cargar_calibracion,
    guardar_calibracion,
)
from calibracion_automatica import ErrorCalibracionAutomatica, generar_candidato_automatico
from capture import CapturadorReciente, resolver_url_http, validar_dispositivo
from temporal_validation import FrameQualityGuard, ParkingZone
from configuracion_local import (
    _comprobar_guardado_propio,
    _sidecar_compatible,
    finalizar_guardado_pendiente,
    identidad_fuente,
    preparar_guardado_calibracion,
    guardar_vinculo,
    ruta_vinculo,
    verificar_sin_guardado_pendiente,
    verificar_vinculo,
)

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_ZONES_PATH = Path("/data/config/zones.json")
TITULO_VENTANA = "Smart Parking Vision - Calibracion de zonas"
RADIO_VERTICE_PX = 12
PALETA_ZONAS = (
    (255, 180, 0),
    (0, 220, 255),
    (255, 100, 220),
    (120, 255, 120),
    (255, 120, 100),
    (180, 120, 255),
    (80, 220, 180),
    (230, 230, 230),
)
COLOR_SELECCION = (0, 255, 255)
COLOR_PENDIENTE = (0, 165, 255)
COLOR_INVALIDO = (0, 0, 255)
COLOR_TEXTO = (255, 255, 255)

ALTO_CABECERA = 56
ANCHO_PANEL = 260
COLOR_FONDO = (18, 18, 18)
COLOR_PANEL = (28, 28, 28)
COLOR_SEPARADOR = (56, 56, 56)
COLOR_PRINCIPAL = (238, 238, 238)
COLOR_SECUNDARIO = (170, 170, 170)
COLOR_AVISO = (70, 190, 235)


def zone_identity_color(identifier: str) -> tuple[int, int, int]:
    """Asigna el mismo color a una zona cada vez que se muestra."""
    if not identifier.startswith("C") or not identifier[1:].isdigit():
        return (150, 150, 150)
    numero = int(identifier[1:])
    if numero < 1:
        return (150, 150, 150)
    matiz = ((numero - 1) * 137.508) % 360 / 360
    rojo, verde, azul = colorsys.hls_to_rgb(matiz, 0.56, 0.78)
    return round(azul * 255), round(verde * 255), round(rojo * 255)


def _dividir_texto(texto: str, ancho: int) -> list[str]:
    """Divide el texto para que quepa en el espacio sin hacerlo más pequeño."""
    fuente, escala = cv2.FONT_HERSHEY_SIMPLEX, 0.5

    def cabe(valor: str) -> bool:
        return cv2.getTextSize(valor, fuente, escala, 1)[0][0] <= ancho

    lineas, actual = [], ""
    for palabra in texto.split():
        while palabra and not cabe(palabra):
            if actual:
                lineas.append(actual)
                actual = ""
            limite = 1
            while limite < len(palabra) and cabe(palabra[:limite + 1]):
                limite += 1
            lineas.append(palabra[:limite])
            palabra = palabra[limite:]
        if not palabra:
            continue
        candidato = f"{actual} {palabra}" if actual else palabra
        if actual and not cabe(candidato):
            lineas.append(actual)
            actual = palabra
        else:
            actual = candidato
    if actual:
        lineas.append(actual)
    return lineas or [""]


def componer_marco(imagen: np.ndarray, columnas: int, modo: str,
                    fuente: str, lineas: list[tuple[str, tuple[int, int, int]]]) -> np.ndarray:
    """Añade espacio para títulos y mensajes sin cambiar el tamaño de la imagen."""
    alto, ancho = imagen.shape[:2]
    ancho_total = ancho + ANCHO_PANEL * columnas
    lineas_ajustadas = [
        (fragmento, color)
        for texto, color in lineas
        for fragmento in _dividir_texto(texto, max(1, ancho_total - 24))
    ]
    alto_barra = max(80, 16 + 24 * len(lineas_ajustadas))
    alto_cuerpo = max(alto, 100)
    salida = np.full((ALTO_CABECERA + alto_cuerpo + alto_barra, ancho_total, 3),
                     COLOR_FONDO, dtype=np.uint8)
    salida[ALTO_CABECERA:ALTO_CABECERA + alto,
           ancho:ancho_total] = COLOR_PANEL
    salida[ALTO_CABECERA:ALTO_CABECERA + alto, :ancho] = imagen
    cv2.line(salida, (0, ALTO_CABECERA - 1), (ancho_total - 1, ALTO_CABECERA - 1),
             COLOR_SEPARADOR, 1)
    pie = ALTO_CABECERA + alto_cuerpo
    cv2.line(salida, (0, pie), (ancho_total - 1, pie), COLOR_SEPARADOR, 1)
    cv2.putText(salida, "Smart Parking Vision", (12, 24), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, COLOR_PRINCIPAL, 1, cv2.LINE_AA)
    (ancho_modo, _), _ = cv2.getTextSize(modo, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.putText(salida, modo, (max(12, ancho_total - ancho_modo - 14), 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_PRINCIPAL, 1, cv2.LINE_AA)
    cv2.putText(salida, fuente, (12, 45), cv2.FONT_HERSHEY_SIMPLEX,
                0.46, COLOR_SECUNDARIO, 1, cv2.LINE_AA)
    for indice, (texto, color) in enumerate(lineas_ajustadas):
        cv2.putText(salida, texto, (12, pie + 24 + 24 * indice), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, color, 1, cv2.LINE_AA)
    return salida


def dibujar_etiqueta(imagen: np.ndarray, texto: str, puntos: np.ndarray,
                     color: tuple[int, int, int]) -> tuple[int, int, int, int]:
    """Coloca el nombre de una zona junto a su borde, dentro de la imagen."""
    alto, ancho = imagen.shape[:2]
    (ancho_texto, alto_texto), base = cv2.getTextSize(
        texto, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
    ancho_caja = min(ancho, ancho_texto + 15)
    alto_caja = min(alto, alto_texto + base + 8)
    x = max(0, min(int(puntos[:, 0].min()), ancho - ancho_caja))
    borde = int(puntos[:, 1].min())
    y = borde - alto_caja - 4
    if y < 0:
        y = borde + 4
    y = max(0, min(y, alto - alto_caja))
    cv2.rectangle(imagen, (x, y), (x + ancho_caja - 1, y + alto_caja - 1),
                  COLOR_FONDO, cv2.FILLED)
    cv2.rectangle(imagen, (x, y), (min(x + 3, x + ancho_caja - 1), y + alto_caja - 1),
                  color, cv2.FILLED)
    cv2.putText(imagen, texto, (x + 7, min(alto - 1, y + alto_texto + 3)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, COLOR_PRINCIPAL, 1, cv2.LINE_AA)
    return x, y, x + ancho_caja - 1, y + alto_caja - 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--image", type=Path, help="imagen fija para calibrar")
    grupo.add_argument("--source", choices=("http", "camera"), help="fuente en vivo")
    parser.add_argument("--http-url", help="URL HTTP explicita; preferir archivo privado")
    parser.add_argument("--device", help="dispositivo V4L2 explicito dentro de /dev")
    parser.add_argument("--zones", type=Path, default=DEFAULT_ZONES_PATH)
    parser.add_argument("--preview", action="store_true", help="mostrar sin editar")
    args = parser.parse_args()
    if args.image is not None:
        if args.http_url is not None or args.device is not None:
            parser.error("--image no se combina con opciones de camara")
        args.source = "image"
    else:
        args.source = args.source or "http"
        if args.source == "camera" and args.device is None:
            parser.error("--source camera requiere --device")
        if args.source == "http" and args.device is not None:
            parser.error("--device solo aplica a la fuente camera")
        if args.source == "camera" and args.http_url is not None:
            parser.error("--http-url solo aplica a la fuente http")
    return args


class ControlRaton:
    """Permite agregar y mover los puntos de una zona usando el ratón."""

    def __init__(self, calibracion: CalibracionZonas) -> None:
        self.calibracion = calibracion
        self.mensaje = "Dibuja un poligono de al menos tres vertices y pulsa Enter."
        self.arrastre: tuple[str, int] | None = None
        self.poligono_temporal: tuple[str, tuple[tuple[float, float], ...]] | None = None

    def procesar_evento(self, evento: int, x: int, y: int, flags: int, _datos: object) -> None:
        if evento == cv2.EVENT_LBUTTONDOWN:
            self._iniciar_click(x, y)
        elif evento == cv2.EVENT_MOUSEMOVE and self.arrastre is not None:
            self._actualizar_arrastre(x, y)
        elif evento == cv2.EVENT_LBUTTONUP and self.arrastre is not None:
            self._terminar_arrastre(x, y)

    def _iniciar_click(self, x: int, y: int) -> None:
        if self.calibracion.hay_borrador:
            _, self.mensaje = self.calibracion.agregar_punto(x, y)
            return

        id_seleccionado = self.calibracion.id_seleccionado
        zona_seleccionada_existe = id_seleccionado in self.calibracion.zonas
        if zona_seleccionada_existe:
            radio = min(
                RADIO_VERTICE_PX,
                max(5, round(min(self.calibracion.ancho, self.calibracion.alto) * 0.01)),
            )
            vertice = self.calibracion.vertice_cercano(
                x, y, radio, identificador=id_seleccionado
            )
            if vertice is not None:
                identificador, indice = vertice
                self.arrastre = vertice
                self.poligono_temporal = (
                    identificador,
                    self.calibracion.zonas[identificador].polygon,
                )
                self.mensaje = f"Arrastra el vertice de la zona {identificador} y suelta para confirmar."
                return

            id_contenedora = self.calibracion.zona_en_punto(x, y)
            if id_contenedora is not None:
                self.calibracion.seleccionar_zona(id_contenedora)
                self.mensaje = f"Zona {id_contenedora} seleccionada; arrastra un vertice para editar."
                return

        id_contenedora = self.calibracion.zona_en_punto(x, y)
        if id_contenedora is not None:
            self.calibracion.seleccionar_zona(id_contenedora)
            self.mensaje = f"Zona {id_contenedora} seleccionada; arrastra un vertice para editar."
            return

        self.calibracion.id_seleccionado = None
        _, self.mensaje = self.calibracion.agregar_punto(x, y)

    def _actualizar_arrastre(self, x: int, y: int) -> None:
        if self.arrastre is None or self.poligono_temporal is None:
            return
        try:
            punto = self.calibracion.pixel_a_normalizado(x, y)
        except ValueError:
            return
        identificador, indice = self.arrastre
        vertices = list(self.poligono_temporal[1])
        vertices[indice] = punto
        self.poligono_temporal = identificador, tuple(vertices)

    def _terminar_arrastre(self, x: int, y: int) -> None:
        if self.arrastre is None:
            return
        identificador, indice = self.arrastre
        aceptado, self.mensaje = self.calibracion.mover_vertice(
            identificador, indice, x, y
        )
        if not aceptado:
            self.mensaje += " Se conserva el punto anterior."
        self.arrastre = None
        self.poligono_temporal = None


def dibujar_superposicion(
    imagen: np.ndarray,
    calibracion: CalibracionZonas,
    mensaje: str = "",
    *,
    solo_vista_previa: bool = False,
    poligono_temporal: tuple[str, tuple[tuple[float, float], ...]] | None = None,
    instrucciones: list[str] | None = None,
    marco: bool = False,
    fuente: str = "Fuente sin especificar",
) -> np.ndarray:
    """Dibuja las zonas, sus puntos y los controles sobre una copia de la imagen."""

    lienzo = imagen.copy()
    alto, ancho = lienzo.shape[:2]
    numeros_seleccionados = []
    seleccion = calibracion.id_seleccionado
    if marco and seleccion in calibracion.zonas:
        poligono = calibracion.zonas[seleccion].polygon
        if poligono_temporal is not None and poligono_temporal[0] == seleccion:
            poligono = poligono_temporal[1]
        for numero, punto in enumerate(poligono, start=1):
            x, y = calibracion.normalizado_a_pixel(punto)
            texto = str(numero)
            (ancho_texto, alto_texto), base = cv2.getTextSize(
                texto, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            x = max(1, min(x + 8, ancho - ancho_texto - 2))
            y = max(alto_texto + 2, min(y - 8, alto - base - 2))
            numeros_seleccionados.append((texto, x, y, ancho_texto, alto_texto, base))
    etiqueta_seleccionada = None

    for identificador, zona in calibracion.zonas.items():
        poligono = zona.polygon
        temporal = poligono_temporal is not None and poligono_temporal[0] == identificador
        if temporal:
            poligono = poligono_temporal[1]
        puntos = np.array(
            [calibracion.normalizado_a_pixel(punto) for punto in poligono],
            dtype=np.int32,
        )
        color = (zone_identity_color(identificador) if marco else
                 COLOR_SELECCION if identificador == calibracion.id_seleccionado else
                 PALETA_ZONAS[(int(identificador[1:]) - 1) % len(PALETA_ZONAS)])
        try:
            ParkingZone(identificador, tuple(poligono))
            color_poligono = color
            geometria_valida = True
        except ValueError:
            color_poligono = COLOR_INVALIDO
            geometria_valida = False
        if marco:
            cv2.polylines(lienzo, [puntos], True, COLOR_FONDO, 7, cv2.LINE_AA)
            if geometria_valida and identificador == calibracion.id_seleccionado:
                cv2.polylines(lienzo, [puntos], True, COLOR_PRINCIPAL, 5, cv2.LINE_AA)
        cv2.polylines(lienzo, [puntos], True, color_poligono, 3, cv2.LINE_AA)
        for numero_vertice, (x, y) in enumerate(puntos, start=1):
            cv2.circle(lienzo, (int(x), int(y)), 8, color_poligono, cv2.FILLED, cv2.LINE_AA)
            cv2.circle(lienzo, (int(x), int(y)), 10,
                       COLOR_PRINCIPAL if marco else (20, 20, 20), 1, cv2.LINE_AA)
            if identificador == calibracion.id_seleccionado and not marco:
                cv2.putText(
                    lienzo,
                    str(numero_vertice),
                    (int(x) + 8, int(y) - 8),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    COLOR_TEXTO,
                    1,
                    cv2.LINE_AA,
                )
        confianzas = calibracion.metadata.get("confianza_zonas")
        confianza = confianzas.get(identificador) if isinstance(confianzas, dict) else None
        etiqueta = f"{identificador} {confianza:.0%}" if isinstance(confianza, (int, float)) else identificador
        if marco:
            rectangulo = dibujar_etiqueta(lienzo, etiqueta, puntos, color_poligono)
            if identificador == seleccion:
                etiqueta_seleccionada = rectangulo
        else:
            centro = tuple(np.mean(puntos, axis=0).astype(int))
            cv2.putText(
                lienzo,
                etiqueta,
                (int(centro[0]) - 8, int(centro[1]) + 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                color_poligono,
                3,
                cv2.LINE_AA,
            )

    puntos_pendientes = calibracion.puntos_pendientes
    if puntos_pendientes:
        identificador = "BORRADOR"
        puntos = np.array(
            [calibracion.normalizado_a_pixel(punto) for punto in puntos_pendientes],
            dtype=np.int32,
        )
        if len(puntos) > 1:
            cv2.polylines(lienzo, [puntos], False, COLOR_PENDIENTE, 2, cv2.LINE_AA)
        for x, y in puntos:
            cv2.circle(lienzo, (int(x), int(y)), 7, COLOR_PENDIENTE, cv2.FILLED, cv2.LINE_AA)
        if not marco:
            cv2.putText(
                lienzo,
                f"{identificador}: {len(puntos_pendientes)} vertices | Enter confirma (minimo 3)",
                (int(puntos[-1][0]) + 12, int(puntos[-1][1]) + 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                COLOR_PENDIENTE,
                2,
                cv2.LINE_AA,
            )

    for texto, x, y, ancho_texto, alto_texto, base in numeros_seleccionados:
        if etiqueta_seleccionada is not None:
            izquierda, arriba, derecha, abajo = etiqueta_seleccionada
            if (x - 2 <= derecha and x + ancho_texto + 2 >= izquierda
                    and y - alto_texto - 2 <= abajo and y + base + 2 >= arriba):
                debajo = abajo + alto_texto + 4
                y = debajo if debajo <= alto - base - 2 else arriba - base - 4
                y = max(alto_texto + 2, min(y, alto - base - 2))
        cv2.putText(lienzo, texto, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, COLOR_FONDO, 3, cv2.LINE_AA)
        cv2.putText(lienzo, texto, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, COLOR_PRINCIPAL, 1, cv2.LINE_AA)

    total = len(calibracion.zonas)
    if instrucciones is not None:
        lineas = list(instrucciones)
    elif solo_vista_previa:
        lineas = [f"VISTA PREVIA | Zonas: {total}", "Q: cerrar"]
    else:
        lineas = [
            f"CALIBRACION | Zonas: {total} | Seleccionada: {calibracion.id_seleccionado or 'ninguna'}",
            "Click fuera: agregar vertice | Click dentro: seleccionar | Arrastrar vertice: editar",
            "A: candidato automatico | Enter: confirmar | N: nueva | D: eliminar | Z: deshacer | C: cancelar | X: vaciar | S: guardar | Q: salir",
        ]
    if mensaje:
        lineas.append(mensaje)
    avisos = advertencias_solapamiento(calibracion.zonas)
    if avisos:
        lineas.append("AVISO: " + avisos[0])

    if marco:
        if puntos_pendientes:
            lineas.append(f"BORRADOR: {len(puntos_pendientes)} vertices | minimo 3 para confirmar")
        textos = [(texto, COLOR_AVISO if texto.startswith(("AVISO:", "Fuente"))
                   else COLOR_PRINCIPAL) for texto in lineas]
        salida = componer_marco(lienzo, 1, "CALIBRATION", fuente, textos)
        x, y = ancho + 14, ALTO_CABECERA
        seleccion = calibracion.id_seleccionado
        zona = calibracion.zonas.get(seleccion)
        resumen = ["ZONAS", f"Total: {total}", f"Seleccion: {seleccion or 'ninguna'}"]
        if zona is not None:
            vertices = (poligono_temporal[1] if poligono_temporal is not None
                        and poligono_temporal[0] == seleccion else zona.polygon)
            resumen.append(f"Vertices: {len(vertices)}")
        for indice, texto in enumerate(resumen):
            cv2.putText(salida, texto, (x, y + 26 + indice * 25), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, COLOR_PRINCIPAL if indice == 0 else COLOR_SECUNDARIO,
                        1, cv2.LINE_AA)
        return salida

    alto_panel = 16 + 24 * len(lineas)
    panel = lienzo.copy()
    cv2.rectangle(panel, (0, 0), (ancho - 1, min(alto - 1, alto_panel)), (15, 15, 15), cv2.FILLED)
    cv2.addWeighted(panel, 0.78, lienzo, 0.22, 0.0, lienzo)
    for indice, texto in enumerate(lineas):
        color = (0, 190, 255) if texto.startswith("AVISO:") else COLOR_TEXTO
        cv2.putText(
            lienzo,
            texto,
            (12, 25 + indice * 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            1,
            cv2.LINE_AA,
        )
    return lienzo


def _leer_imagen(ruta: Path) -> np.ndarray:
    imagen = cv2.imread(str(ruta), cv2.IMREAD_COLOR)
    if imagen is None:
        raise ValueError(f"No se pudo abrir la imagen: {ruta}")
    return imagen


def ejecutar(args: argparse.Namespace) -> int:
    capturador = None
    ventana_creada = False
    guardia = FrameQualityGuard()
    revision = -1
    generacion = 0
    muestra_actual = None
    estado_fuente = {"valida": True, "motivo": ""}
    try:
        if args.source == "image":
            if args.image is None:
                raise ValueError("La fuente image requiere --image.")
            cuadro = _leer_imagen(args.image)
            valido, _ = guardia.inspect(cuadro, allow_repeated=True)
            if not valido:
                raise ValueError("La imagen de calibracion no tiene calidad suficiente.")
            valor_fuente = args.image
        else:
            url = resolver_url_http(args.http_url) if args.source == "http" else None
            dispositivo = (validar_dispositivo(getattr(args, "device", None))
                           if args.source == "camera" else None)
            valor_fuente = url if args.source == "http" else dispositivo
            capturador = CapturadorReciente(args.source, url, dispositivo)
            capturador.iniciar()
            cv2.namedWindow(TITULO_VENTANA, cv2.WINDOW_AUTOSIZE)
            ventana_creada = True
            espera = np.zeros((360, 640, 3), dtype=np.uint8)
            while True:
                muestra_actual = capturador.esperar(revision, 0.05)
                revision = muestra_actual.revision
                if (muestra_actual.estado == "conectada" and muestra_actual.cuadro is not None
                        and muestra_actual.momento is not None
                        and time.monotonic() - muestra_actual.momento <= 2.0):
                    valido, _ = guardia.inspect(muestra_actual.cuadro)
                    if valido:
                        cuadro = muestra_actual.cuadro
                        generacion = muestra_actual.generacion
                        print(f"Fuente activa: {muestra_actual.backend}.")
                        break
                espera.fill(0)
                cv2.putText(espera, "NO_VERIFICABLE: esperando fuente valida; Q cierra",
                            (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
                cv2.imshow(TITULO_VENTANA, espera)
                if cv2.waitKey(30) & 0xff in (ord("q"), ord("Q")):
                    return 0
                try:
                    if cv2.getWindowProperty(TITULO_VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                        return 0
                except cv2.error:
                    return 0

        alto, ancho = cuadro.shape[:2]
        verificar_sin_guardado_pendiente(args.zones)
        if args.zones.exists():
            verificar_vinculo(args.zones, args.source, valor_fuente, ancho, alto)
            calibracion = cargar_calibracion(args.zones, ancho, alto)
        elif args.preview:
            raise ValueError(f"No existe el archivo de calibracion: {args.zones}")
        else:
            calibracion = CalibracionZonas(ancho, alto)

        control = ControlRaton(calibracion)
        control.mensaje = (f"Archivo cargado: {args.zones}" if calibracion.zonas else
                           "Calibracion vacia; dibuja un poligono para crear C1.")
        if not ventana_creada:
            cv2.namedWindow(TITULO_VENTANA, cv2.WINDOW_AUTOSIZE)
            ventana_creada = True
        def procesar_raton(evento, x, y, flags, param):
            if estado_fuente["valida"]:
                control.procesar_evento(evento, x, y, flags, param)
        if not args.preview:
            cv2.setMouseCallback(TITULO_VENTANA, procesar_raton)
        print(f"Modo={'vista previa' if args.preview else 'calibracion'}; "
              f"fuente={args.source}; imagen={ancho}x{alto}; "
              f"zonas={calibracion.cantidad_completa}; siguiente=C{calibracion.next_c_number}.")

        while True:
            if capturador is not None:
                muestra = capturador.esperar(revision, 0.005)
                nueva = muestra.revision != revision
                revision = muestra.revision
                fresca = (muestra.estado == "conectada" and muestra.cuadro is not None
                          and muestra.momento is not None
                          and time.monotonic() - muestra.momento <= 2.0)
                if not fresca:
                    estado_fuente.update(valida=False, motivo="fuente interrumpida o sin frescura")
                elif nueva:
                    if muestra.cuadro.shape[:2] != (alto, ancho):
                        estado_fuente.update(valida=False, motivo="geometria de fuente cambiada")
                    else:
                        cuadro = muestra.cuadro
                        valido, motivo = guardia.inspect(cuadro)
                        if valido:
                            if not estado_fuente["valida"] or muestra.generacion != generacion:
                                control.mensaje = "Fuente recuperada; borrador conservado."
                            generacion = muestra.generacion
                            estado_fuente.update(valida=True, motivo="")
                        else:
                            estado_fuente.update(valida=False, motivo=str(motivo))
                muestra_actual = muestra

            mensaje = (control.mensaje if estado_fuente["valida"] else
                       f"NO VERIFICABLE: {estado_fuente['motivo']}; edicion y guardado suspendidos.")
            pantalla = dibujar_superposicion(cuadro, calibracion, mensaje,
                                             solo_vista_previa=args.preview,
                                             poligono_temporal=control.poligono_temporal)
            cv2.imshow(TITULO_VENTANA, pantalla)
            tecla = cv2.waitKey(30) & 0xff
            if tecla in (ord("q"), ord("Q")):
                return 0
            if not args.preview and estado_fuente["valida"]:
                if tecla in (ord("a"), ord("A")):
                    if capturador is None:
                        _proponer_candidato(cuadro, calibracion, control)
                    else:
                        reciente = capturador.instantanea()
                        valido = (
                            reciente.estado == "conectada"
                            and reciente.cuadro is not None
                            and reciente.cuadro.shape[:2] == (alto, ancho)
                            and reciente.generacion == generacion
                            and reciente.momento is not None
                            and time.monotonic() - reciente.momento <= 2.0
                            and FrameQualityGuard().inspect(
                                reciente.cuadro, allow_repeated=True,
                            )[0]
                        )
                        if valido:
                            _proponer_candidato(
                                reciente.cuadro.copy(), calibracion, control,
                                aplicar=lambda accion: capturador.aplicar_si_vigente(
                                    reciente, 2.0, accion,
                                ),
                            )
                        else:
                            control.mensaje = "Fuente no verificable; no se genero candidato."
                elif tecla in (ord("s"), ord("S")) and capturador is not None:
                    # Comprueba que la cámara siga conectada y que la imagen no
                    # cambie durante la revisión antes de guardar las zonas.
                    reciente = capturador.instantanea()
                    valido = (reciente.estado == "conectada" and reciente.cuadro is not None
                              and reciente.cuadro.shape[:2] == (alto, ancho)
                              and reciente.generacion == generacion
                              and FrameQualityGuard().inspect(reciente.cuadro, allow_repeated=True)[0])
                    if valido:
                        valido = capturador.aplicar_si_vigente(
                            reciente, 2.0,
                            lambda: _procesar_tecla(tecla, calibracion, control, args.zones,
                                                     args.source, valor_fuente),
                            misma_revision=True)
                    if not valido:
                        control.mensaje = "Fuente no verificable; intente guardar de nuevo."
                else:
                    _procesar_tecla(tecla, calibracion, control, args.zones,
                                    args.source, valor_fuente)
            try:
                if cv2.getWindowProperty(TITULO_VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                    return 0
            except cv2.error:
                return 0
    except (OSError, RuntimeError, ValueError, cv2.error) as error:
        print(f"No se pudo ejecutar la calibracion ({error.__class__.__name__}): {error}", file=sys.stderr)
        return 1
    finally:
        if capturador is not None:
            if capturador.detener():
                print("Fuente de video liberada; ventanas cerradas.")
            else:
                print("La fuente no termino dentro del limite de cierre.", file=sys.stderr)
        cv2.destroyAllWindows()


def _restaurar_par_calibracion(ruta_zonas: Path, respaldo: Path | None) -> None:
    """Recupera el par anterior completo o restablece su ausencia."""
    vinculo = ruta_vinculo(ruta_zonas)
    destinos = (ruta_zonas, vinculo)
    if respaldo is None:
        for destino in destinos:
            destino.unlink(missing_ok=True)
        contenidos = (None, None)
    else:
        contenidos = tuple((respaldo / destino.name).read_bytes() for destino in destinos)
        for destino, contenido in zip(destinos, contenidos, strict=True):
            if destino.is_file() and destino.read_bytes() == contenido:
                continue
            temporal = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=destino.parent,
                    prefix=f".{destino.name}.restaurar-", delete=False,
                ) as salida:
                    temporal = Path(salida.name)
                    salida.write(contenido)
                    salida.flush()
                    os.fsync(salida.fileno())
                os.chmod(temporal, 0o600)
                os.replace(temporal, destino)
            finally:
                if temporal is not None:
                    temporal.unlink(missing_ok=True)

    if ruta_zonas.parent.exists():
        descriptor = os.open(ruta_zonas.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    for destino, contenido in zip(destinos, contenidos, strict=True):
        if contenido is None:
            if destino.exists() or destino.is_symlink():
                raise OSError("No se pudo restablecer la ausencia de la calibracion.")
        elif not destino.is_file() or destino.read_bytes() != contenido:
            raise OSError("La calibracion restaurada no coincide con el respaldo.")


def _procesar_tecla(
    tecla: int,
    calibracion: CalibracionZonas,
    control: ControlRaton,
    ruta_zonas: Path,
    tipo_fuente: str,
    valor_fuente: str | Path | None = None,
    imagen: np.ndarray | None = None,
) -> None:
    if tecla in (ord("a"), ord("A")):
        if imagen is None:
            control.mensaje = "No hay un frame actual para generar el candidato."
        else:
            _proponer_candidato(imagen, calibracion, control)
    elif tecla in (10, 13):
        _, control.mensaje = calibracion.confirmar_poligono()
    elif tecla in (ord("n"), ord("N")):
        _, control.mensaje = calibracion.iniciar_nueva_zona()
    elif tecla in (ord("z"), ord("Z")):
        _, control.mensaje = calibracion.deshacer_punto()
    elif tecla in (ord("c"), ord("C")):
        control.mensaje = calibracion.cancelar_poligono()
    elif tecla in (ord("d"), ord("D")):
        control.mensaje = calibracion.eliminar_zona()
    elif tecla in (ord("x"), ord("X")):
        calibracion.reiniciar_todas()
        control.mensaje = "Todas las zonas se reiniciaron."
    elif tecla in (ord("s"), ord("S")):
        metadata_anterior = copy.deepcopy(calibracion.metadata)
        pendientes_anteriores = calibracion.cambios_pendientes
        try:
            if valor_fuente is not None:
                calibracion.metadata["fuente_sha256"] = identidad_fuente(
                    tipo_fuente, valor_fuente,
                )
            datos_fuente = ({} if valor_fuente is None else {
                "tipo": tipo_fuente, "fuente": valor_fuente,
                "ancho": calibracion.ancho, "alto": calibracion.alto,
            })
            guardado, respaldo = preparar_guardado_calibracion(ruta_zonas, **datos_fuente)
        except BaseException as error:
            calibracion.metadata = metadata_anterior
            calibracion.cambios_pendientes = pendientes_anteriores
            if not isinstance(error, (OSError, ValueError, TypeError)):
                raise
            control.mensaje = f"No se guardo: {error}"
            return
        try:
            try:
                _comprobar_guardado_propio(ruta_zonas, guardado)
                avisos = guardar_calibracion(ruta_zonas, calibracion, tipo_fuente)
                if valor_fuente is not None:
                    _comprobar_guardado_propio(ruta_zonas, guardado)
                    guardar_vinculo(
                        ruta_zonas, tipo_fuente, valor_fuente,
                        calibracion.ancho, calibracion.alto,
                    )
                    datos = json.loads(ruta_vinculo(ruta_zonas).read_text(encoding="utf-8"))
                    if not _sidecar_compatible(
                        ruta_zonas, datos, tipo_fuente, valor_fuente,
                        calibracion.ancho, calibracion.alto,
                    ):
                        raise ValueError("El vinculo guardado no corresponde a la calibracion.")
            except BaseException as error:
                calibracion.metadata = metadata_anterior
                calibracion.cambios_pendientes = pendientes_anteriores
                try:
                    _comprobar_guardado_propio(ruta_zonas, guardado)
                    _restaurar_par_calibracion(ruta_zonas, respaldo)
                    finalizar_guardado_pendiente(ruta_zonas, guardado)
                except BaseException as recuperacion:
                    detalle = (f"respaldo disponible en {respaldo}" if respaldo is not None
                               else "no existia un par anterior")
                    control.mensaje = f"No se recupero la calibracion anterior; {detalle}."
                    raise RuntimeError(control.mensaje) from recuperacion
                if not isinstance(error, (OSError, ValueError, TypeError)):
                    raise
                control.mensaje = f"No se guardo: {error}. Se recupero el estado anterior."
            else:
                try:
                    finalizar_guardado_pendiente(ruta_zonas, guardado)
                except BaseException as cierre:
                    control.mensaje = (
                        "La calibracion se escribio, pero no se pudo cerrar el guardado pendiente; "
                        "conserve el respaldo y revise el par."
                    )
                    raise RuntimeError(control.mensaje) from cierre
                control.mensaje = f"Guardadas {calibracion.cantidad_completa} zonas en {ruta_zonas}."
                if avisos:
                    control.mensaje += " " + " ".join(avisos)
        finally:
            guardado.cerrar()


def _misma_geometria_e_identidades(primera: CalibracionZonas, segunda: CalibracionZonas) -> bool:
    """Compara las zonas, sus puntos, identidades y tamaño de imagen."""
    return (
        primera.ancho == segunda.ancho
        and primera.alto == segunda.alto
        and set(primera.zonas) == set(segunda.zonas)
        and primera.vision_zone_ids == segunda.vision_zone_ids
        and all(
            tuple(tuple(round(valor, 8) for valor in punto)
                  for punto in primera.zonas[etiqueta].polygon)
            == tuple(tuple(round(valor, 8) for valor in punto)
                     for punto in segunda.zonas[etiqueta].polygon)
            for etiqueta in primera.zonas
        )
    )
