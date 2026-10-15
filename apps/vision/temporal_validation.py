"""Spatial and temporal stabilization for vehicle detections."""

from __future__ import annotations

import json
import math
import re
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from numbers import Real
from pathlib import Path
from typing import Any, Iterable

import numpy as np


MINIMUM_CONFIDENCE = 0.30
STRONG_CONFIDENCE = 0.45
STRONG_CONFIRMATION_FRAMES = 2
WEAK_CONFIRMATION_COUNT = 3
WEAK_CONFIRMATION_WINDOW = 5
RELEASE_MISSING_FRAMES = 4
SPATIAL_MATCH_IOU = 0.10
SPATIAL_MATCH_DISTANCE_FRACTION = 0.05
DEMO_ZONE_ID = "WHOLE_FRAME_DEMO"
_DYNAMIC_ZONE_ID_PATTERN = re.compile(r"C([1-9][0-9]*)\Z")


class OccupancyState(str, Enum):
    LIBRE = "LIBRE"
    CANDIDATO_OCUPADO = "CANDIDATO_OCUPADO"
    OCUPADO = "OCUPADO"


@dataclass(frozen=True)
class VehicleDetection:
    """One raw YOLO vehicle detection in source-image pixel coordinates."""

    box_xyxy: tuple[float, float, float, float]
    confidence: float
    class_name: str = "vehicle"

    def __post_init__(self) -> None:
        if len(self.box_xyxy) != 4:
            raise ValueError("A detection box must contain x1, y1, x2, and y2.")
        if not all(math.isfinite(float(value)) for value in self.box_xyxy):
            raise ValueError("Detection box coordinates must be finite.")
        x1, y1, x2, y2 = (float(value) for value in self.box_xyxy)
        if x2 <= x1 or y2 <= y1:
            raise ValueError("Detection boxes must have positive width and height.")
        if not math.isfinite(float(self.confidence)) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Detection confidence must be a finite value from 0 to 1.")


Point = tuple[float, float]


@dataclass(frozen=True)
class ParkingZone:
    """A simple polygon whose vertices use normalized [0, 1] coordinates."""

    identifier: str
    polygon: tuple[Point, ...]

    def __post_init__(self) -> None:
        identifier = self.identifier.strip()
        if not identifier:
            raise ValueError("Every zone must have a non-empty stable id.")
        if len(self.polygon) < 3:
            raise ValueError(f"Zone {identifier!r} must have at least three vertices.")
        normalized: list[Point] = []
        for point in self.polygon:
            if len(point) != 2:
                raise ValueError(f"Zone {identifier!r} vertices must be x/y pairs.")
            x, y = point
            if (
                isinstance(x, bool)
                or isinstance(y, bool)
                or not isinstance(x, Real)
                or not isinstance(y, Real)
            ):
                raise ValueError(f"Zone {identifier!r} coordinates must be numbers.")
            if not math.isfinite(float(x)) or not math.isfinite(float(y)):
                raise ValueError(f"Zone {identifier!r} coordinates must be finite.")
            if not 0.0 <= float(x) <= 1.0 or not 0.0 <= float(y) <= 1.0:
                raise ValueError(
                    f"Zone {identifier!r} coordinates must be normalized to [0, 1]."
                )
            normalized.append((float(x), float(y)))

        if len(set(normalized)) < 3:
            raise ValueError(f"Zone {identifier!r} must have at least three distinct vertices.")
        for index, point in enumerate(normalized):
            if point == normalized[(index + 1) % len(normalized)]:
                raise ValueError(f"Zone {identifier!r} has a repeated adjacent vertex.")

        if _has_self_intersection(normalized):
            raise ValueError(f"Zone {identifier!r} polygon self-intersects.")
        area = abs(_signed_polygon_area(normalized))
        if area <= 1e-12:
            raise ValueError(f"Zone {identifier!r} has zero polygon area.")

        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "polygon", tuple(normalized))

    @property
    def area(self) -> float:
        return abs(_signed_polygon_area(self.polygon))


@dataclass(frozen=True)
class ZoneSnapshot:
    identifier: str
    polygon: tuple[Point, ...]
    state: OccupancyState
    missing_valid_frames: int
    positive_frames_in_window: int
    is_demo: bool
    is_ready: bool


@dataclass(frozen=True)
class _NormalizedDetection:
    box: tuple[float, float, float, float]
    anchor: Point
    confidence: float
    class_name: str


@dataclass
class _ZoneHistory:
    zone: ParkingZone
    is_demo: bool
    state: OccupancyState = OccupancyState.LIBRE
    is_ready: bool = False
    missing_valid_frames: int = 0
    candidate_frames: deque[bool] = field(default_factory=deque)
    candidate_box: _NormalizedDetection | None = None
    strong_streak: int = 0
    last_strong_box: _NormalizedDetection | None = None
    last_strong_frame: int | None = None


def _signed_polygon_area(polygon: Iterable[Point]) -> float:
    points = tuple(polygon)
    return sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    ) / 2.0


def _orientation(first: Point, second: Point, third: Point) -> float:
    return (second[0] - first[0]) * (third[1] - first[1]) - (
        second[1] - first[1]
    ) * (third[0] - first[0])


def _point_on_segment(point: Point, first: Point, second: Point) -> bool:
    epsilon = 1e-12
    return (
        abs(_orientation(first, second, point)) <= epsilon
        and min(first[0], second[0]) - epsilon <= point[0] <= max(first[0], second[0]) + epsilon
        and min(first[1], second[1]) - epsilon <= point[1] <= max(first[1], second[1]) + epsilon
    )


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    first = _orientation(a, b, c)
    second = _orientation(a, b, d)
    third = _orientation(c, d, a)
    fourth = _orientation(c, d, b)
    epsilon = 1e-12

    if (
        ((first > epsilon and second < -epsilon) or (first < -epsilon and second > epsilon))
        and ((third > epsilon and fourth < -epsilon) or (third < -epsilon and fourth > epsilon))
    ):
        return True
    return (
        (abs(first) <= epsilon and _point_on_segment(c, a, b))
        or (abs(second) <= epsilon and _point_on_segment(d, a, b))
        or (abs(third) <= epsilon and _point_on_segment(a, c, d))
        or (abs(fourth) <= epsilon and _point_on_segment(b, c, d))
    )


def _has_self_intersection(polygon: tuple[Point, ...] | list[Point]) -> bool:
    count = len(polygon)
    for first_index in range(count):
        first_next = (first_index + 1) % count
        for second_index in range(first_index + 1, count):
            second_next = (second_index + 1) % count
            if (
                first_index == second_index
                or first_next == second_index
                or second_next == first_index
            ):
                continue
            if _segments_intersect(
                polygon[first_index], polygon[first_next],
                polygon[second_index], polygon[second_next],
            ):
                return True
    return False


def point_in_polygon(point: Point, polygon: tuple[Point, ...]) -> bool:
    """Return true for points inside or on a polygon boundary."""
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if _point_on_segment(point, previous, current):
            return True
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            crossing_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


def load_zones(path: str | Path) -> tuple[ParkingZone, ...]:
    """Load dynamic normalized polygons, allowing an explicitly empty list."""
    zone_path = Path(path)
    try:
        data = json.loads(zone_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f"Could not read zones file {zone_path}: {error}") from error
    if not isinstance(data, dict) or data.get("version") != 2:
        raise ValueError("Zones file must use dynamic calibration schema version 2.")
    if data.get("coordinate_system") != "normalized_0_to_1":
        raise ValueError("Zones file must use normalized coordinates from 0 to 1.")
    if not isinstance(data.get("zones"), list):
        raise ValueError("Zones file must contain a top-level 'zones' array.")

    next_c_number = data.get("next_c_number")
    if (
        not isinstance(next_c_number, int)
        or isinstance(next_c_number, bool)
        or next_c_number < 1
    ):
        raise ValueError("next_c_number must be a positive integer.")

    zones: list[ParkingZone] = []
    identifiers: set[str] = set()
    highest_zone_number = 0
    for item in data["zones"]:
        if not isinstance(item, dict) or "id" not in item or "polygon" not in item:
            raise ValueError("Each zone must provide 'id' and 'polygon' fields.")
        if not isinstance(item["id"], str):
            raise ValueError("Zone ids must be strings.")
        match = _DYNAMIC_ZONE_ID_PATTERN.fullmatch(item["id"])
        if match is None:
            raise ValueError(f"Invalid dynamic zone id {item['id']!r}; expected C followed by a positive integer.")
        highest_zone_number = max(highest_zone_number, int(match.group(1)))
        polygon_value = item["polygon"]
        if not isinstance(polygon_value, list):
            raise ValueError(f"Zone {item['id']!r} polygon must be a coordinate array.")
        try:
            if any(not isinstance(point, list) or len(point) != 2 for point in polygon_value):
                raise ValueError("polygon vertices must be two-number arrays.")
            polygon = tuple((point[0], point[1]) for point in polygon_value)
            zone = ParkingZone(item["id"], polygon)
        except (IndexError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid zone definition: {error}") from error
        if zone.identifier in identifiers:
            raise ValueError(f"Duplicate zone id {zone.identifier!r}.")
        identifiers.add(zone.identifier)
        zones.append(zone)
    if next_c_number <= highest_zone_number:
        raise ValueError("next_c_number must be greater than every active zone id.")
    return tuple(zones)


def whole_frame_demo_zone() -> ParkingZone:
    """Create a clearly labeled single-zone demonstration, not a parking stall."""
    return ParkingZone(
        DEMO_ZONE_ID,
        ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
    )


class TemporalOccupancyValidator:
    """Assign detection bottom-centers to zones and stabilize state over valid frames."""

    def __init__(
        self,
        zones: Iterable[ParkingZone] | None = None,
        *,
        minimum_confidence: float = MINIMUM_CONFIDENCE,
        strong_confidence: float = STRONG_CONFIDENCE,
        strong_confirmation_frames: int = STRONG_CONFIRMATION_FRAMES,
        weak_confirmation_count: int = WEAK_CONFIRMATION_COUNT,
        weak_confirmation_window: int = WEAK_CONFIRMATION_WINDOW,
        release_missing_frames: int = RELEASE_MISSING_FRAMES,
        spatial_match_iou: float = SPATIAL_MATCH_IOU,
        spatial_match_distance_fraction: float = SPATIAL_MATCH_DISTANCE_FRACTION,
    ) -> None:
        if not 0.0 <= minimum_confidence < strong_confidence <= 1.0:
            raise ValueError("Confidence thresholds must satisfy 0 <= minimum < strong <= 1.")
        if strong_confirmation_frames < 2:
            raise ValueError("Strong confirmation must require at least two frames.")
        if weak_confirmation_count < 1 or weak_confirmation_window < weak_confirmation_count:
            raise ValueError("Weak confirmation window must fit its required positive-frame count.")
        if release_missing_frames < 1:
            raise ValueError("release_missing_frames must be at least one.")
        if not 0.0 <= spatial_match_iou <= 1.0:
            raise ValueError("spatial_match_iou must be between 0 and 1.")
        if spatial_match_distance_fraction < 0.0:
            raise ValueError("spatial_match_distance_fraction must be non-negative.")

        configured_zones = tuple(zones) if zones is not None else (whole_frame_demo_zone(),)
        identifiers = [zone.identifier for zone in configured_zones]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Zone identifiers must be unique.")

        self.zones = configured_zones
        self.demo_mode = zones is None
        self.minimum_confidence = minimum_confidence
        self.strong_confidence = strong_confidence
        self.strong_confirmation_frames = strong_confirmation_frames
        self.weak_confirmation_count = weak_confirmation_count
        self.weak_confirmation_window = weak_confirmation_window
        self.release_missing_frames = release_missing_frames
        self.spatial_match_iou = spatial_match_iou
        self.spatial_match_distance_fraction = spatial_match_distance_fraction
        self.valid_frame_index = 0
        self._history = {
            zone.identifier: _ZoneHistory(
                zone=zone,
                is_demo=self.demo_mode,
                candidate_frames=deque(maxlen=weak_confirmation_window),
            )
            for zone in configured_zones
        }

    def snapshots(self) -> tuple[ZoneSnapshot, ...]:
        return tuple(
            ZoneSnapshot(
                identifier=history.zone.identifier,
                polygon=history.zone.polygon,
                state=history.state,
                missing_valid_frames=history.missing_valid_frames,
                positive_frames_in_window=sum(history.candidate_frames),
                is_demo=history.is_demo,
                is_ready=history.is_ready,
            )
            for history in self._history.values()
        )

    def process_frame(
        self,
        detections: Iterable[VehicleDetection],
        frame_width: int,
        frame_height: int,
        *,
        valid: bool = True,
    ) -> tuple[ZoneSnapshot, ...]:
        """Advance once for a valid frame; invalid frames leave all histories untouched."""
        if frame_width <= 0 or frame_height <= 0:
            raise ValueError("Frame dimensions must be positive.")
        if not valid:
            return self.snapshots()

        self.valid_frame_index += 1
        detections_by_zone = self._assign_detections(
            detections, frame_width, frame_height
        )
        for identifier, history in self._history.items():
            current = detections_by_zone[identifier]
            qualifying = [
                detection
                for detection in current
                if detection.confidence >= self.minimum_confidence
            ]

            if history.state is OccupancyState.OCUPADO:
                if qualifying:
                    history.missing_valid_frames = 0
                else:
                    history.missing_valid_frames += 1
                    if history.missing_valid_frames >= self.release_missing_frames:
                        self._clear_candidate(history)
                        history.state = OccupancyState.LIBRE
                        history.missing_valid_frames = 0
                continue

            if not qualifying:
                if history.candidate_box is not None:
                    history.candidate_frames.append(False)
                    history.strong_streak = 0
                    history.last_strong_box = None
                    history.last_strong_frame = None
                    if any(history.candidate_frames):
                        history.state = OccupancyState.CANDIDATO_OCUPADO
                    else:
                        self._clear_candidate(history)
                        history.state = OccupancyState.LIBRE
                        if not history.is_ready:
                            history.missing_valid_frames += 1
                            if history.missing_valid_frames >= self.release_missing_frames:
                                history.is_ready = True
                                history.missing_valid_frames = 0
                elif not history.is_ready:
                    history.missing_valid_frames += 1
                    if history.missing_valid_frames >= self.release_missing_frames:
                        history.is_ready = True
                        history.missing_valid_frames = 0
                continue

            if history.candidate_box is None:
                self._start_candidate(history, max(qualifying, key=lambda item: item.confidence))
                continue

            matching = [
                detection
                for detection in qualifying
                if self._detections_match(history.candidate_box, detection)
            ]
            if not matching:
                # A detection at a separate location starts a new candidate; it does not
                # inherit another object's confidence history.
                self._start_candidate(history, max(qualifying, key=lambda item: item.confidence))
                continue

            selected = max(matching, key=lambda item: item.confidence)
            self._record_candidate_match(history, selected)

        return self.snapshots()

    def _assign_detections(
        self,
        detections: Iterable[VehicleDetection],
        frame_width: int,
        frame_height: int,
    ) -> dict[str, list[_NormalizedDetection]]:
        assigned = {zone.identifier: [] for zone in self.zones}
        for detection in detections:
            if not isinstance(detection, VehicleDetection):
                raise TypeError("process_frame expects VehicleDetection values.")
            x1, y1, x2, y2 = detection.box_xyxy
            normalized = _NormalizedDetection(
                box=(x1 / frame_width, y1 / frame_height, x2 / frame_width, y2 / frame_height),
                anchor=((x1 + x2) / (2.0 * frame_width), y2 / frame_height),
                confidence=float(detection.confidence),
                class_name=detection.class_name,
            )
            containing = [
                zone for zone in self.zones if point_in_polygon(normalized.anchor, zone.polygon)
            ]
            if containing:
                # Overlapping polygons remain deterministic: the smallest containing
                # zone wins, followed by its stable id. One box is assigned only once.
                selected_zone = min(containing, key=lambda zone: (zone.area, zone.identifier))
                assigned[selected_zone.identifier].append(normalized)
        return assigned

    def _detections_match(
        self, first: _NormalizedDetection, second: _NormalizedDetection
    ) -> bool:
        if _box_iou(first.box, second.box) >= self.spatial_match_iou:
            return True
        dx = first.anchor[0] - second.anchor[0]
        dy = first.anchor[1] - second.anchor[1]
        normalized_distance = math.hypot(dx, dy) / math.sqrt(2.0)
        return normalized_distance <= self.spatial_match_distance_fraction

    def _start_candidate(
        self, history: _ZoneHistory, detection: _NormalizedDetection
    ) -> None:
        self._clear_candidate(history)
        history.missing_valid_frames = 0
        history.candidate_box = detection
        history.candidate_frames.append(True)
        history.state = OccupancyState.CANDIDATO_OCUPADO
        if detection.confidence >= self.strong_confidence:
            history.strong_streak = 1
            history.last_strong_box = detection
            history.last_strong_frame = self.valid_frame_index

    def _record_candidate_match(
        self, history: _ZoneHistory, detection: _NormalizedDetection
    ) -> None:
        history.candidate_box = detection
        history.candidate_frames.append(True)
        history.state = OccupancyState.CANDIDATO_OCUPADO

        if detection.confidence >= self.strong_confidence:
            if (
                history.last_strong_box is not None
                and history.last_strong_frame == self.valid_frame_index - 1
                and self._detections_match(history.last_strong_box, detection)
            ):
                history.strong_streak += 1
            else:
                history.strong_streak = 1
            history.last_strong_box = detection
            history.last_strong_frame = self.valid_frame_index
        else:
            history.strong_streak = 0
            history.last_strong_box = None
            history.last_strong_frame = None

        if (
            history.strong_streak >= self.strong_confirmation_frames
            or sum(history.candidate_frames) >= self.weak_confirmation_count
        ):
            history.state = OccupancyState.OCUPADO
            history.is_ready = True
            history.missing_valid_frames = 0
            self._clear_candidate(history)

    @staticmethod
    def _clear_candidate(history: _ZoneHistory) -> None:
        history.candidate_frames.clear()
        history.candidate_box = None
        history.strong_streak = 0
        history.last_strong_box = None
        history.last_strong_frame = None


def _box_iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0.0 else 0.0


class FrameQualityGuard:
    """Reject malformed, near-black, and pixel-identical repeated frames.

    OpenCV's live HTTP capture does not provide a dependable presentation timestamp
    for each decoded frame. Exact repeated image content is therefore treated as a
    stale/repeated frame; source read failures are handled separately by capture.py.
    """

    def __init__(self, black_max_value: int = 1) -> None:
        if not 0 <= black_max_value <= 255:
            raise ValueError("black_max_value must be from 0 to 255.")
        self.black_max_value = black_max_value
        self._previous: np.ndarray | None = None

    def inspect(
        self, frame: object, *, allow_repeated: bool = False
    ) -> tuple[bool, str | None]:
        """Validate image content, optionally accepting intentional still-frame repeats."""
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            return False, "malformed frame"
        if frame.size == 0:
            return False, "empty frame"
        if int(frame.max()) <= self.black_max_value:
            return False, "black frame"
        if (
            not allow_repeated
            and self._previous is not None
            and frame.shape == self._previous.shape
        ):
            if np.array_equal(frame, self._previous):
                return False, "repeated frame"
        self._previous = frame.copy()
        return True, None
