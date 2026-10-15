"""Frame ordering and timing helpers for local still-image simulations."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

FRAME_NAME_PATTERN = re.compile(r"^frame_(\d+)\.png$", re.IGNORECASE)


@dataclass(frozen=True)
class SimulationFrame:
    """One ordered image and its hold duration in a simulation sequence."""

    path: Path
    index: int
    duration_seconds: float


def build_simulation_sequence(
    directory: Path,
    default_duration: float,
    duration_overrides: Sequence[str] = (),
) -> tuple[SimulationFrame, ...]:
    """Discover numbered PNG frames, sort numerically, and apply duration overrides."""
    if not math.isfinite(default_duration) or default_duration <= 0:
        raise ValueError("The default frame duration must be a finite positive number.")
    if not directory.is_dir():
        raise ValueError(f"Simulation directory does not exist: {directory}")

    numbered_frames: list[tuple[int, Path]] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        match = FRAME_NAME_PATTERN.fullmatch(path.name)
        if match is not None:
            numbered_frames.append((int(match.group(1)), path))
    numbered_frames.sort(key=lambda item: item[0])
    if not numbered_frames:
        raise ValueError(f"No numbered frame_###.png images found in {directory}.")

    indices = [index for index, _ in numbered_frames]
    if indices != list(range(1, len(indices) + 1)):
        raise ValueError(
            "Simulation frames must be numbered consecutively from frame_001.png. "
            f"Found indices: {indices}."
        )

    frame_names = {path.name for _, path in numbered_frames}
    overrides: dict[str, float] = {}
    for specification in duration_overrides:
        filename, separator, raw_duration = specification.partition("=")
        if not separator or Path(filename).name != filename or filename not in frame_names:
            raise ValueError(
                "Frame duration overrides must use an existing filename as "
                "FRAME=SECONDS, for example frame_003.png=7.5."
            )
        if filename in overrides:
            raise ValueError(f"Duplicate frame duration override: {filename}.")
        try:
            duration = float(raw_duration)
        except ValueError as error:
            raise ValueError(
                f"Invalid duration for {filename}: {raw_duration!r}."
            ) from error
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"Duration for {filename} must be finite and positive.")
        overrides[filename] = duration

    return tuple(
        SimulationFrame(
            path=path,
            index=index,
            duration_seconds=overrides.get(path.name, default_duration),
        )
        for index, path in numbered_frames
    )


def next_frame_index(current_index: int, frame_count: int, loop: bool) -> int | None:
    """Return the next zero-based playlist index, or None after a non-looping end."""
    if frame_count < 1 or not 0 <= current_index < frame_count:
        raise ValueError("The current simulation frame index is outside the sequence.")
    if current_index + 1 < frame_count:
        return current_index + 1
    return 0 if loop else None
