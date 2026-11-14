"""Aceptación del apagado ordenado y reinicio del proceso bridge."""

import errno
import json
import os
import pty
import select
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


CAPTURA_ID = "0123456789abcdef0123456789abcdef"
RUTA_CAPTURA = "/api/v1/dispositivos/rfid-1/capturas/activa"


class ManejadorApiCaptura(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != RUTA_CAPTURA:
            self.send_error(404)
            return
        self.server.consultas_estado.append(self.server.captura_estado)
        contenido = json.dumps({
            "capturaId": CAPTURA_ID,
            "estado": self.server.captura_estado,
            "expiraEn": "2030-01-01T00:00:00Z",
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(contenido)))
        self.end_headers()
        self.wfile.write(contenido)

    def do_POST(self):
        if self.path != RUTA_CAPTURA.rsplit("/", 1)[0] + "/{}/estado".format(CAPTURA_ID):
            self.send_error(404)
            return
        tamano = int(self.headers.get("Content-Length", "0"))
        cuerpo = json.loads(self.rfile.read(tamano)) if tamano else {}
        if cuerpo != {"estado": "ESCANEANDO"}:
            self.send_error(400)
            return
        self.server.transiciones.append((self.server.captura_estado, cuerpo["estado"]))
        self.server.captura_estado = "ESCANEANDO"
        self.send_response(204)
        self.end_headers()

    def log_message(self, formato, *argumentos):
        pass


class BridgeProcesoTest(unittest.TestCase):
    def test_sigterm_cierra_tty_y_permite_reiniciar_mismo_pty(self):
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), ManejadorApiCaptura)
        servidor.captura_estado = "PENDIENTE"
        servidor.consultas_estado = []
        servidor.transiciones = []
        hilo_servidor = threading.Thread(
            target=servidor.serve_forever, daemon=True
        )
        maestro, esclavo = pty.openpty()
        ruta_pty = os.ttyname(esclavo)
        os.close(esclavo)
        ruta_bridge = Path(__file__).resolve().parents[1] / "bridge.py"
        entorno = os.environ.copy()
        entorno["SMARTPARKING_RFID1_API_URL"] = (
            "http://127.0.0.1:{}".format(servidor.server_port)
        )
        entorno["SMARTPARKING_RFID1_TOKEN"] = "token-sintetico-prueba"
        procesos = []
        hilo_servidor.start()
        try:
            for _ in range(2):
                proceso = subprocess.Popen(
                    [sys.executable, str(ruta_bridge), "--port", ruta_pty],
                    cwd=str(ruta_bridge.parent.parent.parent),
                    env=entorno,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                procesos.append(proceso)
                self.assertTrue(
                    _esperar_trama(maestro, "ENROLL_ARM," + CAPTURA_ID, 5),
                    "El proceso no armó la captura en el mismo PTY.",
                )
                proceso.terminate()
                self.assertEqual(proceso.wait(timeout=5), 0)
            self.assertEqual(servidor.transiciones, [("PENDIENTE", "ESCANEANDO")])
            self.assertIn("ESCANEANDO", servidor.consultas_estado)
        finally:
            for proceso in procesos:
                if proceso.poll() is None:
                    proceso.kill()
                    proceso.wait(timeout=5)
            os.close(maestro)
            servidor.shutdown()
            servidor.server_close()
            hilo_servidor.join(timeout=2)


def _esperar_trama(maestro, trama_esperada, tiempo_espera):
    limite = time.monotonic() + tiempo_espera
    buffer = bytearray()
    while time.monotonic() < limite:
        separador = buffer.find(b"\n")
        if separador >= 0:
            linea = bytes(buffer[:separador]).decode("ascii").removesuffix("\r")
            del buffer[:separador + 1]
            if linea == "PING":
                os.write(maestro, b"PONG\n")
            elif linea == trama_esperada:
                return True
            continue
        listos, _, _ = select.select([maestro], [], [], 0.05)
        if not listos:
            continue
        try:
            buffer.extend(os.read(maestro, 1024))
        except OSError as error:
            if error.errno != errno.EIO:
                raise
    return False


if __name__ == "__main__":
    unittest.main()
