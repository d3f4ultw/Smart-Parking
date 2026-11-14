"""Contrato HTTP del heartbeat manual con Bearer sintético en loopback."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cliente_capturas import ClienteCapturas, RUTA_SALIDAS_MANUALES


DESAFIO = "A" * 22
BOOT = "B" * 21 + "A"
FIRMA = "A" * 16


class Manejador(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.solicitudes.append((self.command, self.path, self.headers.get("Authorization"), None))
        cuerpo = json.dumps({"desafioId": DESAFIO}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_POST(self):
        longitud = int(self.headers["Content-Length"])
        cuerpo = json.loads(self.rfile.read(longitud))
        self.server.solicitudes.append((self.command, self.path, self.headers.get("Authorization"), cuerpo))
        self.send_response(204)
        self.end_headers()

    def log_message(self, _formato, *argumentos):
        pass


class PruebasClienteCapacidad(unittest.TestCase):
    def setUp(self):
        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self.servidor.solicitudes = []
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()
        self.cliente = ClienteCapturas(
            "http://127.0.0.1:{}".format(self.servidor.server_port), "bearer-sintetico"
        )

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=2)

    def test_desafio_confirmacion_y_desconexion_usan_bearer_existente(self):
        self.assertEqual(self.cliente.solicitar_desafio_salida_manual(), DESAFIO)
        self.cliente.confirmar_capacidad_salida_manual(DESAFIO, BOOT, FIRMA)
        self.cliente.invalidar_capacidad_salida_manual()
        self.assertEqual(self.servidor.solicitudes, [
            ("GET", RUTA_SALIDAS_MANUALES + "/capacidad/desafio", "Bearer bearer-sintetico", None),
            ("POST", RUTA_SALIDAS_MANUALES + "/capacidad", "Bearer bearer-sintetico",
             {"desafioId": DESAFIO, "bootId": BOOT, "firma": FIRMA}),
            ("POST", RUTA_SALIDAS_MANUALES + "/capacidad", "Bearer bearer-sintetico",
             {"conectado": False}),
        ])

    def test_tokens_incorrectos_no_se_envian(self):
        for desafio, boot, firma in (("invalido", BOOT, FIRMA), (DESAFIO, "x" * 22, FIRMA),
                                     (DESAFIO, BOOT, "mala")):
            with self.subTest():
                with self.assertRaises(ValueError):
                    self.cliente.confirmar_capacidad_salida_manual(desafio, boot, firma)
        self.assertEqual(self.servidor.solicitudes, [])


if __name__ == "__main__":
    unittest.main()
