"""Display a local camera feed for the Smart Parking Vision prototype."""

from __future__ import annotations

import argparse
import sys
import time

import cv2

MAX_CAMERA_INDEX = 9
CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720
CAPTURE_SIZE = (CAPTURE_WIDTH, CAPTURE_HEIGHT)
DEFAULT_HTTP_URL = "http://127.0.0.1:4747/video"
HTTP_OPEN_TIMEOUT_MS = 5000
HTTP_READ_TIMEOUT_MS = 5000
WINDOW_TITLE = "Smart Parking Vision - Camera Capture"
BACKENDS = {
    "dshow": ("DirectShow", cv2.CAP_DSHOW),
    "msmf": ("Media Foundation", cv2.CAP_MSMF),
}


def validate_frame(frame: object, source_name: str) -> None:
    """Reject empty, malformed, or unexpected-resolution video frames."""
    if frame is None or not hasattr(frame, "shape") or len(frame.shape) < 2:
        raise RuntimeError(f"{source_name} returned an empty or malformed frame.")
    height, width = frame.shape[:2]
    if len(frame.shape) != 3 or frame.shape[2] != 3:
        raise RuntimeError(
            f"{source_name} returned an unsupported frame format; expected 3-channel BGR."
        )
    if (width, height) != CAPTURE_SIZE:
        raise RuntimeError(
            f"{source_name} frame changed size: required "
            f"{CAPTURE_WIDTH}x{CAPTURE_HEIGHT}, received {width}x{height}."
        )


def read_frame(capture: cv2.VideoCapture, source_name: str) -> object:
    """Read and validate one frame, reporting stream failures with source context."""
    try:
        ok, frame = capture.read()
    except cv2.error as error:
        raise RuntimeError(
            f"{source_name} read failed ({error.__class__.__name__})."
        ) from error
    if not ok:
        raise RuntimeError(f"{source_name} stopped returning frames.")
    validate_frame(frame, source_name)
    return frame


def backend_order(selection: str) -> list[tuple[str, int]]:
    if selection == "auto":
        return list(BACKENDS.values())
    return [BACKENDS[selection]]


def camera_indices(selection: int | None) -> range | tuple[int]:
    if selection is None:
        return range(MAX_CAMERA_INDEX + 1)
    return (selection,)


def open_camera(
    index: int | None, backend: str
) -> tuple[cv2.VideoCapture, int, str, object]:
    failures: list[str] = []
    for backend_name, backend_id in backend_order(backend):
        for camera_index in camera_indices(index):
            try:
                capture = cv2.VideoCapture(camera_index, backend_id)
            except cv2.error as error:
                failures.append(
                    f"index {camera_index} via {backend_name}: {error.__class__.__name__}"
                )
                continue
            if not capture.isOpened():
                capture.release()
                failures.append(f"index {camera_index} via {backend_name}: open failed")
                continue

            try:
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
                ok, frame = capture.read()
            except cv2.error as error:
                capture.release()
                failures.append(
                    f"index {camera_index} via {backend_name}: {error.__class__.__name__}"
                )
                continue
            if not ok or frame is None:
                capture.release()
                failures.append(f"index {camera_index} via {backend_name}: no frame")
                continue

            actual_size = (frame.shape[1], frame.shape[0])
            if actual_size != CAPTURE_SIZE:
                capture.release()
                actual_width, actual_height = actual_size
                failures.append(
                    f"index {camera_index} via {backend_name}: requested "
                    f"{CAPTURE_WIDTH}x{CAPTURE_HEIGHT}, received "
                    f"{actual_width}x{actual_height}"
                )
                continue

            return capture, camera_index, backend_name, frame

    tried = ", ".join(failures) or "no camera candidates"
    scope = (
        f"camera indices 0-{MAX_CAMERA_INDEX}"
        if index is None
        else f"camera index {index}"
    )
    raise RuntimeError(
        f"No readable {CAPTURE_WIDTH}x{CAPTURE_HEIGHT} frame was received from "
        f"{scope}. Attempts: {tried}. Confirm that the selected DroidCam Video "
        "source is active and retry."
    )


def open_http_source(url: str) -> tuple[cv2.VideoCapture, str, str, object]:
    """Open the DroidCam USB HTTP stream with bounded FFmpeg timeouts."""
    if not url.lower().startswith(("http://", "https://")):
        raise RuntimeError("The video source URL must use http:// or https://.")

    capture = cv2.VideoCapture()
    try:
        opened = capture.open(
            url,
            cv2.CAP_FFMPEG,
            [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                HTTP_OPEN_TIMEOUT_MS,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                HTTP_READ_TIMEOUT_MS,
            ],
        )
    except cv2.error as error:
        capture.release()
        raise RuntimeError(
            f"Could not open HTTP video source ({error.__class__.__name__})."
        ) from error

    if not opened or not capture.isOpened():
        capture.release()
        raise RuntimeError(
            f"Could not open HTTP video source {url}. Confirm DroidCam USB and "
            "the local ADB forward on port 4747 are active."
        )

    source_name = f"HTTP source {url}"
    try:
        frame = read_frame(capture, source_name)
    except Exception:
        capture.release()
        raise
    return capture, source_name, "FFmpeg", frame


def open_video_source(
    source: str,
    http_url: str,
    camera_index: int | None,
    backend: str,
) -> tuple[cv2.VideoCapture, str, str, object]:
    """Open an explicit HTTP or local camera source without probing other devices."""
    if source == "http":
        return open_http_source(http_url)
    selected_index = 1 if camera_index is None else camera_index
    capture, actual_index, backend_name, frame = open_camera(
        selected_index, backend
    )
    return capture, f"camera index {actual_index}", backend_name, frame


def list_cameras() -> int:
    found = False
    for backend_name, backend_id in backend_order("auto"):
        for camera_index in camera_indices(None):
            try:
                capture = cv2.VideoCapture(camera_index, backend_id)
            except cv2.error:
                continue
            try:
                if not capture.isOpened():
                    continue
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
                try:
                    ok, frame = capture.read()
                except cv2.error:
                    continue
                if not ok or frame is None:
                    continue
                height, width = frame.shape[:2]
                print(
                    f"index={camera_index} backend={backend_name} "
                    f"requested={CAPTURE_WIDTH}x{CAPTURE_HEIGHT} "
                    f"resolution={width}x{height}"
                )
                found = True
            finally:
                capture.release()

    if not found:
        print("No readable cameras found at indices 0-9.")
        return 1
    print("Run with --camera-index N to select the DroidCam index.")
    return 0


def run(source: str, http_url: str, camera_index: int | None, backend: str) -> int:
    capture, source_name, backend_name, frame = open_video_source(
        source, http_url, camera_index, backend
    )
    measured_fps = 0.0
    fps_window_start = time.perf_counter()
    fps_window_frames = 0

    print(
        f"Video source opened: {source_name}, backend={backend_name}, "
        f"resolution={CAPTURE_WIDTH}x{CAPTURE_HEIGHT}. "
        "Press Q in the video window to quit."
    )

    try:
        cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_AUTOSIZE)
        while True:
            now = time.perf_counter()
            fps_window_frames += 1
            elapsed = now - fps_window_start
            if elapsed >= 1.0:
                measured_fps = fps_window_frames / elapsed
                fps_window_frames = 0
                fps_window_start = now

            height, width = frame.shape[:2]
            display_frame = frame.copy()
            cv2.putText(
                display_frame,
                f"{width}x{height} | {measured_fps:.1f} FPS",
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(WINDOW_TITLE, display_frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q")):
                return 0

            try:
                if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                    return 0
            except cv2.error:
                return 0

            try:
                next_frame = read_frame(capture, source_name)
            except RuntimeError as error:
                print(str(error), file=sys.stderr)
                return 1
            frame = next_frame
    finally:
        capture.release()
        cv2.destroyAllWindows()
        print("Camera released; OpenCV windows closed.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("http", "camera"),
        help="video source (default: HTTP unless legacy camera options are supplied)",
    )
    parser.add_argument(
        "--http-url",
        default=DEFAULT_HTTP_URL,
        help=f"DroidCam HTTP video URL (default: {DEFAULT_HTTP_URL})",
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        help=f"local camera index to use (default: 1 when --source camera is selected)",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "dshow", "msmf"),
        default=None,
        help="OpenCV backend for --source camera (default: auto)",
    )
    parser.add_argument(
        "--list-cameras",
        action="store_true",
        help="probe indices 0-9 with both backends, then exit",
    )
    args = parser.parse_args()
    if args.camera_index is not None and not 0 <= args.camera_index <= MAX_CAMERA_INDEX:
        parser.error(f"--camera-index must be between 0 and {MAX_CAMERA_INDEX}")
    legacy_camera_selection = args.camera_index is not None or args.backend is not None
    if args.source is None:
        args.source = "camera" if legacy_camera_selection else "http"
    if args.source == "http" and legacy_camera_selection:
        parser.error("--camera-index/--backend cannot be combined with --source http")
    if args.backend is None:
        args.backend = "auto"
    return args


def main() -> int:
    args = parse_args()
    try:
        if args.list_cameras:
            return list_cameras()
        return run(args.source, args.http_url, args.camera_index, args.backend)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    except cv2.error as error:
        print(f"OpenCV runtime error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
