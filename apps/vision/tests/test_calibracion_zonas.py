from __future__ import annotations

import argparse
import json
import tempfile
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
from detect import draw_zone_states
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


class CalibracionZonasTests(unittest.TestCase):
    def test_starts_empty_and_first_confirmed_polygon_gets_c1(self):
        calibracion = CalibracionZonas(100, 100)
        self.assertEqual(calibracion.zonas, {})
        self.assertEqual(calibracion.next_c_number, 1)

        for punto in TRIANGULO[:2]:
            self.assertTrue(calibracion.agregar_punto(*punto)[0])
        self.assertFalse(calibracion.confirmar_poligono()[0])
        self.assertEqual(calibracion.zonas, {})
        self.assertEqual(calibracion.next_c_number, 1)

        self.assertTrue(calibracion.agregar_punto(*TRIANGULO[2])[0])
        self.assertTrue(calibracion.confirmar_poligono()[0])
        self.assertIn("C1", calibracion.zonas)
        self.assertEqual(calibracion.next_c_number, 2)

    def test_cancelled_draft_does_not_consume_identifier(self):
        calibracion = CalibracionZonas(100, 100)
        for punto in TRIANGULO[:2]:
            self.assertTrue(calibracion.agregar_punto(*punto)[0])
        self.assertIn("no cambio", calibracion.cancelar_poligono())
        self.assertEqual(calibracion.next_c_number, 1)
        self.assertEqual(calibracion.puntos_pendientes, [])

        self.assertEqual(crear_zona(calibracion), "C1")

    def test_three_four_and_five_vertex_polygons_are_supported(self):
        calibracion = CalibracionZonas(100, 100)
        self.assertEqual(crear_zona(calibracion, TRIANGULO), "C1")
        self.assertEqual(crear_zona(calibracion, CUADRILATERO), "C2")
        self.assertEqual(crear_zona(calibracion, PENTAGONO), "C3")
        self.assertEqual(
            [len(calibracion.zonas[f"C{i}"].polygon) for i in range(1, 4)],
            [3, 4, 5],
        )

    def test_invalid_polygon_remains_editable_without_consuming_id(self):
        calibracion = CalibracionZonas(100, 100)
        bow_tie = ((10, 10), (80, 80), (10, 80), (80, 10))
        for punto in bow_tie:
            self.assertTrue(calibracion.agregar_punto(*punto)[0])

        aceptado, mensaje = calibracion.confirmar_poligono()

        self.assertFalse(aceptado)
        self.assertIn("Poligono invalido", mensaje)
        self.assertEqual(len(calibracion.puntos_pendientes), 4)
        self.assertEqual(calibracion.next_c_number, 1)
        self.assertEqual(calibracion.zonas, {})

    def test_empty_calibration_round_trips_with_dynamic_schema(self):
        calibracion = CalibracionZonas(1672, 941)
        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            self.assertEqual(guardar_calibracion(destino, calibracion, "image"), [])
            datos = json.loads(destino.read_text(encoding="utf-8"))
            cargada = cargar_calibracion(destino, 1280, 720)
            temporal = load_zones(destino)

        self.assertEqual(datos["version"], 2)
        self.assertEqual(datos["coordinate_system"], "normalized_0_to_1")
        self.assertEqual(datos["next_c_number"], 1)
        self.assertEqual(datos["zones"], [])
        self.assertEqual(cargada.zonas, {})
        self.assertEqual(cargada.next_c_number, 1)
        self.assertEqual(temporal, ())

    def test_partial_round_trip_preserves_ids_and_normalized_geometry(self):
        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion, TRIANGULO)
        crear_zona(calibracion, PENTAGONO)
        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            guardar_calibracion(destino, calibracion, "image")
            cargada = cargar_calibracion(destino, 100, 100)

        self.assertEqual(tuple(cargada.zonas), ("C1", "C2"))
        self.assertEqual(cargada.next_c_number, 3)
        for identifier in ("C1", "C2"):
            for actual, original in zip(
                cargada.zonas[identifier].polygon,
                calibracion.zonas[identifier].polygon,
            ):
                self.assertAlmostEqual(actual[0], original[0], places=8)
                self.assertAlmostEqual(actual[1], original[1], places=8)

    def test_arbitrary_zone_count_round_trips_without_a_fixed_maximum(self):
        calibracion = CalibracionZonas(1000, 800)
        for fila in range(3):
            for columna in range(4):
                x = 20 + columna * 240
                y = 20 + fila * 240
                crear_zona(
                    calibracion,
                    ((x, y), (x + 150, y), (x + 75, y + 160)),
                )

        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            guardar_calibracion(destino, calibracion, "image")
            cargada = cargar_calibracion(destino, 1000, 800)

        self.assertEqual(len(cargada.zonas), 12)
        self.assertEqual(tuple(cargada.zonas), tuple(f"C{i}" for i in range(1, 13)))
        self.assertEqual(cargada.next_c_number, 13)

    def test_editing_any_vertex_count_keeps_the_identifier(self):
        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion, PENTAGONO)
        original = calibracion.zonas["C1"]

        aceptado, _ = calibracion.mover_vertice("C1", 4, 14, 55)

        self.assertTrue(aceptado)
        self.assertEqual(calibracion.zonas["C1"].identifier, "C1")
        self.assertEqual(len(calibracion.zonas["C1"].polygon), 5)
        self.assertNotEqual(calibracion.zonas["C1"], original)

        movida = calibracion.zonas["C1"]
        aceptado, _ = calibracion.mover_vertice("C1", 4, 70, 10)
        self.assertFalse(aceptado)
        self.assertEqual(calibracion.zonas["C1"], movida)

    def test_deletion_never_renumbers_or_reuses_ids_after_reload(self):
        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion, TRIANGULO)
        crear_zona(calibracion, CUADRILATERO)
        crear_zona(calibracion, PENTAGONO)
        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            guardar_calibracion(destino, calibracion, "image")
            calibracion.eliminar_zona("C2")
            guardar_calibracion(destino, calibracion, "image")
            recargada = cargar_calibracion(destino, 100, 100)

            self.assertEqual(tuple(recargada.zonas), ("C1", "C3"))
            self.assertEqual(recargada.next_c_number, 4)
            self.assertEqual(crear_zona(recargada), "C4")
            recargada.eliminar_zona("C4")
            guardar_calibracion(destino, recargada, "image")
            despues_de_borrar_el_mayor = cargar_calibracion(destino, 100, 100)
            self.assertEqual(despues_de_borrar_el_mayor.next_c_number, 5)
            self.assertEqual(crear_zona(despues_de_borrar_el_mayor), "C5")

        self.assertEqual(
            tuple(despues_de_borrar_el_mayor.zonas), ("C1", "C3", "C5")
        )

    def test_reset_all_keeps_the_persisted_allocator_high_water_mark(self):
        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion)
        crear_zona(calibracion)
        calibracion.reiniciar_todas()
        self.assertEqual(calibracion.zonas, {})
        self.assertEqual(calibracion.next_c_number, 3)

        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            guardar_calibracion(destino, calibracion, "image")
            recargada = cargar_calibracion(destino, 100, 100)

        self.assertEqual(recargada.zonas, {})
        self.assertEqual(crear_zona(recargada), "C3")

    def test_save_omits_unfinished_draft_but_keeps_committed_zones(self):
        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion)
        for punto in TRIANGULO[:2]:
            self.assertTrue(calibracion.agregar_punto(*punto)[0])

        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            guardar_calibracion(destino, calibracion, "image")
            datos = json.loads(destino.read_text(encoding="utf-8"))
            cargada = cargar_calibracion(destino, 100, 100)

        self.assertEqual([zona["id"] for zona in datos["zones"]], ["C1"])
        self.assertEqual(datos["next_c_number"], 2)
        self.assertEqual(tuple(cargada.zonas), ("C1",))
        self.assertTrue(calibracion.hay_borrador)
        self.assertTrue(calibracion.cambios_pendientes)

    def test_zero_and_multiple_zones_produce_only_configured_temporal_states(self):
        empty = TemporalOccupancyValidator(())
        self.assertEqual(empty.zones, ())
        self.assertFalse(empty.demo_mode)
        self.assertEqual(empty.snapshots(), ())
        self.assertEqual(
            empty.process_frame([VehicleDetection((1, 1, 20, 20), 0.9, "car")], 100, 100),
            (),
        )

        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion, ((0, 0), (70, 0), (70, 70), (0, 70)))
        crear_zona(calibracion, ((30, 30), (95, 30), (95, 95), (30, 95)))
        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            guardar_calibracion(destino, calibracion, "image")
            zonas = load_zones(destino)
        validator = TemporalOccupancyValidator(zonas)
        snapshots = validator.process_frame([], 100, 100)

        self.assertEqual(tuple(snapshot.identifier for snapshot in snapshots), ("C1", "C2"))
        self.assertTrue(all(snapshot.state is OccupancyState.LIBRE for snapshot in snapshots))
        self.assertTrue(all(not snapshot.is_demo for snapshot in snapshots))

    def test_invalid_configs_are_rejected_by_calibration_and_detection_loaders(self):
        valid_zone = {"id": "C1", "polygon": [[0.1, 0.1], [0.8, 0.1], [0.4, 0.8]]}
        invalid_variants = (
            ("duplicate", [valid_zone, valid_zone], 2),
            ("bad_id", [{**valid_zone, "id": "1"}], 2),
            ("bad_counter", [valid_zone], 1),
            ("two_points", [{"id": "C1", "polygon": [[0, 0], [1, 1]]}], 2),
            (
                "bad_coordinate",
                [{"id": "C1", "polygon": [[-0.1, 0], [1, 0], [0, 1]]}],
                2,
            ),
            (
                "self_intersection",
                [{"id": "C1", "polygon": [[0.1, 0.1], [0.8, 0.8], [0.1, 0.8], [0.8, 0.1]]}],
                2,
            ),
        )
        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "invalid.json"
            for name, zones, next_number in invalid_variants:
                with self.subTest(name=name):
                    destino.write_text(
                        json.dumps(config_dinamica(zones, next_number)), encoding="utf-8"
                    )
                    with self.assertRaises(ValueError):
                        cargar_calibracion(destino, 100, 100)
                    with self.assertRaises(ValueError):
                        load_zones(destino)

            destino.write_text("{malformed", encoding="utf-8")
            with self.assertRaises(ValueError):
                cargar_calibracion(destino, 100, 100)
            with self.assertRaises(ValueError):
                load_zones(destino)

    def test_invalid_save_does_not_replace_existing_file_or_leave_temporary_file(self):
        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion)
        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            guardar_calibracion(destino, calibracion, "image")
            original = destino.read_bytes()
            calibracion.next_c_number = 1

            with self.assertRaisesRegex(ValueError, "greater than|mayor que"):
                guardar_calibracion(destino, calibracion, "image")

            self.assertEqual(destino.read_bytes(), original)
            self.assertEqual(list(Path(directorio).glob(".zones.json.*.tmp")), [])

    def test_missing_malformed_and_wrong_schema_files_fail_clearly(self):
        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            with self.assertRaisesRegex(ValueError, "No se pudo leer"):
                cargar_calibracion(destino, 100, 100)
            destino.write_text("{bad json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "No se pudo leer"):
                cargar_calibracion(destino, 100, 100)
            destino.write_text(json.dumps({"version": 1, "zones": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "esquema"):
                cargar_calibracion(destino, 100, 100)

    def test_zone_selection_and_near_vertex_lookup_are_dynamic(self):
        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion, PENTAGONO)
        crear_zona(calibracion, CUADRILATERO)
        self.assertEqual(calibracion.zona_en_punto(20, 20), "C1")
        self.assertEqual(calibracion.vertice_cercano(10, 10, 2), ("C1", 0))
        calibracion.seleccionar_zona("C2")
        self.assertEqual(calibracion.id_seleccionado, "C2")

    def test_mouse_control_selects_and_edits_selected_zone(self):
        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion, CUADRILATERO)
        control = ControlRaton(calibracion)
        control.procesar_evento(cv2.EVENT_LBUTTONDOWN, 40, 40, 0, None)
        self.assertEqual(calibracion.id_seleccionado, "C1")

        control.procesar_evento(cv2.EVENT_LBUTTONDOWN, 10, 10, 0, None)
        control.procesar_evento(cv2.EVENT_MOUSEMOVE, 15, 15, 0, None)
        control.procesar_evento(cv2.EVENT_LBUTTONUP, 15, 15, 0, None)

        self.assertAlmostEqual(calibracion.zonas["C1"].polygon[0][0], 15 / 99)
        self.assertAlmostEqual(calibracion.zonas["C1"].polygon[0][1], 15 / 99)

    def test_overlay_renders_variable_zones_and_draft(self):
        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion, PENTAGONO)
        calibracion.iniciar_nueva_zona()
        calibracion.agregar_punto(5, 5)
        calibracion.agregar_punto(25, 5)
        imagen = np.zeros((300, 400, 3), dtype=np.uint8)
        resultado = dibujar_superposicion(imagen, calibracion, "Prueba")

        self.assertEqual(resultado.shape, imagen.shape)
        self.assertFalse(np.array_equal(resultado, imagen))

    def test_detection_zone_overlay_accepts_dynamic_identifier(self):
        zone = ParkingZone("C1", ((0.1, 0.1), (0.7, 0.1), (0.5, 0.8)))
        snapshots = TemporalOccupancyValidator((zone,)).snapshots()
        display = np.zeros((100, 100, 3), dtype=np.uint8)

        draw_zone_states(display, snapshots, 100, 100)

        self.assertFalse(np.array_equal(display, np.zeros_like(display)))

    def test_still_image_runtime_draws_confirms_saves_and_reloads(self):
        with tempfile.TemporaryDirectory() as directorio:
            directory = Path(directorio)
            image_path = directory / "view.png"
            zones_path = directory / "zones.json"
            image = np.full((100, 100, 3), 45, dtype=np.uint8)
            self.assertTrue(cv2.imwrite(str(image_path), image))
            args = argparse.Namespace(
                source="image",
                image=image_path,
                zones=zones_path,
                preview=False,
                http_url="http://127.0.0.1:4747/video",
                camera_index=None,
                backend="auto",
            )
            callbacks: list[object] = []
            shown: list[np.ndarray] = []
            keys = iter((13, ord("s"), ord("q")))

            def register_callback(_window, callback):
                callbacks.append(callback)

            def wait_for_key(_delay):
                if len(shown) == 1:
                    callback = callbacks[0]
                    for x, y in TRIANGULO:
                        callback(cv2.EVENT_LBUTTONDOWN, x, y, 0, None)
                return next(keys)

            with (
                patch("calibrar_zonas.cv2.namedWindow"),
                patch("calibrar_zonas.cv2.setMouseCallback", side_effect=register_callback),
                patch("calibrar_zonas.cv2.imshow", side_effect=lambda _window, frame: shown.append(frame.copy())),
                patch("calibrar_zonas.cv2.waitKey", side_effect=wait_for_key),
                patch("calibrar_zonas.cv2.getWindowProperty", return_value=1),
                patch("calibrar_zonas.cv2.destroyAllWindows") as close_windows,
            ):
                self.assertEqual(ejecutar(args), 0)

            loaded = cargar_calibracion(zones_path, 100, 100)
            self.assertEqual(tuple(loaded.zonas), ("C1",))
            self.assertEqual(len(shown), 3)
            self.assertEqual(shown[0].shape, image.shape)
            self.assertTrue(close_windows.called)
            self.assertEqual(list(directory.glob(".zones.json.*.tmp")), [])

    def test_http_capture_q_releases_capture_and_closes_windows(self):
        capture = Mock()
        frame = np.full((720, 1280, 3), 45, dtype=np.uint8)
        args = argparse.Namespace(
            source="http",
            image=None,
            zones=Path("zones-not-present.json"),
            preview=False,
            http_url="http://127.0.0.1:4747/video",
            camera_index=None,
            backend="auto",
        )
        with (
            patch(
                "calibrar_zonas.open_video_source",
                return_value=(capture, "HTTP source", "FFmpeg", frame),
            ) as open_source,
            patch("calibrar_zonas.cv2.namedWindow"),
            patch("calibrar_zonas.cv2.setMouseCallback"),
            patch("calibrar_zonas.cv2.imshow"),
            patch("calibrar_zonas.cv2.waitKey", return_value=ord("q")),
            patch("calibrar_zonas.cv2.destroyAllWindows") as close_windows,
        ):
            self.assertEqual(ejecutar(args), 0)

        open_source.assert_called_once_with(
            "http", "http://127.0.0.1:4747/video", None, "auto"
        )
        capture.release.assert_called_once_with()
        close_windows.assert_called_once_with()

    def test_saved_dynamic_zone_loads_into_existing_temporal_association(self):
        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion, ((0, 0), (60, 0), (60, 60), (0, 60)))
        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            guardar_calibracion(destino, calibracion, "image")
            zonas_temporales = load_zones(destino)

        self.assertEqual(tuple(zona.identifier for zona in zonas_temporales), ("C1",))
        validator = TemporalOccupancyValidator(zonas_temporales)
        detection = VehicleDetection((10, 10, 15, 20), 0.8, "car")
        validator.process_frame([detection], 100, 100)
        estados = validator.process_frame([detection], 100, 100)

        self.assertEqual(estados[0].identifier, "C1")
        self.assertEqual(estados[0].state, OccupancyState.OCUPADO)

    def test_excessive_overlap_warns_without_blocking_save(self):
        calibracion = CalibracionZonas(100, 100)
        crear_zona(calibracion, CUADRILATERO)
        calibracion.zonas["C2"] = ParkingZone("C2", calibracion.zonas["C1"].polygon)
        calibracion.vision_zone_ids["C2"] = uuid4()
        calibracion.next_c_number = 3

        advertencias = advertencias_solapamiento(calibracion.zonas)
        with tempfile.TemporaryDirectory() as directorio:
            destino = Path(directorio) / "zones.json"
            guardado = guardar_calibracion(destino, calibracion, "image")
            self.assertTrue(destino.exists())

        self.assertTrue(advertencias)
        self.assertTrue(guardado)


if __name__ == "__main__":
    unittest.main()
