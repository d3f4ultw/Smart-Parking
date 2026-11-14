"""Pruebas de publicacion Vision hacia Java."""

import argparse
import os
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

import detect
from estado_local import EstadoLocal
from temporal_validation import ParkingZone, VehicleDetection
from soporte_standalone import SoporteStandalone


class PublicadorVisionTests(SoporteStandalone):
    def test_publicador_recibe_inferencia_vigente_y_se_invalida_ante_cuadro_repetido(self):
        estado = EstadoLocal((self.zone,))
        guardia = detect.FrameQualityGuard()
        publicador = Mock()
        args = argparse.Namespace(imgsz=64, conf=0.3, publicador=publicador)
        frame = np.full((40, 40, 3), 30, dtype=np.uint8)
        with patch.object(detect, "predict", return_value=(object(), 1.0, 1.0)), \
             patch.object(detect, "detections_from_result", return_value=[self.vehicle]):
            detect.inferir(None, frame, args, guardia, estado)
            detect.inferir(None, frame + 1, args, guardia, estado)
            self.assertEqual(publicador.ofrecer.call_count, 2)
            self.assertEqual(publicador.ofrecer.call_args.args[0][0].efectivo, "OCUPADO")
            detect.inferir(None, frame + 1, args, guardia, estado)
            publicador.invalidar.assert_called_once()
            self.assertEqual(publicador.ofrecer.call_count, 2)

    def test_inferencia_ya_desactualizada_no_se_ofrece_al_publicador(self):
        estado = EstadoLocal((self.zone,))
        publicador = Mock()
        args = argparse.Namespace(imgsz=64, conf=0.3, publicador=publicador)
        frame = np.full((40, 40, 3), 30, dtype=np.uint8)
        with patch.object(detect, "predict", return_value=(object(), 1.0, 1.0)), \
             patch.object(detect, "detections_from_result", return_value=[self.vehicle]):
            detect.inferir(None, frame, args, detect.FrameQualityGuard(), estado,
                           confirmar=lambda _actualizar: False)
        publicador.ofrecer.assert_not_called()
        publicador.invalidar.assert_called_once()

    def test_publicador_conserva_instante_de_captura_durante_inferencia(self):
        estado = EstadoLocal((self.zone,))
        publicador = Mock()
        args = argparse.Namespace(imgsz=64, conf=0.3, publicador=publicador)
        frame = np.full((40, 40, 3), 30, dtype=np.uint8)
        momento_captura = time.monotonic() - 1.5
        def predecir(*_argumentos):
            time.sleep(0.05)
            return object(), 1.0, 1.0
        with patch.object(detect, "predict", side_effect=predecir), \
             patch.object(detect, "detections_from_result", return_value=[self.vehicle]):
            detect.inferir(None, frame, args, detect.FrameQualityGuard(), estado,
                           momento_captura=momento_captura)
        argumentos = publicador.ofrecer.call_args.kwargs
        self.assertEqual(argumentos["momento_observacion"], momento_captura)
        edad = (detect.datetime.now(detect.timezone.utc) - argumentos["observado_en"]).total_seconds()
        self.assertGreaterEqual(edad, 1.5)
        self.assertLess(edad, 2.5)

    def test_publicacion_java_requiere_opt_in_explicito_para_cualquier_fuente(self):
        casos = [
            ("imagen", "0", False, False),
            ("imagen", "1", False, False),
            ("imagen", "1", True, True),
            ("simulacion", "0", True, False),
            ("simulacion", "1", False, False),
            ("simulacion", "1", True, True),
            ("camara", "0", False, False),
            ("camara", "0", True, True),
        ]
        for fuente, opt_in, publicar, esperado in casos:
            with self.subTest(fuente=fuente, opt_in=opt_in, publicar=publicar):
                args = argparse.Namespace(zones=Path("zones.json"), model=Path("modelo.pt"),
                                          image=Path("frame.png") if fuente == "imagen" else None,
                                          simulation_dir=Path("simulacion") if fuente == "simulacion" else None,
                                          publish_java=publicar)
                estado = Mock()
                estado.zones = (self.zone,)
                publicador = Mock()
                entorno = {"VISION_SIMULACION_JAVA": opt_in,
                           "VISION_JAVA_URL": "http://api:8080",
                           "VISION_FUENTE_ID": "fuente-de-prueba",
                           "VISION_TOKEN_ARCHIVO": "/token-de-prueba"}
                with patch.dict(os.environ, entorno, clear=True), \
                     patch.object(detect, "inicializar_estado", return_value=estado), \
                     patch.object(detect, "load_model_from_path", return_value=object()), \
                     patch.object(detect, "cargar_configuracion", return_value=object()) as cargar, \
                     patch.object(detect, "PublicadorVision", return_value=publicador), \
                     patch.object(detect, "ejecutar_imagen", return_value=0), \
                     patch.object(detect, "ejecutar_simulacion", return_value=0), \
                     patch.object(detect, "ejecutar_directo", return_value=0), \
                     patch.object(cv2, "destroyAllWindows"):
                    self.assertEqual(detect.run(args), 0)
                self.assertEqual(cargar.call_count, int(esperado))
                self.assertEqual(publicador.iniciar.call_count, int(esperado))
                self.assertEqual(publicador.detener.call_count, int(esperado))



if __name__ == "__main__":
    unittest.main()
