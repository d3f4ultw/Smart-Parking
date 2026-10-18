"""Run pretrained YOLO26n detection on a local feed, still image, or simulation."""

from __future__ import annotations

import argparse
import colorsys
import math
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from capture import (
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    DEFAULT_HTTP_URL,
    open_video_source,
    read_frame,
    validate_frame,
)
from temporal_validation import (
    FrameQualityGuard,
    MINIMUM_CONFIDENCE,
    RELEASE_MISSING_FRAMES,
    STRONG_CONFIDENCE,
    STRONG_CONFIRMATION_FRAMES,
    WEAK_CONFIRMATION_COUNT,
    WEAK_CONFIRMATION_WINDOW,
    OccupancyState,
    TemporalOccupancyValidator,
    VehicleDetection,
    ZoneSnapshot,
    load_zones,
)
from simulation_playback import build_simulation_sequence, next_frame_index
from smart_parking_client import (
    INTERVALO_HEARTBEAT_SEGUNDOS,
    INTERVALO_OBSERVACION_SEGUNDOS,
    SmartParkingClient,
    VisionAPIError,
    ruta_cache_zonas,
    ruta_estado_vision,
)

PROJECT_DIR = Path(__file__).resolve().parent
MODEL_DIR = PROJECT_DIR / "models"
DEFAULT_ZONES_PATH = ruta_cache_zonas()
MODEL_DIR.mkdir(parents=True, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = str(ruta_estado_vision() / "ultralytics")

from ultralytics import YOLO  # noqa: E402
from ultralytics.utils.downloads import attempt_download_asset  # noqa: E402

MODEL_PATH = MODEL_DIR / "yolo26n.pt"
VEHICLE_CLASSES = (2, 3, 5, 7)  # car, motorcycle, bus, truck (COCO)
WINDOW_TITLE = "Smart Parking Vision - YOLO26n Vehicle Detection"
CAPTURE_SAMPLE_SECONDS = 2.0


class PublicadorVision:
    """Envía solo snapshots estables y conserva la frescura ante errores."""

    def __init__(self, client: SmartParkingClient) -> None:
        self.client = client
        ahora = time.monotonic()
        self.ultimo_heartbeat = ahora
        self.ultimo_intento_observacion = ahora
        self.deshabilitado = False
        self.error_reportado = False

    def avanzar(self, snapshots: tuple[ZoneSnapshot, ...], *, inferencia_valida: bool) -> None:
        """Renueva el heartbeat y publica estados solo tras inferencia valida."""

        if self.deshabilitado:
            return
        ahora = time.monotonic()
        try:
            if ahora - self.ultimo_heartbeat >= INTERVALO_HEARTBEAT_SEGUNDOS:
                self.client.heartbeat()
                self.ultimo_heartbeat = ahora
            if (
                inferencia_valida
                and ahora - self.ultimo_intento_observacion
                >= INTERVALO_OBSERVACION_SEGUNDOS
            ):
                self.ultimo_intento_observacion = ahora
                self.client.publicar_observaciones(snapshots)
        except VisionAPIError as error:
            if not self.error_reportado:
                codigo = "sin respuesta" if error.status_code is None else f"HTTP {error.status_code}"
                print(
                    f"Vision no acepto la telemetria ({codigo}); se conserva el estado desactualizado.",
                    file=sys.stderr,
                )
                self.error_reportado = True
            if error.status_code == 409:
                self.deshabilitado = True


def iniciar_publicador_vision(args: argparse.Namespace) -> PublicadorVision | None:
    """Carga primero la configuracion de API para evitar zonas locales obsoletas."""

    if not args.publish:
        return None
    api_url = args.api_url or os.environ.get(
        "VISION_API_BASE_URL",
        "http://127.0.0.1:8000",
    )
    client = SmartParkingClient(api_url)
    configuracion = client.cargar_configuracion()
    client.iniciar_sesion()
    args.zones = ruta_cache_zonas()
    print(
        f"Vision publication enabled: revision={configuracion.revision}, "
        f"active_zones={len(configuracion.zones)}."
    )
    return PublicadorVision(client)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--image",
        type=Path,
        help="run one local still image with the same detections and zone overlay",
    )
    source_group.add_argument(
        "--source",
        choices=("http", "camera"),
        help="video source (default: HTTP unless legacy camera options are supplied)",
    )
    source_group.add_argument(
        "--simulation-dir",
        type=Path,
        help="play numbered still-image frames as a temporal video simulation",
    )
    parser.add_argument("--http-url")
    parser.add_argument(
        "--api-url",
        help="direccion de Smart Parking API usada con --publish",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="publica solo ocupaciones estabilizadas a la API Vision",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="procesa sin abrir ventanas ni esperar entradas de teclado",
    )
    parser.add_argument("--camera-index", type=int)
    parser.add_argument("--backend", choices=("dshow", "msmf", "auto"))
    parser.add_argument(
        "--frame-duration",
        type=float,
        default=None,
        help="default seconds to hold each simulation image (default: 30)",
    )
    parser.add_argument(
        "--frame-duration-override",
        action="append",
        default=[],
        metavar="FRAME=SECONDS",
        help="override one simulation frame duration; repeat for multiple frames",
    )
    parser.add_argument(
        "--no-loop",
        action="store_true",
        help="play the simulation sequence once instead of looping",
    )
    parser.add_argument(
        "--playback-fps",
        type=float,
        default=None,
        help="maximum repeated YOLO cycles per second while a simulation image is held",
    )
    parser.add_argument("--imgsz", type=int, default=960, help="YOLO inference image size")
    parser.add_argument("--conf", type=float, default=0.30, help="minimum YOLO confidence")
    parser.add_argument(
        "--zones",
        type=Path,
        help="calibrated normalized zones JSON (auto-loads zones.json when present)",
    )
    parser.add_argument("--minimum-confidence", type=float, default=MINIMUM_CONFIDENCE)
    parser.add_argument("--strong-confidence", type=float, default=STRONG_CONFIDENCE)
    parser.add_argument(
        "--strong-confirmation-frames", type=int, default=STRONG_CONFIRMATION_FRAMES
    )
    parser.add_argument(
        "--weak-confirmation-count", type=int, default=WEAK_CONFIRMATION_COUNT
    )
    parser.add_argument(
        "--weak-confirmation-window", type=int, default=WEAK_CONFIRMATION_WINDOW
    )
    parser.add_argument(
        "--release-missing-frames", type=int, default=RELEASE_MISSING_FRAMES
    )
    args = parser.parse_args()
    if args.api_url is not None and not args.publish:
        parser.error("--api-url requiere --publish")
    if args.publish and args.image is not None:
        parser.error("--publish requiere video en vivo o --simulation-dir; una imagen no estabiliza estados")
    if args.camera_index is not None and not 0 <= args.camera_index <= 9:
        parser.error("--camera-index must be between 0 and 9")
    if args.imgsz < 32:
        parser.error("--imgsz must be at least 32")
    if not 0.0 <= args.conf <= 1.0:
        parser.error("--conf must be between 0 and 1")
    if not 0.0 <= args.minimum_confidence < args.strong_confidence <= 1.0:
        parser.error("confidence thresholds must satisfy 0 <= minimum < strong <= 1")
    if args.strong_confirmation_frames < 2:
        parser.error("--strong-confirmation-frames must be at least 2")
    if (
        args.weak_confirmation_count < 1
        or args.weak_confirmation_window < args.weak_confirmation_count
    ):
        parser.error("weak confirmation window must fit the required positive-frame count")
    if args.release_missing_frames < 1:
        parser.error("--release-missing-frames must be at least 1")
    legacy_camera_selection = args.camera_index is not None or args.backend is not None
    if args.image is not None or args.simulation_dir is not None:
        if args.http_url is not None or legacy_camera_selection:
            parser.error(
                "--image/--simulation-dir cannot be combined with live-video source options"
            )
    else:
        if args.http_url is None:
            args.http_url = DEFAULT_HTTP_URL
        if args.source is None:
            args.source = "camera" if legacy_camera_selection else "http"
        if args.source == "http" and legacy_camera_selection:
            parser.error("--camera-index/--backend cannot be combined with --source http")
    if args.image is None and args.simulation_dir is None and args.backend is None:
        args.backend = "msmf"
    simulation_options_supplied = (
        args.frame_duration is not None
        or args.playback_fps is not None
        or bool(args.frame_duration_override)
        or args.no_loop
    )
    if args.simulation_dir is not None:
        if args.frame_duration is None:
            args.frame_duration = 30.0
        if args.playback_fps is None:
            args.playback_fps = 5.0
        if not math.isfinite(args.frame_duration) or args.frame_duration <= 0:
            parser.error("--frame-duration must be a finite positive number")
        if not math.isfinite(args.playback_fps) or not 0 < args.playback_fps <= 60:
            parser.error("--playback-fps must be greater than 0 and no more than 60")
    elif simulation_options_supplied:
        parser.error("simulation timing and loop options require --simulation-dir")
    if args.zones is None and DEFAULT_ZONES_PATH.is_file():
        args.zones = DEFAULT_ZONES_PATH
    return args


def load_model() -> YOLO:
    """Load the official pretrained checkpoint into this project's models directory."""
    checkpoint = attempt_download_asset(str(MODEL_PATH))
    return YOLO(checkpoint)


def load_model_from_path(model_path: str | Path) -> YOLO:
    """Carga un checkpoint explícito sin intentar descargarlo."""

    checkpoint = Path(model_path).expanduser()
    if not checkpoint.is_file():
        raise FileNotFoundError("El checkpoint configurado no está disponible.")
    return YOLO(str(checkpoint))


def is_blank_frame(frame: object) -> bool:
    """Detect a fully black or near-black source frame."""
    return int(frame.max()) <= 1


def measure_capture_rate(
    capture: cv2.VideoCapture, frame: object, seconds: float, source_name: str
) -> tuple[float, object, int, float]:
    """Measure source-only read throughput before timing inference."""
    validate_frame(frame, source_name)
    started = time.perf_counter()
    frame_count = 0
    latest_frame = frame
    while time.perf_counter() - started < seconds:
        next_frame = read_frame(capture, source_name)
        latest_frame = next_frame
        frame_count += 1
    elapsed = time.perf_counter() - started
    return frame_count / elapsed, latest_frame, frame_count, elapsed


def predict(model: YOLO, frame: object, imgsz: int, confidence: float):
    started = time.perf_counter()
    results = model.predict(
        source=frame,
        imgsz=imgsz,
        conf=confidence,
        classes=list(VEHICLE_CLASSES),
        device="cpu",
        verbose=False,
    )
    predict_call_ms = (time.perf_counter() - started) * 1000.0
    result = results[0]
    model_inference_ms = float(result.speed.get("inference", predict_call_ms))
    return result, predict_call_ms, model_inference_ms


def detections_from_result(result) -> list[VehicleDetection]:
    """Convert the current YOLO result into one spatial-validation input per box."""
    if result.boxes is None or len(result.boxes) == 0:
        return []
    boxes = result.boxes.xyxy.cpu().tolist()
    class_ids = result.boxes.cls.cpu().tolist()
    confidences = result.boxes.conf.cpu().tolist()
    names = result.names
    detections = []
    for box, raw_class_id, raw_confidence in zip(boxes, class_ids, confidences):
        class_id = int(raw_class_id)
        if isinstance(names, dict):
            class_name = str(names.get(class_id, class_id))
        else:
            class_name = str(names[class_id])
        detections.append(
            VehicleDetection(
                tuple(float(value) for value in box),
                float(raw_confidence),
                class_name,
            )
        )
    return detections


def draw_vehicle_detections(
    image: np.ndarray, detections: list[VehicleDetection]
) -> np.ndarray:
    """Draw vehicle boxes with directly readable confidence percentages."""
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
    """Use colors reserved for zone-state polygons and labels."""
    if not ready:
        return (150, 150, 150)
    if state is OccupancyState.OCUPADO:
        return (0, 210, 0)
    if state is OccupancyState.CANDIDATO_OCUPADO:
        return (0, 165, 255)
    return (210, 210, 210)


def zone_identity_color(identifier: str) -> tuple[int, int, int]:
    """Return a stable BGR color derived from the permanent C-number."""
    if not identifier.startswith("C") or not identifier[1:].isdigit():
        return (150, 150, 150)
    numero = int(identifier[1:])
    if numero < 1:
        return (150, 150, 150)

    matiz = ((numero - 1) * 137.508) % 360 / 360
    rojo, verde, azul = colorsys.hls_to_rgb(matiz, 0.56, 0.78)
    return round(azul * 255), round(verde * 255), round(rojo * 255)


def draw_zone_states(
    display,
    snapshots: tuple[ZoneSnapshot, ...],
    width: int,
    height: int,
    compact_labels: bool = False,
) -> None:
    """Draw configured polygons separately from raw YOLO detection boxes."""
    if snapshots and snapshots[0].is_demo:
        snapshot = snapshots[0]
        text = f"DEMO ONLY - WHOLE FRAME | {snapshot.state.value}"
        cv2.rectangle(display, (8, 8), (min(width - 8, 545), 42), (20, 20, 20), cv2.FILLED)
        cv2.putText(
            display, text, (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
            zone_color(snapshot.state), 2, cv2.LINE_AA,
        )
        return

    for snapshot in snapshots:
        color_estado = zone_color(snapshot.state, ready=snapshot.is_ready)
        color_identidad = zone_identity_color(snapshot.identifier)
        estado = snapshot.state.value if snapshot.is_ready else "DESCONOCIDO"
        points = [
            (round(x * (width - 1)), round(y * (height - 1)))
            for x, y in snapshot.polygon
        ]
        puntos_np = np.array(points, dtype="int32")
        capa_relleno = display.copy()
        cv2.fillPoly(capa_relleno, [puntos_np], color_identidad)
        cv2.addWeighted(capa_relleno, 0.14, display, 0.86, 0, display)
        cv2.polylines(display, [puntos_np], True, color_identidad, 2, cv2.LINE_AA)
        if compact_labels:
            state_label = (
                "CANDIDATO"
                if snapshot.state is OccupancyState.CANDIDATO_OCUPADO
                else estado
            )
            label = f"{snapshot.identifier}: {state_label}"
            font_scale = 0.48
            thickness = 1
            anchor_y = max(16, min(height - 5, max(point[1] for point in points) - 8))
        else:
            label = f"{snapshot.identifier}: {estado}"
            font_scale = 0.55
            thickness = 2
            anchor_y = max(16, min(point[1] for point in points) - 8)
        (text_width, text_height), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness
        )
        anchor_x = min(
            min(point[0] for point in points),
            max(0, width - text_width - 8),
        )
        if compact_labels:
            cv2.rectangle(
                display,
                (anchor_x, max(0, anchor_y - text_height - baseline - 4)),
                (anchor_x + text_width + 6, anchor_y + 3),
                (20, 20, 20),
                cv2.FILLED,
            )
        cv2.putText(
            display, label, (anchor_x + (3 if compact_labels else 0), anchor_y),
            cv2.FONT_HERSHEY_SIMPLEX, font_scale, (8, 10, 14), thickness + 2, cv2.LINE_AA,
        )
        cv2.putText(
            display, label, (anchor_x + (3 if compact_labels else 0), anchor_y),
            cv2.FONT_HERSHEY_SIMPLEX, font_scale, color_estado, thickness, cv2.LINE_AA,
        )


def render_frame(
    frame,
    result,
    snapshots: tuple[ZoneSnapshot, ...],
    source_fps: float,
    processed_fps: float,
    inference_ms: float,
    end_to_end_ms: float,
    validation_ms: float,
    minimum_confidence: float,
    imgsz: int,
    confidence: float,
    input_status: str | None,
    static_image: bool = False,
    detections: list[VehicleDetection] | None = None,
    simulation_status: tuple[str, str] | None = None,
):
    """Render raw YOLO boxes plus independently colored stabilized zone states."""
    detections = detections if detections is not None else (
        detections_from_result(result) if result is not None else []
    )
    display = draw_vehicle_detections(frame, detections)
    box_count = len(detections)
    if result is not None and box_count == 0 and not static_image:
        cv2.putText(
            display, "No raw vehicle detections", (12, 132),
            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 200, 255), 2, cv2.LINE_AA,
        )
    if input_status:
        cv2.putText(
            display, f"Input held: {input_status}; occupancy history unchanged",
            (12, 158), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 0, 255), 2, cv2.LINE_AA,
        )

    if static_image:
        lines = (
            f"Still image {frame.shape[1]}x{frame.shape[0]} | "
            f"{box_count} vehicle boxes | camera FPS: N/A",
            f"Inference {inference_ms:.1f} ms | end-to-end {end_to_end_ms:.1f} ms | "
            f"validation {validation_ms:.3f} ms",
            f"imgsz={imgsz} YOLO conf={confidence:.2f} | temporal min={minimum_confidence:.2f}",
        )
    elif simulation_status is not None:
        lines = (
            *simulation_status,
            f"Simulation {frame.shape[1]}x{frame.shape[0]} | "
            f"{box_count} vehicle boxes | {processed_fps:.1f} YOLO cycles/s",
            f"Inference {inference_ms:.1f} ms | end-to-end {end_to_end_ms:.1f} ms | "
            f"validation {validation_ms:.3f} ms",
            f"imgsz={imgsz} YOLO conf={confidence:.2f} | temporal min={minimum_confidence:.2f}",
        )
    else:
        lines = (
            f"Source {frame.shape[1]}x{frame.shape[0]}: {source_fps:.1f} read FPS | "
            f"YOLO: {processed_fps:.1f} processed FPS",
            f"Inference {inference_ms:.1f} ms | end-to-end {end_to_end_ms:.1f} ms | "
            f"validation {validation_ms:.3f} ms",
            f"imgsz={imgsz} YOLO conf={confidence:.2f} | temporal min={minimum_confidence:.2f}",
        )
    if static_image or simulation_status is not None:
        panel = display.copy()
        line_step = 22
        panel_height = min(
            frame.shape[0] - 1,
            14 + line_step * len(lines),
        )
        cv2.rectangle(
            panel,
            (0, 0),
            (min(frame.shape[1] - 1, 980 if simulation_status is not None else 760), panel_height),
            (15, 15, 15),
            cv2.FILLED,
        )
        cv2.addWeighted(panel, 0.72, display, 0.28, 0.0, display)
    line_start = 22 if static_image or simulation_status is not None else 58
    line_step = 22 if static_image or simulation_status is not None else 24
    for line_index, text in enumerate(lines):
        cv2.putText(
            display,
            text,
            (12, line_start + line_index * line_step),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48 if static_image or simulation_status is not None else 0.55,
            (0, 255, 0),
            1 if static_image or simulation_status is not None else 2,
            cv2.LINE_AA,
        )
    draw_zone_states(
        display,
        snapshots,
        frame.shape[1],
        frame.shape[0],
        compact_labels=static_image or simulation_status is not None,
    )
    return display, box_count


def run_still_image(args: argparse.Namespace) -> int:
    """Display one YOLO-annotated still image until Q or window close."""
    try:
        image_path = args.image.expanduser().resolve()
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"Could not decode image: {image_path}")
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("Still image must decode to a 3-channel BGR image.")

        height, width = frame.shape[:2]
        zones = load_zones(args.zones) if args.zones else None
        validator = TemporalOccupancyValidator(
            zones,
            minimum_confidence=args.minimum_confidence,
            strong_confidence=args.strong_confidence,
            strong_confirmation_frames=args.strong_confirmation_frames,
            weak_confirmation_count=args.weak_confirmation_count,
            weak_confirmation_window=args.weak_confirmation_window,
            release_missing_frames=args.release_missing_frames,
        )

        print(f"Still image opened: {image_path}, resolution={width}x{height}.")
        model_started = time.perf_counter()
        model = load_model()
        print(
            f"Model loaded: {MODEL_PATH} ({time.perf_counter() - model_started:.2f}s); "
            "device=cpu; classes=car,motorcycle,bus,truck."
        )
        print(
            "Zone mode: whole-frame temporal demo only; no parking stall is calibrated."
            if validator.demo_mode
            else f"Zone mode: {len(validator.zones)} calibrated polygons loaded from {args.zones}."
        )

        processing_started = time.perf_counter()
        frame_guard = FrameQualityGuard()
        frame_check_started = time.perf_counter()
        frame_valid, frame_reason = frame_guard.inspect(frame)
        frame_guard_ms = (time.perf_counter() - frame_check_started) * 1000.0
        result = None
        detections: list[VehicleDetection] = []
        inference_ms = 0.0
        predict_call_ms = 0.0
        if frame_valid:
            result, predict_call_ms, inference_ms = predict(
                model, frame, args.imgsz, args.conf
            )
            detections = detections_from_result(result)
            temporal_started = time.perf_counter()
            snapshots = validator.process_frame(detections, width, height, valid=True)
        else:
            temporal_started = time.perf_counter()
            snapshots = validator.process_frame([], width, height, valid=False)
        temporal_ms = (time.perf_counter() - temporal_started) * 1000.0
        end_to_end_ms = (time.perf_counter() - processing_started) * 1000.0
        input_status = None if frame_valid else (frame_reason or "invalid image")

        display, box_count = render_frame(
            frame,
            result,
            snapshots,
            0.0,
            0.0,
            inference_ms,
            end_to_end_ms,
            frame_guard_ms + temporal_ms,
            args.minimum_confidence,
            args.imgsz,
            args.conf,
            input_status,
            static_image=True,
            detections=detections,
        )
        print(
            f"Image inference: detections={box_count}, "
            f"predict_call={predict_call_ms:.1f}ms, model_inference={inference_ms:.1f}ms, "
            f"end_to_end={end_to_end_ms:.1f}ms."
        )
        for detection in detections:
            print(
                f"Vehicle: {detection.class_name}, "
                f"confidence={detection.confidence:.3f} "
                f"({detection.confidence * 100:.1f}%)."
            )
        for snapshot in snapshots:
            if not snapshot.is_demo:
                print(f"Zone {snapshot.identifier}: {snapshot.state.value}.")
        if detections:
            print("Detection labels show confidence as a fraction; 0.87 means 87%.")
        if args.headless:
            return 0

        print("Press Q in the preview to close it.")
        cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_AUTOSIZE)
        while True:
            cv2.imshow(WINDOW_TITLE, display)
            key = cv2.waitKey(20) & 0xFF
            if key in (ord("q"), ord("Q")):
                return 0
            try:
                if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                    return 0
            except cv2.error:
                return 0
    except Exception as error:
        print(
            f"Still-image detection failed ({error.__class__.__name__}): {error}",
            file=sys.stderr,
        )
        return 1
    finally:
        cv2.destroyAllWindows()


def log_state_changes(
    previous: tuple[ZoneSnapshot, ...], current: tuple[ZoneSnapshot, ...]
) -> None:
    """Print only stabilized zone-state transitions for the simulation log."""
    old_states = {snapshot.identifier: snapshot.state for snapshot in previous}
    for snapshot in current:
        previous_state = old_states.get(snapshot.identifier)
        if previous_state is not None and previous_state is not snapshot.state:
            print(
                f"slot {snapshot.identifier} changed: "
                f"{previous_state.value} -> {snapshot.state.value}",
                flush=True,
            )


def simulation_window_closed() -> bool:
    try:
        return cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True


def run_simulation(args: argparse.Namespace) -> int:
    """Play image files as repeated pseudo-video frames through YOLO and validation."""
    processed_frames = 0
    inference_errors = 0
    invalid_frames = 0
    inference_total_ms = 0.0
    predict_call_total_ms = 0.0
    end_to_end_total_ms = 0.0
    run_started = 0.0
    cycles_by_frame: dict[str, int] = {}
    detections_by_frame: dict[str, list[int]] = {}
    exit_reason = "error"
    publicador: PublicadorVision | None = None

    try:
        sequence = build_simulation_sequence(
            args.simulation_dir,
            args.frame_duration,
            args.frame_duration_override,
        )
        images: list[np.ndarray] = []
        expected_size: tuple[int, int] | None = None
        for item in sequence:
            image = cv2.imread(str(item.path), cv2.IMREAD_COLOR)
            if image is None or image.ndim != 3 or image.shape[2] != 3:
                raise ValueError(f"Could not decode a 3-channel image: {item.path}")
            actual_size = (image.shape[1], image.shape[0])
            if expected_size is None:
                expected_size = actual_size
            elif actual_size != expected_size:
                raise ValueError(
                    f"Simulation frame {item.path.name} is {actual_size[0]}x{actual_size[1]}; "
                    f"expected {expected_size[0]}x{expected_size[1]} like the other frames."
                )
            images.append(image)

        publicador = iniciar_publicador_vision(args)
        zones = load_zones(args.zones) if args.zones else None
        validator = TemporalOccupancyValidator(
            zones,
            minimum_confidence=args.minimum_confidence,
            strong_confidence=args.strong_confidence,
            strong_confirmation_frames=args.strong_confirmation_frames,
            weak_confirmation_count=args.weak_confirmation_count,
            weak_confirmation_window=args.weak_confirmation_window,
            release_missing_frames=args.release_missing_frames,
        )
        previous_snapshots = validator.snapshots()
        frame_guard = FrameQualityGuard()

        print(
            f"Simulation ready: {len(sequence)} frames, "
            f"resolution={expected_size[0]}x{expected_size[1]}, "
            f"default_duration={args.frame_duration:.2f}s, "
            f"processing_limit={args.playback_fps:.2f} FPS, "
            f"loop={'off' if args.no_loop else 'on'}."
        )
        for item in sequence:
            if item.duration_seconds != args.frame_duration:
                print(
                    f"Frame timing override: {item.path.name}="
                    f"{item.duration_seconds:.2f}s."
                )
        print(
            "Zone mode: whole-frame temporal demo only; no parking stall is calibrated."
            if validator.demo_mode
            else f"Zone mode: {len(validator.zones)} calibrated polygons loaded from {args.zones}."
        )
        model_started = time.perf_counter()
        model = load_model()
        print(
            f"Model loaded: {MODEL_PATH} ({time.perf_counter() - model_started:.2f}s); "
            "device=cpu; classes=car,motorcycle,bus,truck."
        )

        if not args.headless:
            cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_AUTOSIZE)
        run_started = time.perf_counter()
        playlist_index = 0
        loop_number = 1
        running = True
        last_inference_error: str | None = None
        cycle_period = 1.0 / args.playback_fps

        while running:
            item = sequence[playlist_index]
            frame = images[playlist_index]
            first_cycle = True
            frame_started: float | None = None
            frame_deadline: float | None = None
            frame_cycles = 0
            print(
                f"Playing {item.path.name} ({playlist_index + 1} / {len(sequence)}) "
                f"for {item.duration_seconds:.2f}s; loop {loop_number}.",
                flush=True,
            )

            while first_cycle or (
                (not args.headless or not args.no_loop)
                and frame_deadline is not None
                and time.perf_counter() < frame_deadline
            ):
                cycle_started = time.perf_counter()
                frame_check_started = time.perf_counter()
                frame_valid, frame_reason = frame_guard.inspect(
                    frame, allow_repeated=True
                )
                frame_guard_ms = (time.perf_counter() - frame_check_started) * 1000.0
                result = None
                detections: list[VehicleDetection] = []
                inference_ms = 0.0
                predict_call_ms = 0.0
                input_status = None if frame_valid else (frame_reason or "invalid image")
                temporal_started = time.perf_counter()
                inferencia_valida = False

                if frame_valid:
                    try:
                        result, predict_call_ms, inference_ms = predict(
                            model, frame, args.imgsz, args.conf
                        )
                        detections = detections_from_result(result)
                    except Exception as error:
                        result = None
                        detections = []
                        inference_errors += 1
                        input_status = f"inference error ({error.__class__.__name__})"
                        snapshots = validator.snapshots()
                        error_type = error.__class__.__name__
                        if error_type != last_inference_error:
                            print(
                                f"YOLO inference failed on {item.path.name} "
                                f"({error_type}); occupancy history held.",
                                file=sys.stderr,
                                flush=True,
                            )
                        last_inference_error = error_type
                    else:
                        last_inference_error = None
                        inferencia_valida = True
                        snapshots = validator.process_frame(
                            detections, frame.shape[1], frame.shape[0], valid=True
                        )
                        log_state_changes(previous_snapshots, snapshots)
                        previous_snapshots = snapshots
                        processed_frames += 1
                        inference_total_ms += inference_ms
                        predict_call_total_ms += predict_call_ms
                        cycles_by_frame[item.path.name] = (
                            cycles_by_frame.get(item.path.name, 0) + 1
                        )
                        detections_by_frame.setdefault(item.path.name, []).append(
                            len(detections)
                        )
                else:
                    invalid_frames += 1
                    snapshots = validator.process_frame(
                        [], frame.shape[1], frame.shape[0], valid=False
                    )

                if publicador is not None:
                    publicador.avanzar(
                        snapshots,
                        inferencia_valida=inferencia_valida,
                    )

                temporal_ms = (time.perf_counter() - temporal_started) * 1000.0
                end_to_end_ms = (time.perf_counter() - cycle_started) * 1000.0
                if result is not None:
                    end_to_end_total_ms += end_to_end_ms
                frame_cycles += 1
                elapsed_total = max(time.perf_counter() - run_started, 1e-9)
                processed_fps = processed_frames / elapsed_total
                elapsed_in_frame = (
                    0.0
                    if frame_started is None
                    else min(
                        time.perf_counter() - frame_started,
                        item.duration_seconds,
                    )
                )
                simulation_status = (
                    f"SIMULATION MODE | {item.path.name} | "
                    f"{playlist_index + 1} / {len(sequence)} | loop {loop_number}",
                    f"Frame elapsed {elapsed_in_frame:.1f} / "
                    f"{item.duration_seconds:.1f} s | cycle {frame_cycles}",
                )
                display, _ = render_frame(
                    frame,
                    result,
                    snapshots,
                    0.0,
                    processed_fps,
                    inference_ms,
                    end_to_end_ms,
                    frame_guard_ms + temporal_ms,
                    args.minimum_confidence,
                    args.imgsz,
                    args.conf,
                    input_status,
                    detections=detections,
                    simulation_status=simulation_status,
                )
                if not args.headless:
                    cv2.imshow(WINDOW_TITLE, display)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), ord("Q")):
                        running = False
                        exit_reason = "Q"
                        break
                    if not args.headless and simulation_window_closed():
                        running = False
                        exit_reason = "window closed"
                        break

                if first_cycle:
                    frame_started = time.perf_counter()
                    frame_deadline = frame_started + item.duration_seconds
                    next_cycle = frame_started + cycle_period
                    first_cycle = False
                else:
                    next_cycle = cycle_started + cycle_period
                while running and not (args.headless and args.no_loop):
                    now = time.perf_counter()
                    if frame_deadline is None:
                        break
                    wait_until = min(next_cycle, frame_deadline)
                    remaining = wait_until - now
                    if remaining <= 0:
                        break
                    wait_ms = max(1, min(50, math.ceil(remaining * 1000.0)))
                    key = cv2.waitKey(wait_ms) & 0xFF
                    if key in (ord("q"), ord("Q")):
                        running = False
                        exit_reason = "Q"
                        break
                    if not args.headless and simulation_window_closed():
                        running = False
                        exit_reason = "window closed"
                        break

            if not running:
                break
            next_index = next_frame_index(
                playlist_index, len(sequence), loop=not args.no_loop
            )
            if next_index is None:
                print("Simulation sequence completed once (--no-loop).")
                exit_reason = "sequence complete"
                break
            if next_index == 0:
                loop_number += 1
                print(
                    f"Simulation loop {loop_number - 1} complete; "
                    "restarting at frame_001.png.",
                    flush=True,
                )
            playlist_index = next_index

        return 0
    except Exception as error:
        print(
            f"Simulation playback failed ({error.__class__.__name__}): {error}",
            file=sys.stderr,
        )
        return 1
    finally:
        cv2.destroyAllWindows()
        print(
            f"Simulation stopped ({exit_reason}); "
            + ("headless mode." if args.headless else "OpenCV windows closed.")
        )
        if processed_frames:
            elapsed = max(time.perf_counter() - run_started, 1e-9)
            print(
                "Simulation metrics: "
                f"processed_cycles={processed_frames}, "
                f"avg_processed_fps={processed_frames / elapsed:.2f}, "
                f"avg_model_inference_ms={inference_total_ms / processed_frames:.2f}, "
                f"avg_predict_call_ms={predict_call_total_ms / processed_frames:.2f}, "
                f"avg_cycle_end_to_end_ms={end_to_end_total_ms / processed_frames:.2f}, "
                f"inference_errors={inference_errors}, invalid_frames={invalid_frames}."
            )
            print(
                "Successful processing cycles by image: "
                + ", ".join(
                    f"{name}={count}" for name, count in cycles_by_frame.items()
                )
                + "."
            )
            print(
                "Vehicle detections per image (min-max over processing cycles): "
                + ", ".join(
                    f"{name}={min(counts)}-{max(counts)}"
                    for name, counts in detections_by_frame.items()
                )
                + "."
            )


def run(args: argparse.Namespace) -> int:
    if args.simulation_dir is not None:
        return run_simulation(args)
    if args.image is not None:
        return run_still_image(args)

    capture = None
    publicador: PublicadorVision | None = None
    processed_frames = 0
    frames_with_detections = 0
    max_detections = 0
    predict_call_total_ms = 0.0
    inference_total_ms = 0.0
    end_to_end_total_ms = 0.0
    capture_fps = 0.0
    processing_started = 0.0
    loop_fps_started = 0.0
    loop_fps_frames = 0
    processed_fps = 0.0
    preview_frames = 0
    invalid_frames = 0
    frame_guard_ms_total = 0.0
    temporal_ms_total = 0.0
    inference_error_printed = False

    try:
        publicador = iniciar_publicador_vision(args)
        zones = load_zones(args.zones) if args.zones else None
        validator = TemporalOccupancyValidator(
            zones,
            minimum_confidence=args.minimum_confidence,
            strong_confidence=args.strong_confidence,
            strong_confirmation_frames=args.strong_confirmation_frames,
            weak_confirmation_count=args.weak_confirmation_count,
            weak_confirmation_window=args.weak_confirmation_window,
            release_missing_frames=args.release_missing_frames,
        )
        capture, source_name, backend_name, frame = open_video_source(
            args.source, args.http_url, args.camera_index, args.backend
        )
        actual_size = (frame.shape[1], frame.shape[0])
        validate_frame(frame, source_name)
        print(
            f"Video source opened: {source_name}, backend={backend_name}, "
            f"resolution={actual_size[0]}x{actual_size[1]}."
        )

        model_started = time.perf_counter()
        model = load_model()
        model_load_seconds = time.perf_counter() - model_started
        print(
            f"Model loaded: {MODEL_PATH} ({model_load_seconds:.2f}s); device=cpu; "
            "classes=car,motorcycle,bus,truck."
        )
        print(
            "Temporal validation: "
            f"min={args.minimum_confidence:.2f}, strong={args.strong_confidence:.2f} "
            f"x{args.strong_confirmation_frames}, weak={args.weak_confirmation_count}/"
            f"{args.weak_confirmation_window}, release={args.release_missing_frames}."
        )
        print(
            "Zone mode: whole-frame temporal demo only; no parking stall is calibrated."
            if validator.demo_mode
            else f"Zone mode: {len(validator.zones)} calibrated polygons loaded from {args.zones}."
        )

        capture_fps, frame, sample_count, sample_seconds = measure_capture_rate(
            capture, frame, CAPTURE_SAMPLE_SECONDS, source_name
        )
        print(
            f"Source-only sample: {sample_count} frames in {sample_seconds:.2f}s, "
            f"{capture_fps:.2f} FPS at {CAPTURE_WIDTH}x{CAPTURE_HEIGHT}."
        )

        model_warmed = not is_blank_frame(frame)
        if model_warmed:
            warmup_result, warmup_call_ms, warmup_inference_ms = predict(
                model, frame, args.imgsz, args.conf
            )
            print(
                f"Warmup excluded from averages: predict_call={warmup_call_ms:.1f}ms, "
                f"model_inference={warmup_inference_ms:.1f}ms."
            )
            _ = warmup_result
        else:
            print(
                "Warmup deferred: DroidCam returned an all-black frame; "
                "YOLO inference will wait for image content."
            )

        frame_guard = FrameQualityGuard()
        frame_guard.inspect(frame)
        if not args.headless:
            cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_AUTOSIZE)
        processing_started = time.perf_counter()
        loop_fps_started = processing_started
        latest_end_to_end_ms = 0.0

        while True:
            end_to_end_started = time.perf_counter()
            frame = read_frame(capture, source_name)
            frame_check_started = time.perf_counter()
            frame_valid, frame_reason = frame_guard.inspect(frame)
            frame_guard_ms = (time.perf_counter() - frame_check_started) * 1000.0
            frame_guard_ms_total += frame_guard_ms

            result = None
            predict_call_ms = 0.0
            inference_ms = 0.0
            detections: list[VehicleDetection] = []
            input_status = None
            temporal_ms = 0.0
            inferencia_valida = False

            if not frame_valid:
                invalid_frames += 1
                input_status = frame_reason or "invalid frame"
                temporal_started = time.perf_counter()
                snapshots = validator.process_frame(
                    [], frame.shape[1], frame.shape[0], valid=False
                )
                temporal_ms = (time.perf_counter() - temporal_started) * 1000.0
            elif not model_warmed:
                warmup_started = time.perf_counter()
                try:
                    _, warmup_call_ms, warmup_inference_ms = predict(
                        model, frame, args.imgsz, args.conf
                    )
                except Exception as error:
                    input_status = f"inference error ({error.__class__.__name__})"
                    snapshots = validator.snapshots()
                else:
                    model_warmed = True
                    snapshots = validator.snapshots()
                    print(
                        f"Warmup completed when POCO image appeared "
                        f"({time.perf_counter() - warmup_started:.2f}s; "
                        f"predict_call={warmup_call_ms:.1f}ms, "
                        f"model_inference={warmup_inference_ms:.1f}ms)."
                    )
                    _ = warmup_inference_ms
            else:
                try:
                    result, predict_call_ms, inference_ms = predict(
                        model, frame, args.imgsz, args.conf
                    )
                except Exception as error:
                    input_status = f"inference error ({error.__class__.__name__})"
                    snapshots = validator.snapshots()
                    if not inference_error_printed:
                        print(
                            f"YOLO inference unavailable for this frame "
                            f"({error.__class__.__name__}); occupancy history held.",
                            file=sys.stderr,
                        )
                        inference_error_printed = True
                else:
                    inference_error_printed = False
                    inferencia_valida = True
                    detections = detections_from_result(result)
                    temporal_started = time.perf_counter()
                    snapshots = validator.process_frame(
                        detections, frame.shape[1], frame.shape[0], valid=True
                    )
                    temporal_ms = (time.perf_counter() - temporal_started) * 1000.0
                    processed_frames += 1
                    loop_fps_frames += 1
                    predict_call_total_ms += predict_call_ms
                    inference_total_ms += inference_ms

            if publicador is not None:
                publicador.avanzar(
                    snapshots,
                    inferencia_valida=inferencia_valida,
                )

            temporal_ms_total += temporal_ms
            if result is not None:
                box_count = len(result.boxes) if result.boxes is not None else 0
                max_detections = max(max_detections, box_count)
                if box_count:
                    frames_with_detections += 1

            display, box_count = render_frame(
                frame,
                result,
                snapshots,
                capture_fps,
                processed_fps,
                inference_ms,
                latest_end_to_end_ms,
                frame_guard_ms + temporal_ms,
                args.minimum_confidence,
                args.imgsz,
                args.conf,
                input_status,
                detections=detections,
            )
            key: int | None = None
            if not args.headless:
                cv2.imshow(WINDOW_TITLE, display)
                key = cv2.waitKey(1) & 0xFF
            latest_end_to_end_ms = (time.perf_counter() - end_to_end_started) * 1000.0
            preview_frames += 1
            if result is not None:
                end_to_end_total_ms += latest_end_to_end_ms

            fps_elapsed = time.perf_counter() - loop_fps_started
            if fps_elapsed >= 1.0:
                processed_fps = loop_fps_frames / fps_elapsed
                loop_fps_frames = 0
                loop_fps_started = time.perf_counter()

            if key in (ord("q"), ord("Q")):
                return 0
            if not args.headless:
                try:
                    if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                        return 0
                except cv2.error:
                    return 0

    except Exception as error:
        print(f"Detection run failed ({error.__class__.__name__}): {error}", file=sys.stderr)
        return 1
    finally:
        if capture is not None:
            capture.release()
        cv2.destroyAllWindows()
        if capture is not None and not args.headless:
            print("Camera released; OpenCV windows closed.")
        elif capture is not None:
            print("Video source released in headless mode.")
        if processed_frames:
            elapsed = time.perf_counter() - processing_started
            print(
                "Live metrics: "
                f"source_read_fps={capture_fps:.2f}, "
                f"processed_fps={processed_frames / elapsed:.2f}, "
                f"avg_model_inference_ms={inference_total_ms / processed_frames:.2f}, "
                f"avg_predict_call_ms={predict_call_total_ms / processed_frames:.2f}, "
                f"avg_end_to_end_ms={end_to_end_total_ms / processed_frames:.2f}, "
                f"frames={processed_frames}, "
                f"frames_with_detections={frames_with_detections}, "
                f"max_detections_per_frame={max_detections}."
            )
        if preview_frames:
            print(
                "Validation overhead: "
                f"avg_frame_quality_check_ms={frame_guard_ms_total / preview_frames:.4f}, "
                f"avg_temporal_and_spatial_ms={temporal_ms_total / preview_frames:.4f}, "
                f"invalid_frames={invalid_frames}, preview_frames={preview_frames}."
            )


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
