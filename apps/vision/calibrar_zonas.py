"""Editor visual local para calibrar cualquier numero de zonas."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from calibracion_zonas import (
    CalibracionZonas,
    advertencias_solapamiento,
    cargar_calibracion,
    guardar_calibracion,
)
from capture import (
    DEFAULT_HTTP_URL,
    MAX_CAMERA_INDEX,
    open_video_source,
    read_frame,
)
from temporal_validation import ParkingZone
from smart_parking_client import (
    SmartParkingClient,
    VisionAPIError,
    ruta_cache_zonas,
)

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_ZONES_PATH = ruta_cache_zonas()
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, help="imagen fija para calibrar o previsualizar")
    parser.add_argument(
        "--source",
        choices=("http", "camera"),
        help="fuente en vivo; por defecto usa HTTP salvo que se indique --image",
    )
    parser.add_argument("--http-url", default=DEFAULT_HTTP_URL)
    parser.add_argument(
        "--api-url",
        help="activa el modo integrado; la API reemplaza el contenido de la cache local",
    )
    parser.add_argument("--camera-index", type=int)
    parser.add_argument("--backend", choices=("auto", "dshow", "msmf"))
    parser.add_argument(
        "--zones",
        type=Path,
        default=DEFAULT_ZONES_PATH,
        help="archivo JSON de calibracion (por defecto: zones.json)",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="mostrar zonas existentes sin permitir cambios",
    )
    args = parser.parse_args()

    seleccion_local = args.camera_index is not None or args.backend is not None
    if args.image is not None and (args.source is not None or seleccion_local):
        parser.error("--image no se combina con --source, --camera-index ni --backend")
    if args.camera_index is not None and not 0 <= args.camera_index <= MAX_CAMERA_INDEX:
        parser.error(f"--camera-index debe estar entre 0 y {MAX_CAMERA_INDEX}")

    if args.source is None:
        if args.image is not None:
            args.source = "image"
        else:
            args.source = "camera" if seleccion_local else "http"
    if seleccion_local and args.source != "camera":
        parser.error("--camera-index y --backend solo aplican con --source camera")
    if args.backend is None:
        args.backend = "auto"
    return args


class ControlRaton:
    """Traduce clicks y arrastres de la ventana a ediciones de vertices."""

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
) -> np.ndarray:
    """Dibuja zonas, vertices y controles sobre una copia del cuadro original."""

    lienzo = imagen.copy()
    alto, ancho = lienzo.shape[:2]

    for identificador, zona in calibracion.zonas.items():
        poligono = zona.polygon
        temporal = poligono_temporal is not None and poligono_temporal[0] == identificador
        if temporal:
            poligono = poligono_temporal[1]
        puntos = np.array(
            [calibracion.normalizado_a_pixel(punto) for punto in poligono],
            dtype=np.int32,
        )
        color = (
            COLOR_SELECCION
            if identificador == calibracion.id_seleccionado
            else PALETA_ZONAS[(int(identificador[1:]) - 1) % len(PALETA_ZONAS)]
        )
        try:
            ParkingZone(identificador, tuple(poligono))
            color_poligono = color
        except ValueError:
            color_poligono = COLOR_INVALIDO
        cv2.polylines(lienzo, [puntos], True, color_poligono, 3, cv2.LINE_AA)
        for numero_vertice, (x, y) in enumerate(puntos, start=1):
            cv2.circle(lienzo, (int(x), int(y)), 8, color_poligono, cv2.FILLED, cv2.LINE_AA)
            cv2.circle(lienzo, (int(x), int(y)), 10, (20, 20, 20), 1, cv2.LINE_AA)
            if identificador == calibracion.id_seleccionado:
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
        centro = tuple(np.mean(puntos, axis=0).astype(int))
        etiqueta = f"{identificador}"
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

    total = len(calibracion.zonas)
    if solo_vista_previa:
        lineas = [f"VISTA PREVIA | Zonas: {total}", "Q: cerrar"]
    else:
        lineas = [
            f"CALIBRACION | Zonas: {total} | Seleccionada: {calibracion.id_seleccionado or 'ninguna'}",
            "Click fuera: agregar vertice | Click dentro: seleccionar | Arrastrar vertice: editar",
            "Enter: confirmar poligono | N: nueva zona | D: eliminar | Z: deshacer | C: cancelar | X: vaciar | S: guardar | Q: salir",
        ]
    if mensaje:
        lineas.append(mensaje)
    avisos = advertencias_solapamiento(calibracion.zonas)
    if avisos:
        lineas.append("AVISO: " + avisos[0])

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
    captura = None
    try:
        cliente_api = None
        if getattr(args, "api_url", None):
            cliente_api = SmartParkingClient(args.api_url)
            cliente_api.cargar_configuracion()
            args.zones = ruta_cache_zonas()
        if args.source == "image":
            if args.image is None:
                raise ValueError("La fuente image requiere --image.")
            cuadro = _leer_imagen(args.image)
            tipo_fuente = "image"
            nombre_fuente = str(args.image)
        else:
            captura, nombre_fuente, backend, cuadro = open_video_source(
                args.source,
                args.http_url,
                args.camera_index,
                args.backend,
            )
            tipo_fuente = args.source
            print(f"Fuente activa: {nombre_fuente}; backend={backend}.")

        alto, ancho = cuadro.shape[:2]
        if args.zones.exists():
            calibracion = cargar_calibracion(args.zones, ancho, alto)
        elif args.preview:
            raise ValueError(f"No existe el archivo de calibracion: {args.zones}")
        else:
            calibracion = CalibracionZonas(ancho, alto)

        control = ControlRaton(calibracion)
        mensaje = (
            f"Archivo cargado: {args.zones}"
            if calibracion.zonas
            else "Calibracion vacia; dibuja un poligono para crear C1."
        )
        control.mensaje = mensaje
        cv2.namedWindow(TITULO_VENTANA, cv2.WINDOW_AUTOSIZE)
        if not args.preview:
            cv2.setMouseCallback(TITULO_VENTANA, control.procesar_evento)
        print(
            f"Modo={'vista previa' if args.preview else 'calibracion'}; "
            f"fuente={tipo_fuente}; imagen={ancho}x{alto}; "
            f"zonas={calibracion.cantidad_completa}; siguiente=C{calibracion.next_c_number}."
        )

        while True:
            mensaje_visible = control.mensaje if control.mensaje else mensaje
            pantalla = dibujar_superposicion(
                cuadro,
                calibracion,
                mensaje_visible,
                solo_vista_previa=args.preview,
                poligono_temporal=control.poligono_temporal,
            )
            cv2.imshow(TITULO_VENTANA, pantalla)
            tecla = cv2.waitKey(30) & 0xFF
            if tecla in (ord("q"), ord("Q")):
                return 0

            if not args.preview:
                _procesar_tecla(
                    tecla,
                    calibracion,
                    control,
                    args.zones,
                    tipo_fuente,
                    cliente_api,
                )

            try:
                if cv2.getWindowProperty(TITULO_VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                    return 0
            except cv2.error:
                return 0

            if captura is not None:
                cuadro = read_frame(captura, nombre_fuente)

    except (OSError, RuntimeError, ValueError, VisionAPIError, cv2.error) as error:
        print(f"No se pudo ejecutar la calibracion ({error.__class__.__name__}): {error}", file=sys.stderr)
        return 1
    finally:
        if captura is not None:
            captura.release()
        cv2.destroyAllWindows()
        if captura is not None:
            print("Fuente de video liberada; ventanas cerradas.")


def _procesar_tecla(
    tecla: int,
    calibracion: CalibracionZonas,
    control: ControlRaton,
    ruta_zonas: Path,
    tipo_fuente: str,
    cliente_api: SmartParkingClient | None = None,
) -> None:
    if tecla in (10, 13):
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
        try:
            if cliente_api is None:
                avisos = guardar_calibracion(ruta_zonas, calibracion, tipo_fuente)
            else:
                cliente_api.guardar_configuracion(calibracion)
                canonica = cargar_calibracion(
                    ruta_cache_zonas(),
                    calibracion.ancho,
                    calibracion.alto,
                )
                calibracion.zonas = canonica.zonas
                calibracion.vision_zone_ids = canonica.vision_zone_ids
                calibracion.next_c_number = canonica.next_c_number
                calibracion.id_seleccionado = None
                calibracion.cambios_pendientes = False
                avisos = advertencias_solapamiento(calibracion.zonas)
        except (OSError, ValueError, VisionAPIError) as error:
            control.mensaje = f"No se guardo: {error}"
        else:
            destino = "FastAPI" if cliente_api is not None else str(ruta_zonas)
            control.mensaje = f"Guardadas {calibracion.cantidad_completa} zonas en {destino}."
            if calibracion.hay_borrador:
                control.mensaje += " El borrador actual no se guardo."
            if avisos:
                control.mensaje += " " + avisos[0]


def main() -> int:
    return ejecutar(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
