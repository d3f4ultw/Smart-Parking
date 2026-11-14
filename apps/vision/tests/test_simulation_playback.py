from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simulation_playback import build_simulation_sequence, next_frame_index


class SimulationPlaybackTests(unittest.TestCase):
    def test_discovers_all_numbered_frames_in_numeric_order(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            for index in (10, 2, 1, 8, 3, 4, 5, 6, 7, 9):
                (directory / f"frame_{index:03}.png").touch()
            (directory / "notes.txt").touch()

            sequence = build_simulation_sequence(directory, 5.0)

            self.assertEqual(
                [frame.path.name for frame in sequence],
                [f"frame_{index:03}.png" for index in range(1, 11)],
            )
            self.assertTrue(all(frame.duration_seconds == 5.0 for frame in sequence))

    def test_applies_per_frame_duration_override(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            for index in range(1, 4):
                (directory / f"frame_{index:03}.png").touch()

            sequence = build_simulation_sequence(
                directory,
                5.0,
                ("frame_002.png=7.5", "frame_003.png=2.25"),
            )

            self.assertEqual(
                [frame.duration_seconds for frame in sequence], [5.0, 7.5, 2.25]
            )

    def test_rejects_gaps_in_frame_numbering(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "frame_001.png").touch()
            (directory / "frame_003.png").touch()

            with self.assertRaisesRegex(ValueError, "numbered consecutively"):
                build_simulation_sequence(directory, 5.0)

    def test_rejects_invalid_frame_duration_overrides(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "frame_001.png").touch()

            for override in (
                "frame_002.png=2",
                "frame_001.png=0",
                "frame_001.png=NaN",
                "frame_001.png=invalid",
                "folder/frame_001.png=2",
            ):
                with self.subTest(override=override):
                    with self.assertRaises(ValueError):
                        build_simulation_sequence(directory, 5.0, (override,))

    def test_loop_wraps_after_last_frame_and_no_loop_stops(self):
        self.assertEqual(next_frame_index(6, 8, loop=True), 7)
        self.assertEqual(next_frame_index(7, 8, loop=True), 0)
        self.assertIsNone(next_frame_index(7, 8, loop=False))


if __name__ == "__main__":
    unittest.main()
