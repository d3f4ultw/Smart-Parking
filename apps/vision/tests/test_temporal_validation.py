from __future__ import annotations

import unittest

import numpy as np

from temporal_validation import (
    FrameQualityGuard,
    OccupancyState,
    ParkingZone,
    TemporalOccupancyValidator,
    VehicleDetection,
    load_zones,
)


def vehicle(confidence: float, x: float = 400, y: float = 200) -> VehicleDetection:
    return VehicleDetection((x, y, x + 80, y + 70), confidence, "car")


def state(validator: TemporalOccupancyValidator, zone_id: str | None = None):
    snapshots = validator.snapshots()
    if zone_id is None:
        return snapshots[0].state
    return next(snapshot.state for snapshot in snapshots if snapshot.identifier == zone_id)


class TemporalValidationTests(unittest.TestCase):
    def test_explicit_empty_zone_collection_is_not_whole_frame_demo(self):
        validator = TemporalOccupancyValidator(())

        self.assertEqual(validator.zones, ())
        self.assertFalse(validator.demo_mode)
        self.assertEqual(validator.snapshots(), ())
        self.assertEqual(
            validator.process_frame([vehicle(0.9)], 1280, 720),
            (),
        )
        self.assertEqual(validator.snapshots(), ())

    def test_one_strong_detection_is_only_a_candidate(self):
        validator = TemporalOccupancyValidator()
        result = validator.process_frame([vehicle(0.80)], 1280, 720)
        self.assertEqual(result[0].state, OccupancyState.CANDIDATO_OCUPADO)

    def test_startup_free_state_is_not_publishable_until_four_valid_clear_frames(self):
        validator = TemporalOccupancyValidator((ParkingZone("C1", ((0, 0), (1, 0), (1, 1))),))
        self.assertFalse(validator.snapshots()[0].is_ready)
        for _ in range(3):
            snapshot = validator.process_frame([], 100, 100)[0]
            self.assertFalse(snapshot.is_ready)
        snapshot = validator.process_frame([], 100, 100)[0]
        self.assertTrue(snapshot.is_ready)
        self.assertEqual(snapshot.state, OccupancyState.LIBRE)

    def test_invalid_frame_does_not_make_startup_free_state_ready(self):
        validator = TemporalOccupancyValidator((ParkingZone("C1", ((0, 0), (1, 0), (1, 1))),))
        for _ in range(8):
            snapshot = validator.process_frame([], 100, 100, valid=False)[0]
        self.assertFalse(snapshot.is_ready)
        self.assertEqual(validator.valid_frame_index, 0)

    def test_two_consecutive_spatially_matching_strong_detections_confirm(self):
        validator = TemporalOccupancyValidator()
        validator.process_frame([vehicle(0.45)], 1280, 720)
        result = validator.process_frame([vehicle(0.90, x=406, y=204)], 1280, 720)
        self.assertEqual(result[0].state, OccupancyState.OCUPADO)

    def test_three_weak_matches_within_five_valid_frames_confirm(self):
        validator = TemporalOccupancyValidator()
        validator.process_frame([vehicle(0.30)], 1280, 720)
        validator.process_frame([], 1280, 720)
        validator.process_frame([vehicle(0.44, x=405)], 1280, 720)
        result = validator.process_frame([vehicle(0.31, x=410)], 1280, 720)
        self.assertEqual(result[0].state, OccupancyState.OCUPADO)

    def test_one_weak_detection_followed_by_absence_never_confirms(self):
        validator = TemporalOccupancyValidator()
        validator.process_frame([vehicle(0.40)], 1280, 720)
        states = [validator.process_frame([], 1280, 720)[0].state for _ in range(6)]
        self.assertNotIn(OccupancyState.OCUPADO, states)
        self.assertEqual(state(validator), OccupancyState.LIBRE)

    def test_occupied_zone_survives_one_or_two_missing_frames(self):
        validator = TemporalOccupancyValidator()
        validator.process_frame([vehicle(0.70)], 1280, 720)
        validator.process_frame([vehicle(0.72)], 1280, 720)
        for missing_count in (1, 2):
            snapshot = validator.process_frame([], 1280, 720)[0]
            self.assertEqual(snapshot.state, OccupancyState.OCUPADO)
            self.assertEqual(snapshot.missing_valid_frames, missing_count)

    def test_four_consecutive_valid_misses_release_occupied_zone(self):
        validator = TemporalOccupancyValidator()
        validator.process_frame([vehicle(0.70)], 1280, 720)
        validator.process_frame([vehicle(0.72)], 1280, 720)
        results = [validator.process_frame([], 1280, 720)[0] for _ in range(4)]
        self.assertEqual(results[-2].state, OccupancyState.OCUPADO)
        self.assertEqual(results[-1].state, OccupancyState.LIBRE)

    def test_detection_in_neighbor_zone_does_not_occupy_current_zone(self):
        left = ParkingZone("LEFT", ((0.0, 0.0), (0.49, 0.0), (0.49, 1.0), (0.0, 1.0)))
        right = ParkingZone("RIGHT", ((0.51, 0.0), (1.0, 0.0), (1.0, 1.0), (0.51, 1.0)))
        validator = TemporalOccupancyValidator((left, right))
        right_box = vehicle(0.80, x=720, y=150)
        validator.process_frame([right_box], 1280, 720)
        result = validator.process_frame([right_box], 1280, 720)
        self.assertEqual(state(validator, "LEFT"), OccupancyState.LIBRE)
        self.assertEqual(state(validator, "RIGHT"), OccupancyState.OCUPADO)
        self.assertEqual(len(result), 2)

    def test_overlapping_polygons_assign_one_detection_to_one_smallest_zone(self):
        outer = ParkingZone("OUTER", ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)))
        inner = ParkingZone("INNER", ((0.4, 0.2), (0.8, 0.2), (0.8, 0.7), (0.4, 0.7)))
        validator = TemporalOccupancyValidator((outer, inner))
        box = vehicle(0.80, x=520, y=170)
        validator.process_frame([box], 1280, 720)
        result = validator.process_frame([box], 1280, 720)
        self.assertEqual(state(validator, "INNER"), OccupancyState.OCUPADO)
        self.assertEqual(state(validator, "OUTER"), OccupancyState.LIBRE)
        self.assertEqual(sum(snapshot.positive_frames_in_window for snapshot in result), 0)

    def test_invalid_frames_do_not_advance_absence_counter(self):
        validator = TemporalOccupancyValidator()
        validator.process_frame([vehicle(0.75)], 1280, 720)
        validator.process_frame([vehicle(0.75)], 1280, 720)
        before = validator.snapshots()[0]
        for _ in range(8):
            after = validator.process_frame([], 1280, 720, valid=False)[0]
        self.assertEqual(after.state, OccupancyState.OCUPADO)
        self.assertEqual(after.missing_valid_frames, before.missing_valid_frames)
        self.assertEqual(validator.valid_frame_index, 2)

    def test_frame_guard_rejects_black_and_identical_repeated_frames(self):
        guard = FrameQualityGuard()
        black = np.zeros((32, 32, 3), dtype=np.uint8)
        self.assertEqual(guard.inspect(black), (False, "black frame"))
        first = np.full((32, 32, 3), 20, dtype=np.uint8)
        self.assertEqual(guard.inspect(first), (True, None))
        self.assertEqual(guard.inspect(first.copy()), (False, "repeated frame"))
        changed = first.copy()
        changed[0, 0, 0] = 21
        self.assertEqual(guard.inspect(changed), (True, None))

    def test_frame_guard_allows_intentionally_repeated_simulation_frames(self):
        guard = FrameQualityGuard()
        still = np.full((32, 32, 3), 20, dtype=np.uint8)
        self.assertEqual(guard.inspect(still), (True, None))
        self.assertEqual(guard.inspect(still.copy(), allow_repeated=True), (True, None))
        black = np.zeros((32, 32, 3), dtype=np.uint8)
        self.assertEqual(guard.inspect(black, allow_repeated=True), (False, "black frame"))

    def test_duplicate_boxes_in_one_frame_count_as_one_confirmation_frame(self):
        validator = TemporalOccupancyValidator()
        duplicate = vehicle(0.91)
        result = validator.process_frame([duplicate, duplicate], 1280, 720)
        self.assertEqual(result[0].positive_frames_in_window, 1)
        self.assertEqual(result[0].state, OccupancyState.CANDIDATO_OCUPADO)

    def test_two_zones_keep_independent_confirmation_histories(self):
        left = ParkingZone("LEFT", ((0.0, 0.0), (0.49, 0.0), (0.49, 1.0), (0.0, 1.0)))
        right = ParkingZone("RIGHT", ((0.51, 0.0), (1.0, 0.0), (1.0, 1.0), (0.51, 1.0)))
        validator = TemporalOccupancyValidator((left, right))
        left_box = vehicle(0.80, x=100, y=150)
        right_box = vehicle(0.82, x=720, y=150)
        validator.process_frame([left_box], 1280, 720)
        validator.process_frame([right_box], 1280, 720)
        validator.process_frame([right_box], 1280, 720)
        self.assertEqual(state(validator, "LEFT"), OccupancyState.CANDIDATO_OCUPADO)
        self.assertEqual(state(validator, "RIGHT"), OccupancyState.OCUPADO)

    def test_confidence_threshold_boundaries_are_inclusive_as_specified(self):
        below = TemporalOccupancyValidator()
        below.process_frame([vehicle(0.2999)], 1280, 720)
        self.assertEqual(state(below), OccupancyState.LIBRE)

        weak = TemporalOccupancyValidator()
        for _ in range(3):
            result = weak.process_frame([vehicle(0.30)], 1280, 720)
        self.assertEqual(result[0].state, OccupancyState.OCUPADO)

        strong = TemporalOccupancyValidator()
        strong.process_frame([vehicle(0.45)], 1280, 720)
        result = strong.process_frame([vehicle(0.45)], 1280, 720)
        self.assertEqual(result[0].state, OccupancyState.OCUPADO)

    def test_normalized_zone_association_survives_resolution_change(self):
        zone = ParkingZone("RIGHT", ((0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)))
        validator = TemporalOccupancyValidator((zone,))
        validator.process_frame([vehicle(0.80, x=720, y=150)], 1280, 720)
        scaled = VehicleDetection((360, 75, 400, 110), 0.80, "car")
        result = validator.process_frame([scaled], 640, 360)
        self.assertEqual(result[0].state, OccupancyState.OCUPADO)

    def test_unmatched_vehicle_location_does_not_inherit_candidate_history(self):
        validator = TemporalOccupancyValidator()
        validator.process_frame([vehicle(0.80, x=100, y=120)], 1280, 720)
        result = validator.process_frame([vehicle(0.80, x=800, y=500)], 1280, 720)
        self.assertEqual(result[0].state, OccupancyState.CANDIDATO_OCUPADO)
        self.assertEqual(result[0].positive_frames_in_window, 1)

    def test_polygon_validation_rejects_self_intersection_and_bad_coordinates(self):
        with self.assertRaisesRegex(ValueError, "self-intersects"):
            ParkingZone("BAD", ((0.1, 0.1), (0.9, 0.9), (0.1, 0.9), (0.9, 0.1)))
        with self.assertRaisesRegex(ValueError, "normalized"):
            ParkingZone("BAD", ((-0.1, 0.1), (0.9, 0.1), (0.9, 0.9)))


if __name__ == "__main__":
    unittest.main()
