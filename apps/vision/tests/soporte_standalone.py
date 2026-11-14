"""Fixture compartido de zonas y detecciones para pruebas autónomas."""

import unittest

from temporal_validation import ParkingZone, VehicleDetection


class SoporteStandalone(unittest.TestCase):
    def setUp(self):
        self.zone = ParkingZone("C1", ((0, 0), (1, 0), (1, 1), (0, 1)))
        self.vehicle = VehicleDetection((10, 10, 20, 30), 0.9, "car")

