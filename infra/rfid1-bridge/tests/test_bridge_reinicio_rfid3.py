"""Reinicio de proceso bridge con PTY y API sintética que falla cerrada."""

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
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


UID_SINTETICO = "04A1B2C3"
TOKEN_SINTETICO = "token-sintetico-reinicio"
RUTA_SALIDA = "/api/v1/dispositivos/rfid-3/salidas"


class ManejadorApiFallida(BaseHTTPRequestHandler):
    def log_message(self, formato, *argumentos):
        pass

    def do_GET(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        longitud = int(self.headers.get("Content-Length", "0"))
        cuerpo = self.rfile.read(longitud)
        if self.path == RUTA_SALIDA:
            lectura = json.loads(cuerpo)
            valido = (self.headers.get("Authorization") == "Bearer " + TOKEN_SINTETICO
                      and lectura.get("uid") == UID_SINTETICO)
            self.server.solicitudes.append((lectura.get("lecturaId"), valido))
            self.send_response(503)
        else:
            self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()


class EmuladorSerial:
    def __init__(self, maestro):
        self.maestro = maestro
        self.buffer = bytearray()

    def esperar(self, objetivo, tiempo_espera=5):
        limite = time.monotonic() + tiempo_espera
        while time.monotonic() < limite:
            if b"\n" not in self.buffer:
                if not select.select([self.maestro], [], [], 0.05)[0]:
                    continue
                try:
                    self.buffer.extend(os.read(self.maestro, 1024))
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                continue
            linea, _, resto = self.buffer.partition(b"\n")
            self.buffer = bytearray(resto)
            linea = linea.rstrip(b"\r").decode("ascii")
            if linea == "PING":
                os.write(self.maestro, b"PONG\n")
            if linea.startswith("RFID3_RESULT,") and linea.endswith(",AUTORIZADA"):
                raise AssertionError("El bridge inventó una autorización ante la API fallida.")
            if linea == objetivo:
                return
        if objetivo is not None:
            raise AssertionError("El bridge no emitió la trama esperada durante el reinicio.")

    def vaciar(self):
        self.buffer.clear()
        while select.select([self.maestro], [], [], 0)[0]:
            try:
                if not os.read(self.maestro, 1024):
                    return
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                return

    def presentar(self, lectura_id):
        trama = "RFID3,{},{}\n".format(lectura_id, UID_SINTETICO)
        os.write(self.maestro, trama.encode("ascii"))


class BridgeReinicioRfid3Test(unittest.TestCase):
    def test_reinicio_pierde_cache_pero_no_inventa_autorizacion(self):
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), ManejadorApiFallida)
        servidor.solicitudes = []
        hilo_servidor = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo_servidor.start()
        maestro, esclavo = pty.openpty()
        ruta_pty = os.ttyname(esclavo)
        os.close(esclavo)
        serial = EmuladorSerial(maestro)
        ruta_bridge = Path(__file__).resolve().parents[1] / "bridge.py"
        entorno = os.environ.copy()
        entorno["SMARTPARKING_RFID1_API_URL"] = "http://127.0.0.1:{}".format(servidor.server_port)
        entorno["SMARTPARKING_RFID1_TOKEN"] = TOKEN_SINTETICO
        entorno["PYTHONDONTWRITEBYTECODE"] = "1"
        lectura_id = str(uuid.uuid4())
        denegada = "RFID3_RESULT,{},DENEGADA".format(lectura_id)
        procesos = []
        registros = []
        try:
            for numero in range(2):
                proceso = subprocess.Popen(
                    [sys.executable, "-B", str(ruta_bridge), "--port", ruta_pty],
                    cwd=str(ruta_bridge.parent), env=entorno, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                procesos.append(proceso)
                serial.esperar("PING")
                serial.presentar(lectura_id)
                serial.esperar(denegada)
                self.assertEqual(len(servidor.solicitudes), 2 * (numero + 1))
                if numero == 0:
                    # Una retransmisión en el mismo proceso usa la denegación terminal.
                    serial.presentar(lectura_id)
                    serial.esperar(denegada)
                    self.assertEqual(len(servidor.solicitudes), 2)
                    instante_terminal = time.monotonic()
                else:
                    # El UUID vuelve a consultarse al reiniciar antes de vencer los 15 s.
                    self.assertLess(time.monotonic() - instante_terminal, 15)
                serial.esperar(None, tiempo_espera=0.3)
                proceso.terminate()
                registro, _ = proceso.communicate(timeout=5)
                registros.append(registro)
                self.assertEqual(proceso.returncode, 0)
                serial.vaciar()
            self.assertTrue(all(item == (lectura_id, True) for item in servidor.solicitudes))
            self.assertFalse(any(UID_SINTETICO in texto or TOKEN_SINTETICO in texto
                                 for texto in registros))
        finally:
            for proceso in procesos:
                if proceso.poll() is None:
                    proceso.kill()
                    proceso.communicate(timeout=5)
            os.close(maestro)
            servidor.shutdown()
            servidor.server_close()
            hilo_servidor.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
