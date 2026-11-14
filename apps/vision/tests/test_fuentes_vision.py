"""Pruebas de seleccion, configuracion y reconexion de fuentes Vision."""

import argparse
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

import capture
import detect
from calibracion_zonas import CalibracionZonas, cargar_calibracion, guardar_calibracion
from configuracion_local import guardar_vinculo, verificar_vinculo
from estado_local import EstadoLocal
from temporal_validation import ParkingZone, VehicleDetection, load_zones
from soporte_standalone import SoporteStandalone


class FuentesVisionTests(SoporteStandalone):
    def test_seleccion_http_y_v4l2_no_sondea_otro_dispositivo(self):
        with patch.object(capture, "open_http_source", side_effect=RuntimeError("fail")) as http, \
             patch.object(capture, "open_camera") as camera:
            with self.assertRaises(RuntimeError):
                capture.open_video_source("http", "http://127.0.0.1:4747/video", None)
            http.assert_called_once()
            camera.assert_not_called()
        cam = Mock()
        frame = np.full((60, 80, 3), 1, np.uint8)
        cam.isOpened.return_value = True
        cam.read.return_value = (True, frame)
        cam.get.return_value = 30.0
        with patch.object(capture.cv2, "VideoCapture", return_value=cam) as constructor:
            opened, _, backend, _ = capture.open_camera("/dev/v4l/by-id/test")
        constructor.assert_called_once_with("/dev/v4l/by-id/test", cv2.CAP_V4L2)
        self.assertIs(opened, cam)
        self.assertEqual(backend, "V4L2")
        with self.assertRaises(ValueError):
            capture.validar_dispositivo("../../etc/passwd")
        with self.assertRaises(ValueError):
            capture.validar_dispositivo(None)

    def test_url_privada_desde_archivo_y_rechazo_de_credenciales(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "url"
            ruta.write_text("http://127.0.0.1:4747/video\n", encoding="utf-8")
            with patch.dict(os.environ, {"VISION_HTTP_URL_FILE": str(ruta)}):
                self.assertEqual(capture.resolver_url_http(None), "http://127.0.0.1:4747/video")
                self.assertEqual(capture.resolver_url_http("http://localhost:123/video"),
                                 "http://localhost:123/video")
                ruta.write_text("una\ndos\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    capture.resolver_url_http(None)
        with self.assertRaises(ValueError):
            capture.resolver_url_http("http://usuario:secreto@localhost:4747/video")

    def test_modelo_ausente_no_importa_ultralytics_ni_descarga(self):
        with patch.dict("sys.modules", {"ultralytics": None}):
            with self.assertRaises(FileNotFoundError):
                detect.load_model_from_path("/ruta/que/no/existe/yolo26n.pt")

    def test_vinculo_y_carga_detectan_fuente_geometria_y_contenido_invalidos(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "zones.json"
            cal = CalibracionZonas(100, 100)
            for x, y in ((10, 10), (90, 10), (90, 90), (10, 90)):
                cal.agregar_punto(x, y)
            cal.confirmar_poligono()
            guardar_calibracion(ruta, cal, "image")
            img = Path(tmp) / "frame_001.png"
            img.write_bytes(b"fixture de referencia local")
            guardar_vinculo(ruta, "image", img, 100, 100)
            with self.assertRaises(ValueError):
                verificar_vinculo(ruta, "simulation", Path(tmp), 200, 200)
            with self.assertRaises(ValueError):
                verificar_vinculo(ruta, "camera", "/dev/video0", 100, 100)
            with self.assertRaises(ValueError):
                verificar_vinculo(ruta, "image", img, 200, 100)
            ruta.write_text("{}", encoding="utf-8")
            verificar_vinculo(ruta, "image", img, 100, 100)
            with self.assertRaises(ValueError):
                cargar_calibracion(ruta, 100, 100)
            with self.assertRaises(ValueError):
                load_zones(ruta)

    def test_reconexion_invalida_y_reconfirma_durante_el_loop(self):
        frames = [np.full((40, 40, 3), x, dtype=np.uint8) for x in (30, 31, 32, 33)]
        ahora = time.monotonic()
        muestras = [
            capture.MuestraCaptura("conectada", 1, 1, ahora, frames[0], "FFmpeg"),
            capture.MuestraCaptura("conectada", 2, 1, ahora, frames[1], "FFmpeg"),
            capture.MuestraCaptura("interrumpida", 3, 1, None, None, "FFmpeg"),
            capture.MuestraCaptura("conectada", 4, 2, ahora, frames[2], "FFmpeg"),
            capture.MuestraCaptura("conectada", 5, 2, ahora, frames[3], "FFmpeg"),
        ]
        capturador = Mock()
        capturador.esperar.side_effect = muestras
        capturador.detener.return_value = True
        def confirmar(_muestra, _edad, accion):
            accion()
            return True
        capturador.aplicar_si_vigente.side_effect = confirmar
        args = argparse.Namespace(source="http", http_url="http://localhost:4747/video", device=None,
                                  zones=Path("zones.json"), headless=True, imgsz=64, conf=0.3)
        estado = EstadoLocal((self.zone,))
        vistos = []
        fuentes = []
        def presentar(_frame, _detecciones, actual, _mensaje, _headless, *, fuente):
            vistos.append((actual.estados()[0].efectivo, actual.estados()[0].ultimo))
            fuentes.append(fuente)
            return len(vistos) < 5
        medidor = detect.MedidorFPS()
        with patch.object(detect, "CapturadorReciente", return_value=capturador), \
             patch.object(detect, "MedidorFPS", return_value=medidor), \
             patch.object(medidor, "reiniciar", wraps=medidor.reiniciar) as reiniciar, \
             patch.object(detect, "verificar_vinculo"), patch.object(detect, "presentar", side_effect=presentar), \
             patch.object(detect, "predict", return_value=(object(), 1.0, 1.0)), \
             patch.object(detect, "detections_from_result", return_value=[self.vehicle]):
            self.assertEqual(detect.ejecutar_directo(args, None, estado), 0)
        self.assertEqual(vistos, [("NO_VERIFICABLE", None), ("OCUPADO", "OCUPADO"),
                                  ("NO_VERIFICABLE", "OCUPADO"),
                                  ("NO_VERIFICABLE", "OCUPADO"), ("OCUPADO", "OCUPADO")])
        self.assertEqual(len(fuentes), 5)
        self.assertTrue(all(fuente for fuente in fuentes))
        capturador.iniciar.assert_called_once()
        capturador.detener.assert_called_once()
        self.assertEqual(reiniciar.call_count, 3)



if __name__ == "__main__":
    unittest.main()
