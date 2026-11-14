"""Sincronizacion, atraso y reconexion del lector continuo sin camara fisica."""

from __future__ import annotations

import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import cv2
import numpy as np

import capture
from capture import CapturadorReciente


class EmisorRapido(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.server.conexiones += 1
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for numero in range(1, self.server.cuadros_por_conexion + 1):
                data = self.server.frames[numero - 1]
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
                self.wfile.flush()
                self.server.ultimo_emitido = numero
                time.sleep(0.025)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True


class CapturaRecienteTests(unittest.TestCase):
    def _servidor(self, cuadros_por_conexion: int):
        try:
            servidor = ThreadingHTTPServer(("127.0.0.1", 0), EmisorRapido)
        except PermissionError:
            self.skipTest("El entorno no permite abrir sockets locales para FFmpeg")
        servidor.daemon_threads = True
        servidor.cuadros_por_conexion = cuadros_por_conexion
        servidor.conexiones = 0
        servidor.ultimo_emitido = 0
        servidor.frames = []
        for numero in range(1, cuadros_por_conexion + 1):
            frame = np.full((80, 100, 3), numero, dtype=np.uint8)
            exito, jpeg = cv2.imencode(".jpg", frame)
            self.assertTrue(exito)
            servidor.frames.append(jpeg.tobytes())
        hilo = threading.Thread(target=servidor.serve_forever,
                                kwargs={"poll_interval": 0.05}, daemon=True)
        hilo.start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(hilo.join, 2)
        self.addCleanup(servidor.shutdown)
        return servidor

    def _lector(self, servidor):
        url = f"http://127.0.0.1:{servidor.server_port}/video"
        lector = CapturadorReciente("http", url, None, pausa_reconexion=0.05)
        lector.iniciar()
        self.addCleanup(lambda: self.assertTrue(lector.detener()))
        return lector

    def _conectada(self, lector, generacion=1):
        limite = time.monotonic() + 5
        revision = -1
        while time.monotonic() < limite:
            muestra = lector.esperar(revision, 0.1)
            revision = muestra.revision
            if muestra.estado == "conectada" and muestra.generacion >= generacion:
                return muestra
        self.fail("El lector no obtuvo la conexion esperada dentro del limite")

    def test_consumidor_lento_obtiene_cuadro_reciente_sin_cola_creciente(self):
        servidor = self._servidor(120)
        lector = self._lector(servidor)
        self._conectada(lector)
        atrasos = []
        for _ in range(7):
            # Simula inferencia 5 FPS, con emisor de ~40 FPS.
            time.sleep(0.2)
            muestra = lector.instantanea()
            self.assertEqual(muestra.estado, "conectada")
            actual = int(muestra.cuadro.mean())
            atrasos.append(servidor.ultimo_emitido - actual)
            self.assertLess(time.monotonic() - muestra.momento, 0.5)
        self.assertLessEqual(max(atrasos), 10, f"Atrasos en cuadros: {atrasos}")
        print(f"Atraso maximo lector continuo: {max(atrasos)} cuadros.")

    def test_reconexion_rechaza_observacion_de_generacion_anterior(self):
        servidor = self._servidor(24)
        lector = self._lector(servidor)
        primera = self._conectada(lector)
        segunda = self._conectada(lector, generacion=2)
        self.assertGreaterEqual(servidor.conexiones, 2)
        self.assertGreater(segunda.generacion, primera.generacion)
        actualizar = Mock()
        self.assertFalse(lector.aplicar_si_vigente(primera, 10.0, actualizar))
        actualizar.assert_not_called()
        self.assertTrue(lector.aplicar_si_vigente(segunda, 10.0, actualizar))
        actualizar.assert_called_once()

    def test_liberacion_es_del_hilo_que_leyo_la_captura(self):
        objeto = Mock()
        frame = np.full((8, 8, 3), 30, dtype=np.uint8)
        hilo_de_liberacion = []
        objeto.release.side_effect = lambda: hilo_de_liberacion.append(threading.current_thread().name)
        def leer(*_args):
            time.sleep(0.03)
            return frame
        with patch.object(capture, "open_video_source", return_value=(objeto, "HTTP", "FFmpeg", frame)), \
             patch.object(capture, "read_frame", side_effect=leer):
            lector = CapturadorReciente("http", "http://localhost/video", None)
            lector.iniciar()
            self._conectada(lector)
            self.assertTrue(lector.detener(timeout=2))
        self.assertEqual(hilo_de_liberacion, ["vision-captura"])

    def test_lectura_bloqueada_no_se_libera_en_paralelo_y_luego_cierra(self):
        objeto = Mock()
        frame = np.full((8, 8, 3), 30, dtype=np.uint8)
        lectura_en_curso = threading.Event()
        permitir_salida = threading.Event()
        hilos_liberacion = []
        objeto.release.side_effect = lambda: hilos_liberacion.append(threading.current_thread().name)
        def leer(*_args):
            lectura_en_curso.set()
            if not permitir_salida.wait(3):
                raise RuntimeError("la prueba no libero la lectura")
            return frame
        with patch.object(capture, "open_video_source", return_value=(objeto, "HTTP", "FFmpeg", frame)), \
             patch.object(capture, "read_frame", side_effect=leer):
            lector = CapturadorReciente("http", "http://localhost/video", None)
            lector.iniciar()
            try:
                self.assertTrue(lectura_en_curso.wait(1))
                self.assertFalse(lector.detener(timeout=0.05))
                objeto.release.assert_not_called()
            finally:
                permitir_salida.set()
                self.assertTrue(lector.detener(timeout=2))
        self.assertEqual(hilos_liberacion, ["vision-captura"])

    def test_muestra_antigua_no_actualiza_estado(self):
        objeto = Mock()
        frame = np.full((8, 8, 3), 30, dtype=np.uint8)
        def leer(*_args):
            time.sleep(0.03)
            return frame
        with patch.object(capture, "open_video_source", return_value=(objeto, "HTTP", "FFmpeg", frame)), \
             patch.object(capture, "read_frame", side_effect=leer):
            lector = CapturadorReciente("http", "http://localhost/video", None)
            lector.iniciar()
            muestra = self._conectada(lector)
            time.sleep(0.05)
            actualizar = Mock()
            self.assertFalse(lector.aplicar_si_vigente(muestra, 0.01, actualizar))
            actualizar.assert_not_called()
            self.assertTrue(lector.detener(timeout=2))

    def test_cambio_de_revision_impide_guardar_sobre_un_frame_no_verificado(self):
        objeto = Mock()
        frame = np.full((8, 8, 3), 30, dtype=np.uint8)
        def leer(*_args):
            time.sleep(0.03)
            return frame
        with patch.object(capture, "open_video_source", return_value=(objeto, "HTTP", "FFmpeg", frame)), \
             patch.object(capture, "read_frame", side_effect=leer):
            lector = CapturadorReciente("http", "http://localhost/video", None)
            lector.iniciar()
            try:
                primera = self._conectada(lector)
                siguiente = lector.esperar(primera.revision, 1)
                self.assertGreater(siguiente.revision, primera.revision)
                guardar = Mock()
                self.assertFalse(lector.aplicar_si_vigente(primera, 2, guardar, misma_revision=True))
                guardar.assert_not_called()
            finally:
                self.assertTrue(lector.detener(timeout=2))


if __name__ == "__main__":
    unittest.main()
