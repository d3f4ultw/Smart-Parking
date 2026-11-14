"""Pruebas de dibujo, controles y runtime de calibracion."""

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

from soporte_calibracion_zonas import (
    CalibracionZonas,
    CUADRILATERO,
    PENTAGONO,
    TRIANGULO,
    ControlRaton,
    MuestraCaptura,
    OccupancyState,
    ParkingZone,
    TemporalOccupancyValidator,
    VehicleDetection,
    _procesar_tecla,
    advertencias_solapamiento,
    cargar_calibracion,
    crear_zona,
    dibujar_superposicion,
    draw_zone_states,
    ejecutar,
    guardar_calibracion,
    load_zones,
    zone_identity_color,
)


class InterfazCalibracionTests(unittest.TestCase):
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

    def test_zone_identity_colors_are_stable_and_separate_from_occupancy(self):
        self.assertEqual(zone_identity_color("C1"), (55, 55, 230))
        self.assertEqual(zone_identity_color("C1"), zone_identity_color("C1"))
        self.assertNotEqual(zone_identity_color("C1"), zone_identity_color("C2"))
        self.assertNotEqual(zone_identity_color("C2"), zone_identity_color("C3"))
        self.assertEqual(zone_identity_color("invalid"), (150, 150, 150))

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
        lector = Mock()
        frame = np.full((720, 1280, 3), 45, dtype=np.uint8)
        muestra = MuestraCaptura("conectada", 1, 1, time.monotonic(), frame, "FFmpeg")
        lector.esperar.return_value = muestra
        lector.detener.return_value = True
        args = argparse.Namespace(
            source="http", image=None, zones=Path("zones-not-present.json"), preview=False,
            http_url="http://127.0.0.1:4747/video", device=None,
        )
        with (
            patch("calibrar_zonas.CapturadorReciente", return_value=lector) as abrir,
            patch("calibrar_zonas.cv2.namedWindow"),
            patch("calibrar_zonas.cv2.setMouseCallback"),
            patch("calibrar_zonas.cv2.imshow"),
            patch("calibrar_zonas.cv2.waitKey", return_value=ord("q")),
            patch("calibrar_zonas.cv2.destroyAllWindows") as close_windows,
        ):
            self.assertEqual(ejecutar(args), 0)
        abrir.assert_called_once_with("http", "http://127.0.0.1:4747/video", None)
        lector.iniciar.assert_called_once_with()
        lector.detener.assert_called_once_with()
        close_windows.assert_called_once_with()

    def test_http_interrumpido_conserva_borrador_bloquea_guardado_y_reconecta(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "zones.json"
            frames = [np.full((100, 100, 3), x, dtype=np.uint8) for x in (30, 31, 32, 33, 34)]
            ahora = time.monotonic()
            muestras = [
                MuestraCaptura("conectada", 1, 1, ahora, frames[0], "FFmpeg"),
                MuestraCaptura("conectada", 2, 1, ahora, frames[1], "FFmpeg"),
                MuestraCaptura("interrumpida", 3, 1, None, None, "FFmpeg"),
                MuestraCaptura("conectada", 4, 2, ahora, frames[2], "FFmpeg"),
                MuestraCaptura("conectada", 5, 2, ahora, frames[3], "FFmpeg"),
                MuestraCaptura("conectada", 6, 2, ahora, frames[4], "FFmpeg"),
            ]
            lector = Mock()
            lector.esperar.side_effect = muestras
            lector.instantanea.return_value = muestras[4]
            lector.detener.return_value = True
            def confirmar(_muestra, _edad, guardar, **kwargs):
                self.assertTrue(kwargs["misma_revision"])
                guardar()
                return True
            lector.aplicar_si_vigente.side_effect = confirmar
            args = argparse.Namespace(source="http", image=None, zones=ruta, preview=False,
                                      http_url="http://127.0.0.1:4747/video", device=None)
            callbacks = []
            mostrados = []
            def registrar(_titulo, callback):
                callbacks.append(callback)
            def mostrar(_titulo, imagen):
                mostrados.append(imagen)
                if len(mostrados) == 1:
                    for x, y in TRIANGULO:
                        callbacks[0](cv2.EVENT_LBUTTONDOWN, x, y, 0, None)
            pasos = 0
            def tecla(_espera):
                nonlocal pasos
                pasos += 1
                if pasos == 1:
                    return 0  # El poligono sigue siendo un borrador.
                if pasos == 2:
                    callbacks[0](cv2.EVENT_LBUTTONDOWN, 40, 40, 0, None)
                    return ord("s")  # Fuente interrumpida: no debe persistir.
                if pasos == 3:
                    self.assertFalse(ruta.exists())
                    return 13  # Confirma el mismo borrador tras la reconexion.
                if pasos == 4:
                    return ord("s")
                self.assertTrue(ruta.exists())
                return ord("q")
            with (
                patch("calibrar_zonas.CapturadorReciente", return_value=lector) as abrir,
                patch("calibrar_zonas.cv2.namedWindow"),
                patch("calibrar_zonas.cv2.setMouseCallback", side_effect=registrar),
                patch("calibrar_zonas.cv2.imshow", side_effect=mostrar),
                patch("calibrar_zonas.cv2.waitKey", side_effect=tecla),
                patch("calibrar_zonas.cv2.getWindowProperty", return_value=1),
                patch("calibrar_zonas.cv2.destroyAllWindows"),
                patch("calibrar_zonas.dibujar_superposicion", wraps=dibujar_superposicion) as dibujo,
            ):
                self.assertEqual(ejecutar(args), 0)
            cargada = cargar_calibracion(ruta, 100, 100)
            self.assertEqual(tuple(cargada.zonas), ("C1",))
            self.assertEqual(len(cargada.zonas["C1"].polygon), 3)
            self.assertTrue(any("NO VERIFICABLE" in llamada.args[2] for llamada in dibujo.call_args_list))
            abrir.assert_called_once_with("http", "http://127.0.0.1:4747/video", None)
            lector.detener.assert_called_once()
            lector.aplicar_si_vigente.assert_called_once()

    def test_calibracion_bloquea_guardado_si_solo_hay_marca_sobre_oscuro(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "zones.json"
            claro = np.full((100, 100, 3), 50, dtype=np.uint8)
            oscuro = np.full((100, 100, 3), 3, dtype=np.uint8)
            oscuro[3:7, 3:12] = 239
            ahora = time.monotonic()
            muestras = [MuestraCaptura("conectada", 1, 1, ahora, claro, "FFmpeg"),
                        MuestraCaptura("conectada", 2, 1, ahora, oscuro, "FFmpeg"),
                        MuestraCaptura("conectada", 3, 1, ahora, oscuro, "FFmpeg")]
            lector = Mock()
            lector.esperar.side_effect = muestras
            lector.detener.return_value = True
            args = argparse.Namespace(source="http", image=None, zones=ruta, preview=False,
                                      http_url="http://127.0.0.1:4747/video", device=None)
            with (patch("calibrar_zonas.CapturadorReciente", return_value=lector),
                  patch("calibrar_zonas.cv2.namedWindow"),
                  patch("calibrar_zonas.cv2.setMouseCallback"),
                  patch("calibrar_zonas.cv2.imshow"),
                  patch("calibrar_zonas.cv2.waitKey", side_effect=[ord("s"), ord("q")]),
                  patch("calibrar_zonas.cv2.getWindowProperty", return_value=1),
                  patch("calibrar_zonas.cv2.destroyAllWindows")):
                self.assertEqual(ejecutar(args), 0)
            self.assertFalse(ruta.exists())
            lector.aplicar_si_vigente.assert_not_called()


if __name__ == "__main__":
    unittest.main()
