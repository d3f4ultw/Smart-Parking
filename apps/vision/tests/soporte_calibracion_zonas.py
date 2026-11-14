from __future__ import annotations

import argparse
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import cv2
import numpy as np

from calibracion_zonas import (
    CalibracionZonas,
    advertencias_solapamiento,
    cargar_calibracion,
    guardar_calibracion,
)
from calibrar_zonas import ControlRaton, _procesar_tecla, dibujar_superposicion, ejecutar
from detect import draw_zone_states, zone_identity_color
from capture import MuestraCaptura
from configuracion_local import (
    guardar_vinculo,
    identidad_fuente,
    respaldar_calibracion,
    verificar_vinculo,
)
from temporal_validation import (
    OccupancyState,
    ParkingZone,
    TemporalOccupancyValidator,
    VehicleDetection,
    load_zones,
)


TRIANGULO = ((10, 10), (80, 10), (45, 80))
CUADRILATERO = ((10, 10), (80, 10), (80, 80), (10, 80))
PENTAGONO = ((10, 10), (70, 10), (90, 40), (50, 80), (10, 50))


def crear_zona(
    calibracion: CalibracionZonas,
    puntos: tuple[tuple[int, int], ...] = TRIANGULO,
) -> str:
    for punto in puntos:
        aceptado, mensaje = calibracion.agregar_punto(*punto)
        if not aceptado:
            raise AssertionError(mensaje)
    aceptado, mensaje = calibracion.confirmar_poligono()
    if not aceptado:
        raise AssertionError(mensaje)
    return f"C{calibracion.next_c_number - 1}"


def config_dinamica(zonas: list[dict[str, object]], siguiente: int) -> dict[str, object]:
    return {
        "version": 2,
        "coordinate_system": "normalized_0_to_1",
        "next_c_number": siguiente,
        "metadata": {},
        "zones": zonas,
    }


