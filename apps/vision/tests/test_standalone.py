"""Pruebas de ocupacion, panel y reproduccion autonoma."""

import argparse
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

import detect
from estado_local import EstadoLocal
from temporal_validation import ParkingZone, VehicleDetection
from soporte_standalone import SoporteStandalone


class StandaloneTests(SoporteStandalone):
    def test_reconexion_conserva_ultimo_y_exige_confirmacion_nueva(self):
        estado = EstadoLocal((self.zone,))
        self.assertEqual(estado.avanzar([self.vehicle], 100, 100)[0].efectivo, "NO_VERIFICABLE")
        self.assertEqual(estado.avanzar([self.vehicle], 100, 100)[0].efectivo, "OCUPADO")
        estado.invalidar("fuente interrumpida")
        interrumpido = estado.estados()[0]
        self.assertEqual(interrumpido.efectivo, "NO_VERIFICABLE")
        self.assertEqual(interrumpido.ultimo, "OCUPADO")
        self.assertEqual(estado.avanzar([self.vehicle], 100, 100)[0].efectivo, "NO_VERIFICABLE")
        self.assertEqual(estado.avanzar([self.vehicle], 100, 100)[0].efectivo, "OCUPADO")

    def test_vacio_solo_libera_tras_cuatro_frames_validos(self):
        estado = EstadoLocal((self.zone,))
        estado.avanzar([self.vehicle], 100, 100)
        estado.avanzar([self.vehicle], 100, 100)
        for _ in range(3):
            self.assertEqual(estado.avanzar([], 100, 100)[0].efectivo, "OCUPADO")
        self.assertEqual(estado.avanzar([], 100, 100)[0].efectivo, "LIBRE")

    def test_inferencia_invalida_y_frame_repetido_no_liberan(self):
        estado = EstadoLocal((self.zone,))
        guardia = detect.FrameQualityGuard()
        frame = np.full((40, 40, 3), 30, dtype=np.uint8)
        args = argparse.Namespace(imgsz=960, conf=0.3)
        resultado = object()
        with patch.object(detect, "predict", return_value=(resultado, 1.0, 1.0)), \
             patch.object(detect, "detections_from_result", return_value=[self.vehicle]):
            detect.inferir(None, frame, args, guardia, estado)
            detect.inferir(None, frame + 1, args, guardia, estado)
            self.assertEqual(estado.estados()[0].efectivo, "OCUPADO")
            detect.inferir(None, frame + 1, args, guardia, estado)
            self.assertEqual(estado.estados()[0].efectivo, "NO_VERIFICABLE")
            self.assertEqual(estado.estados()[0].ultimo, "OCUPADO")
            self.assertIn("repetido", estado.motivo)
        with patch.object(detect, "predict", side_effect=RuntimeError("error")):
            detect.inferir(None, frame + 2, args, guardia, estado)
            self.assertEqual(estado.estados()[0].ultimo, "OCUPADO")
            self.assertEqual(estado.estados()[0].efectivo, "NO_VERIFICABLE")

    def test_inferencia_finalizada_tras_interrupcion_no_altera_ultimo_estado(self):
        estado = EstadoLocal((self.zone,))
        estado.avanzar([self.vehicle], 100, 100)
        estado.avanzar([self.vehicle], 100, 100)
        frame = np.full((100, 100, 3), 40, dtype=np.uint8)
        args = argparse.Namespace(imgsz=64, conf=0.3)
        with patch.object(detect, "predict", return_value=(object(), 1.0, 1.0)), \
             patch.object(detect, "detections_from_result", return_value=[]):
            _, _, resultado = detect.inferir(None, frame, args, detect.FrameQualityGuard(),
                                              estado, confirmar=lambda _actualizar: False)
        self.assertIsNone(resultado)
        self.assertEqual(estado.estados()[0].efectivo, "NO_VERIFICABLE")
        self.assertEqual(estado.estados()[0].ultimo, "OCUPADO")

    def test_marca_blanca_en_escena_negra_nunca_libera_un_ocupado(self):
        estado = EstadoLocal((self.zone,))
        estado.avanzar([self.vehicle], 100, 100)
        estado.avanzar([self.vehicle], 100, 100)
        frame = np.full((100, 100, 3), 3, dtype=np.uint8)
        frame[3:7, 3:12] = 239
        args = argparse.Namespace(imgsz=64, conf=0.3)
        guardia = detect.FrameQualityGuard()
        with patch.object(detect, "predict") as predictor:
            for _ in range(8):
                _, _, resultado = detect.inferir(None, frame, args, guardia, estado)
                self.assertIsNone(resultado)
                self.assertEqual(estado.estados()[0].efectivo, "NO_VERIFICABLE")
                self.assertEqual(estado.estados()[0].ultimo, "OCUPADO")
            predictor.assert_not_called()

    def test_panel_de_ocho_zonas_separa_estado_y_ultimo_en_dos_lineas(self):
        zones = tuple(ParkingZone(f"C{i}", self.zone.polygon) for i in range(1, 9))
        estado = EstadoLocal(zones)
        for zone in zones:
            estado.ultimos[zone.identifier] = ("OCUPADO", time.monotonic() - 5)
        estados = estado.estados()
        alto, columnas, pagina, paginas, inicio, entradas = detect.distribuir_panel(estados, 720)
        self.assertEqual((alto, columnas, pagina, paginas, inicio), (720, 1, 0, 1, 0))
        self.assertEqual(len(entradas), 8)
        self.assertTrue(all("NO_VERIFICABLE" in item[2] and "Ultimo: OCUPADO" in item[3]
                            for item in entradas))
        self.assertTrue(all(entradas[i + 1][1] - entradas[i][1] >= 34 for i in range(7)))
        frame = np.full((720, 1280, 3), 30, dtype=np.uint8)
        with patch.object(detect.cv2, "putText", wraps=cv2.putText) as texto:
            imagen = detect.renderizar(frame, [self.vehicle], estados, "Prueba")
        escritos = [llamada.args[1] for llamada in texto.call_args_list]
        self.assertIn("C1", escritos)
        self.assertIn("NO_VERIFICABLE", escritos)
        self.assertTrue(any(t.startswith("Ultimo: OCUPADO (") for t in escritos))
        self.assertEqual(imagen.shape, (856, 1540, 3))
        self.assertIn("Prueba", escritos)
        self.assertTrue(np.array_equal(imagen[356:361, 500:505], frame[300:305, 500:505]))

    def test_panel_mas_de_ocho_zonas_muestra_paginas_sin_ocultar_estados(self):
        zones = tuple(ParkingZone(f"C{i}", self.zone.polygon) for i in range(1, 36))
        estados = EstadoLocal(zones).estados()
        alto, columnas, pagina, paginas, inicio, primera = detect.distribuir_panel(estados, 720, 0)
        self.assertEqual((columnas, pagina, paginas, inicio, len(primera)), (2, 0, 2, 0, 28))
        self.assertTrue(all(item[1] + 17 < alto for item in primera))
        _, columnas2, pagina2, paginas2, inicio2, segunda = detect.distribuir_panel(estados, 720, 1)
        self.assertEqual((columnas2, pagina2, paginas2, inicio2, len(segunda)), (1, 1, 2, 28, 7))
        etiquetas = [item[2].split(":", 1)[0] for item in primera + segunda]
        self.assertEqual(etiquetas, [f"C{i}" for i in range(1, 36)])
        frame = np.full((720, 1280, 3), 30, dtype=np.uint8)
        imagen1 = detect.renderizar(frame, [], estados, "Prueba", pagina=0)
        imagen2 = detect.renderizar(frame, [], estados, "Prueba", pagina=1)
        self.assertEqual(imagen1.shape[1], 1800)
        self.assertEqual(imagen2.shape[1], 1540)

    def test_fps_movil_reinicia_tras_pausa_y_descarta_muestras_antiguas(self):
        medidor = detect.MedidorFPS(ventana=2.5)
        self.assertIsNone(medidor.registrar(0.0))
        self.assertAlmostEqual(medidor.registrar(0.1), 10.0)
        self.assertAlmostEqual(medidor.registrar(0.2), 10.0)
        medidor.reiniciar()
        self.assertIsNone(medidor.registrar(20.0))
        self.assertAlmostEqual(medidor.registrar(20.05), 20.0)
        self.assertIsNone(medidor.registrar(23.0))

    def test_simulacion_acepta_repeticiones_sinteticas_y_completa_las_escenas(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for i in range(1, 3):
                cv2.imwrite(str(directory / f"frame_{i:03}.png"),
                            np.full((32, 32, 3), 20 + i, dtype=np.uint8))
            args = argparse.Namespace(simulation_dir=directory, frame_duration=0.001,
                                      frame_duration_override=[], zones=directory / "z.json",
                                      playback_fps=60, no_loop=True, headless=True, imgsz=64, conf=0.3)
            estado = EstadoLocal((self.zone,))
            resultado = object()
            with patch.object(detect, "predict", return_value=(resultado, 1.0, 1.0)) as predictor, \
                 patch.object(detect, "detections_from_result", return_value=[]), \
                 patch.object(detect, "verificar_vinculo"):
                self.assertEqual(detect.ejecutar_simulacion(args, None, estado), 0)
            self.assertGreaterEqual(predictor.call_count, 8)
            self.assertEqual(estado.estados()[0].efectivo, "LIBRE")



if __name__ == "__main__":
    unittest.main()
