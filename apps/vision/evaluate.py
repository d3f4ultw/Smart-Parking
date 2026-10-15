"""Run repeatable offline YOLO vehicle-detection comparisons on local images."""

from __future__ import annotations

import argparse
import json
import platform
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import torch
import ultralytics
from ultralytics import YOLO

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL = PROJECT_DIR / "models" / "yolo26n.pt"
VEHICLE_CLASS_NAMES = {
    "car",
    "motorcycle",
    "bus",
    "truck",
    "van",
    "small vehicle",
    "large vehicle",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        action="append",
        required=True,
        help="local image path; repeat this option to evaluate multiple images",
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument(
        "--class-ids",
        type=int,
        nargs="+",
        help="override automatic vehicle class selection for this model",
    )
    parser.add_argument("--imgsz", type=int, nargs="+", default=[640, 960, 1280])
    parser.add_argument("--conf", type=float, nargs="+", default=[0.10, 0.25])
    parser.add_argument(
        "--tile-size",
        type=int,
        help="also evaluate square overlapping crops of this pixel size",
    )
    parser.add_argument("--tile-overlap", type=float, default=0.20)
    parser.add_argument("--nms-iou", type=float, default=0.50)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    if any(size < 32 for size in args.imgsz):
        parser.error("--imgsz values must be at least 32")
    if any(not 0.0 <= confidence <= 1.0 for confidence in args.conf):
        parser.error("--conf values must be between 0 and 1")
    if args.tile_size is not None and args.tile_size < 32:
        parser.error("--tile-size must be at least 32")
    if not 0.0 <= args.tile_overlap < 1.0:
        parser.error("--tile-overlap must be in [0, 1)")
    if not 0.0 < args.nms_iou <= 1.0:
        parser.error("--nms-iou must be in (0, 1]")
    return args


def image_positions(length: int, tile_size: int, stride: int) -> list[int]:
    if length <= tile_size:
        return [0]
    positions = [0]
    while positions[-1] + tile_size < length:
        next_position = min(positions[-1] + stride, length - tile_size)
        if next_position == positions[-1]:
            break
        positions.append(next_position)
    return positions


def tile_origins(width: int, height: int, tile_size: int, overlap: float):
    stride = max(1, int(tile_size * (1.0 - overlap)))
    x_positions = image_positions(width, tile_size, stride)
    y_positions = image_positions(height, tile_size, stride)
    return [(x, y) for y in y_positions for x in x_positions]


def extract_detections(result, offset_x: int = 0, offset_y: int = 0):
    boxes_object = result.obb if result.obb is not None else result.boxes
    if boxes_object is None or len(boxes_object) == 0:
        return []
    boxes = boxes_object.xyxy.cpu().numpy()
    classes = boxes_object.cls.cpu().numpy().astype(int)
    confidences = boxes_object.conf.cpu().numpy()
    detections = []
    for box, class_id, confidence in zip(boxes, classes, confidences):
        x1, y1, x2, y2 = box.tolist()
        detections.append(
            {
                "class_id": int(class_id),
                "class_name": str(result.names.get(int(class_id), class_id)),
                "confidence": float(confidence),
                "box_xyxy": [
                    round(x1 + offset_x, 2),
                    round(y1 + offset_y, 2),
                    round(x2 + offset_x, 2),
                    round(y2 + offset_y, 2),
                ],
            }
        )
    return detections


def box_iou(first: list[float], second: list[float]) -> float:
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def suppress_tile_duplicates(detections: list[dict], iou_threshold: float):
    ordered = sorted(detections, key=lambda item: item["confidence"], reverse=True)
    kept: list[dict] = []
    for candidate in ordered:
        duplicate = any(
            candidate["class_id"] == existing["class_id"]
            and box_iou(candidate["box_xyxy"], existing["box_xyxy"]) >= iou_threshold
            for existing in kept
        )
        if not duplicate:
            kept.append(candidate)
    return kept


def predict_one(
    model: YOLO,
    image: np.ndarray,
    imgsz: int,
    confidence: float,
    class_ids: tuple[int, ...],
):
    started = time.perf_counter()
    result = model.predict(
        source=image,
        imgsz=imgsz,
        conf=confidence,
        classes=list(class_ids),
        device="cpu",
        verbose=False,
    )[0]
    predict_call_ms = (time.perf_counter() - started) * 1000.0
    inference_ms = float(result.speed.get("inference", predict_call_ms))
    return result, predict_call_ms, inference_ms


def annotate(image: np.ndarray, detections: list[dict]) -> np.ndarray:
    output = image.copy()
    for detection in detections:
        x1, y1, x2, y2 = (int(round(value)) for value in detection["box_xyxy"])
        label = f"{detection['class_name']} {detection['confidence']:.2f}"
        cv2.rectangle(output, (x1, y1), (x2, y2), (0, 220, 0), 2)
        text_size, baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2
        )
        top = max(0, y1 - text_size[1] - baseline - 4)
        cv2.rectangle(
            output,
            (x1, top),
            (x1 + text_size[0] + 6, top + text_size[1] + baseline + 4),
            (0, 220, 0),
            cv2.FILLED,
        )
        cv2.putText(
            output,
            label,
            (x1 + 3, top + text_size[1] + 1),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 0),
            2,
            cv2.LINE_AA,
        )
    return output


def safe_stem(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", path.stem).strip("_.") or "image"


def select_vehicle_class_ids(model: YOLO, override: list[int] | None) -> tuple[int, ...]:
    if override:
        return tuple(override)
    names = model.names
    selected = []
    for raw_id, raw_name in names.items():
        normalized = re.sub(r"[_-]+", " ", str(raw_name).lower()).strip()
        if normalized in VEHICLE_CLASS_NAMES:
            selected.append(int(raw_id))
    if not selected:
        raise RuntimeError(
            "No vehicle classes matched this model's label names. "
            "Supply the appropriate --class-ids for this checkpoint."
        )
    return tuple(selected)


def save_result(
    image: np.ndarray,
    detections: list[dict],
    output_dir: Path,
    stem: str,
    metadata: dict,
) -> dict:
    annotated_path = output_dir / f"{stem}.jpg"
    if not cv2.imwrite(str(annotated_path), annotate(image, detections)):
        raise RuntimeError(f"Could not save annotated image {annotated_path}.")
    return {**metadata, "detections": detections, "annotated_image": str(annotated_path)}


def evaluate_image(
    model: YOLO,
    path: Path,
    output_dir: Path,
    imgsz_values: list[int],
    confidences: list[float],
    class_ids: tuple[int, ...],
    tile_size: int | None,
    tile_overlap: float,
    nms_iou: float,
) -> list[dict]:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not decode image: {path}")
    height, width = image.shape[:2]
    results = []

    for imgsz in imgsz_values:
        for confidence in confidences:
            result, predict_call_ms, inference_ms = predict_one(
                model, image, imgsz, confidence, class_ids
            )
            detections = extract_detections(result)
            stem = (
                f"{safe_stem(path)}_full_imgsz{imgsz}_conf{confidence:.2f}"
                .replace(".", "p")
            )
            results.append(
                save_result(
                    image,
                    detections,
                    output_dir,
                    stem,
                    {
                        "image": str(path),
                        "method": "full-frame",
                        "image_resolution": {"width": width, "height": height},
                        "imgsz": imgsz,
                        "confidence_threshold": confidence,
                        "detection_count": len(detections),
                        "predict_call_ms": round(predict_call_ms, 3),
                        "model_inference_ms": round(inference_ms, 3),
                    },
                )
            )

            if tile_size is None:
                continue

            tile_detections = []
            total_call_ms = 0.0
            total_inference_ms = 0.0
            origins = tile_origins(width, height, tile_size, tile_overlap)
            for x, y in origins:
                crop = image[y : min(y + tile_size, height), x : min(x + tile_size, width)]
                tile_result, call_ms, tile_inference_ms = predict_one(
                    model, crop, imgsz, confidence, class_ids
                )
                total_call_ms += call_ms
                total_inference_ms += tile_inference_ms
                tile_detections.extend(extract_detections(tile_result, x, y))

            tile_detections = suppress_tile_duplicates(tile_detections, nms_iou)
            tile_stem = (
                f"{safe_stem(path)}_tiles{tile_size}_imgsz{imgsz}_conf{confidence:.2f}"
                .replace(".", "p")
            )
            results.append(
                save_result(
                    image,
                    tile_detections,
                    output_dir,
                    tile_stem,
                    {
                        "image": str(path),
                        "method": "overlapping-tiles",
                        "image_resolution": {"width": width, "height": height},
                        "tile_size": tile_size,
                        "tile_overlap": tile_overlap,
                        "tile_count": len(origins),
                        "nms_iou": nms_iou,
                        "imgsz": imgsz,
                        "confidence_threshold": confidence,
                        "detection_count": len(tile_detections),
                        "predict_call_ms": round(total_call_ms, 3),
                        "model_inference_ms": round(total_inference_ms, 3),
                    },
                )
            )
    return results


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or PROJECT_DIR / "reports" / f"evaluation-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=False)

    model_path = args.model.resolve()
    if not model_path.is_file():
        raise SystemExit(f"Model checkpoint does not exist: {model_path}")
    images = [Path(value).expanduser().resolve() for value in args.image]
    for path in images:
        if not path.is_file():
            raise SystemExit(f"Image does not exist: {path}")

    model = YOLO(str(model_path))
    class_ids = select_vehicle_class_ids(model, args.class_ids)
    results = []
    for path in images:
        results.extend(
            evaluate_image(
                model,
                path,
                output_dir,
                args.imgsz,
                args.conf,
                class_ids,
                args.tile_size,
                args.tile_overlap,
                args.nms_iou,
            )
        )

    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": str(model_path),
        "runtime": {
            "python": platform.python_version(),
            "opencv": cv2.__version__,
            "ultralytics": ultralytics.__version__,
            "torch": torch.__version__,
            "device": "cpu",
            "task": model.task,
            "vehicle_class_ids": list(class_ids),
            "vehicle_classes": {
                str(class_id): str(model.names[class_id]) for class_id in class_ids
            },
        },
        "results": results,
    }
    json_path = output_dir / "results.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Model: {model_path}")
    print(f"Output directory: {output_dir}")
    print(f"Machine-readable results: {json_path}")
    for result in results:
        print(
            f"{Path(result['image']).name} {result['method']} "
            f"imgsz={result['imgsz']} conf={result['confidence_threshold']:.2f} "
            f"detections={result['detection_count']} "
            f"inference={result['model_inference_ms']:.1f}ms "
            f"predict_call={result['predict_call_ms']:.1f}ms "
            f"annotated={result['annotated_image']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
