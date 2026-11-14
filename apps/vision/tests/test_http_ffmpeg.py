"""Integracion local HTTP MJPEG/FFmpeg con interrupcion y reapertura reales."""

from __future__ import annotations

import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

from capture import open_video_source, read_frame


class EmisorMJPEG(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    frames = ()

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path != "/video":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for frame in self.frames:
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
                self.wfile.flush()
                time.sleep(0.025)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True


class IntegracionHttpFFmpegTests(unittest.TestCase):
    def test_interrupcion_real_y_reapertura_de_mismo_endpoint(self):
        frames = []
        for i in range(24):
            imagen = np.full((80, 100, 3), 20 + i, dtype=np.uint8)
            exito, jpeg = cv2.imencode(".jpg", imagen)
            self.assertTrue(exito)
            frames.append(jpeg.tobytes())
        EmisorMJPEG.frames = tuple(frames)
        try:
            servidor = ThreadingHTTPServer(("127.0.0.1", 0), EmisorMJPEG)
        except PermissionError:
            self.skipTest("El entorno no permite abrir sockets locales para FFmpeg")
        servidor.daemon_threads = True
        hilo = threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.05},
                                daemon=True)
        hilo.start()
        url = f"http://127.0.0.1:{servidor.server_port}/video"
        captura = None
        try:
            inicio = time.monotonic()
            captura, nombre, backend, primer_frame = open_video_source("http", url, None)
            self.assertEqual(backend, "FFmpeg")
            self.assertEqual(primer_frame.shape, (80, 100, 3))
            leidos = 1
            with self.assertRaisesRegex(RuntimeError, "interrumpida"):
                # El emisor cierra tras 24 cuadros; no se aceptan ciclos ilimitados.
                while leidos <= 30 and time.monotonic() - inicio < 12:
                    read_frame(captura, nombre)
                    leidos += 1
            self.assertGreater(leidos, 1)
            captura.release()
            captura = None
            captura, nombre, backend, nuevo_frame = open_video_source("http", url, None)
            self.assertEqual(backend, "FFmpeg")
            self.assertEqual(nuevo_frame.shape, (80, 100, 3))
            self.assertLess(time.monotonic() - inicio, 15)
        finally:
            if captura is not None:
                captura.release()
            servidor.shutdown()
            servidor.server_close()
            hilo.join(timeout=2)
            self.assertFalse(hilo.is_alive())


if __name__ == "__main__":
    unittest.main()
