"""Pruebas locales del contrato HTTP autenticado de RFID 1."""

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from unittest.mock import patch

from cliente_smartparking import (
    ClienteSmartParking,
    ErrorApi,
    RUTA_LECTURAS,
    validar_url_local,
)


TOKEN_PRUEBA = "credencial-rfid1-sintetica-para-pruebas-123456"
UID_PRUEBA = "04A1B2C3"


class ServidorPrueba(HTTPServer):
    respuestas = []
    solicitudes = []


class ManejadorPrueba(BaseHTTPRequestHandler):
    def do_POST(self):
        longitud = int(self.headers.get("Content-Length", "0"))
        cuerpo = self.rfile.read(longitud)
        self.server.solicitudes.append({
            "ruta": self.path,
            "autorizacion": self.headers.get("Authorization"),
            "idempotencia": self.headers.get("Idempotency-Key"),
            "cuerpo": json.loads(cuerpo.decode("utf-8")),
        })
        estado, contenido, extras = self.server.respuestas.pop(0)
        self.send_response(estado)
        for nombre, valor in extras.items():
            self.send_header(nombre, valor)
        self.send_header("Content-Length", str(len(contenido)))
        self.end_headers()
        if contenido:
            self.wfile.write(contenido)

    def log_message(self, formato, *argumentos):
        return


class ServidorGoteo(ThreadingHTTPServer):
    solicitudes = []
    modo = "body"


class ManejadorGoteo(BaseHTTPRequestHandler):
    def do_POST(self):
        longitud = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(longitud)
        self.server.solicitudes.append(self.headers.get("Idempotency-Key"))
        contenido = b'{"estado":"RECIBIDA","accion":"NINGUNA"}'
        prefijo = (
            b"HTTP/1.1 202 Accepted\r\n"
            b"Content-Type: application/json\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"Connection: close\r\n\r\n"
        )
        tamano = "{:X}\r\n".format(len(contenido)).encode("ascii")
        sufijo = b"\r\n0\r\n\r\n"
        primera = len(self.server.solicitudes) == 1
        try:
            if primera and self.server.modo == "longitud":
                encabezados = (
                    b"HTTP/1.1 202 Accepted\r\nContent-Length: "
                    + b"9" * 5000
                    + b"\r\n\r\n"
                )
                self.connection.sendall(encabezados)
            elif primera and self.server.modo == "chunk_size":
                self.connection.sendall(prefijo + b"+1\r\n")
            elif primera and self.server.modo == "headers":
                for byte in prefijo + tamano + contenido + sufijo:
                    self.connection.sendall(bytes((byte,)))
                    time.sleep(0.015)
            elif primera:
                self.connection.sendall(prefijo + tamano)
                for byte in contenido:
                    self.connection.sendall(bytes((byte,)))
                    time.sleep(0.04)
                self.connection.sendall(sufijo)
            else:
                self.connection.sendall(prefijo + tamano + contenido + sufijo)
        except OSError:
            return

    def log_message(self, formato, *argumentos):
        return


class ClienteSmartParkingTest(unittest.TestCase):
    def setUp(self):
        ServidorPrueba.respuestas = []
        ServidorPrueba.solicitudes = []
        self.servidor = ServidorPrueba(
            ("127.0.0.1", 0), ManejadorPrueba
        )
        self.hilo = threading.Thread(
            target=self.servidor.serve_forever, daemon=True
        )
        self.hilo.start()
        host, puerto = self.servidor.server_address
        self.cliente = ClienteSmartParking(
            "http://{}:{}".format(host, puerto), TOKEN_PRUEBA
        )

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=2)

    @staticmethod
    def respuesta(estado, objeto=None, extras=None):
        contenido = json.dumps(objeto or {}).encode("utf-8")
        return estado, contenido, extras or {
            "Content-Type": "application/json"
        }

    def test_reintento_reutiliza_uuid_y_envia_contrato_exacto(self):
        ServidorPrueba.respuestas = [
            self.respuesta(503),
            self.respuesta(202, {"estado": "RECIBIDA", "accion": "NINGUNA"}),
        ]
        self.cliente.enviar_lectura(42, UID_PRUEBA.lower())
        self.assertEqual(len(ServidorPrueba.solicitudes), 2)
        primera, segunda = ServidorPrueba.solicitudes
        self.assertEqual(primera["ruta"], RUTA_LECTURAS)
        self.assertEqual(primera["autorizacion"], "Bearer " + TOKEN_PRUEBA)
        self.assertTrue(primera["idempotencia"])
        self.assertEqual(primera["idempotencia"], segunda["idempotencia"])
        self.assertEqual(len(primera["idempotencia"]), 36)
        self.assertEqual(
            primera["cuerpo"], {"secuencia": 42, "uid": UID_PRUEBA}
        )

    def test_body_goteado_respeta_deadline_y_api_se_recupera(self):
        ServidorGoteo.solicitudes = []
        ServidorGoteo.modo = "body"
        servidor = ServidorGoteo(("127.0.0.1", 0), ManejadorGoteo)
        servidor.daemon_threads = True
        servidor.block_on_close = False
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        host, puerto = servidor.server_address
        cliente = ClienteSmartParking(
            "http://{}:{}".format(host, puerto),
            TOKEN_PRUEBA,
            tiempo_espera=0.2,
        )
        clave = "f4dd23a6-3a17-4d32-9a57-31fc7b73ab99"
        inicio = time.monotonic()
        try:
            with self.assertRaises(ErrorApi):
                cliente.enviar_lectura(42, UID_PRUEBA, clave)
            transcurrido = time.monotonic() - inicio
            self.assertGreaterEqual(transcurrido, 0.15)
            self.assertLess(transcurrido, 0.75)
            cliente.enviar_lectura(42, UID_PRUEBA, clave)
            self.assertEqual(len(ServidorGoteo.solicitudes), 2)
            self.assertEqual(ServidorGoteo.solicitudes, [clave, clave])
        finally:
            servidor.shutdown()
            servidor.server_close()
            hilo.join(timeout=2)

    def test_status_y_cabeceras_goteados_respetan_deadline_total(self):
        ServidorGoteo.solicitudes = []
        ServidorGoteo.modo = "headers"
        servidor = ServidorGoteo(("127.0.0.1", 0), ManejadorGoteo)
        servidor.daemon_threads = True
        servidor.block_on_close = False
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        host, puerto = servidor.server_address
        cliente = ClienteSmartParking(
            "http://{}:{}".format(host, puerto),
            TOKEN_PRUEBA,
            tiempo_espera=0.2,
        )
        inicio = time.monotonic()
        try:
            with self.assertRaises(ErrorApi):
                cliente.enviar_lectura(
                    42, UID_PRUEBA, "f4dd23a6-3a17-4d32-9a57-31fc7b73ab99"
                )
            transcurrido = time.monotonic() - inicio
            self.assertGreaterEqual(transcurrido, 0.15)
            self.assertLess(transcurrido, 0.75)
            self.assertEqual(len(ServidorGoteo.solicitudes), 1)
        finally:
            servidor.shutdown()
            servidor.server_close()
            hilo.join(timeout=2)

    def test_content_length_decimal_enorme_se_rechaza_sin_conversion(self):
        self._verificar_respuesta_invalida("longitud")

    def test_chunk_size_con_signo_se_rechaza(self):
        self._verificar_respuesta_invalida("chunk_size")

    def _verificar_respuesta_invalida(self, modo):
        ServidorGoteo.solicitudes = []
        ServidorGoteo.modo = modo
        servidor = ServidorGoteo(("127.0.0.1", 0), ManejadorGoteo)
        servidor.daemon_threads = True
        servidor.block_on_close = False
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        host, puerto = servidor.server_address
        cliente = ClienteSmartParking(
            "http://{}:{}".format(host, puerto),
            TOKEN_PRUEBA,
            tiempo_espera=0.3,
        )
        try:
            with self.assertRaises(ErrorApi):
                cliente.enviar_lectura(42, UID_PRUEBA)
            self.assertEqual(len(ServidorGoteo.solicitudes), 1)
        finally:
            servidor.shutdown()
            servidor.server_close()
            hilo.join(timeout=2)

    def test_loopback_numerico_no_resuelve_dns(self):
        ServidorPrueba.respuestas = [
            self.respuesta(202, {"estado": "RECIBIDA", "accion": "NINGUNA"})
        ]
        host, puerto = self.servidor.server_address
        cliente = ClienteSmartParking(
            "http://localhost:{}".format(puerto), TOKEN_PRUEBA
        )
        self.assertEqual(
            cliente.url_base, "http://127.0.0.1:{}".format(puerto)
        )
        with patch(
            "cliente_smartparking.socket.getaddrinfo",
            side_effect=AssertionError("No se debe resolver DNS."),
        ):
            cliente.enviar_lectura(42, UID_PRUEBA)
        self.assertEqual(len(ServidorPrueba.solicitudes), 1)

    def test_401_no_reintenta_ni_expone_credencial_en_error(self):
        ServidorPrueba.respuestas = [self.respuesta(401)]
        with self.assertRaises(ErrorApi) as contexto:
            self.cliente.enviar_lectura(42, UID_PRUEBA)
        self.assertEqual(len(ServidorPrueba.solicitudes), 1)
        self.assertNotIn(TOKEN_PRUEBA, str(contexto.exception))

    def test_respuesta_allow_se_rechaza(self):
        ServidorPrueba.respuestas = [
            self.respuesta(202, {"estado": "RECIBIDA", "accion": "ALLOW"})
        ]
        with self.assertRaises(ErrorApi):
            self.cliente.enviar_lectura(42, UID_PRUEBA)

    def test_uid_y_secuencia_invalidos_no_generan_solicitud(self):
        for secuencia, uid in ((-1, UID_PRUEBA), (0x10000, UID_PRUEBA), (42, "GG")):
            with self.subTest(secuencia=secuencia, uid=uid):
                with self.assertRaises(ValueError):
                    self.cliente.enviar_lectura(secuencia, uid)
        self.assertEqual(ServidorPrueba.solicitudes, [])

    def test_secuencia_ffff_valida_y_10000_rechazada(self):
        ServidorPrueba.respuestas = [
            self.respuesta(202, {"estado": "RECIBIDA", "accion": "NINGUNA"})
        ]
        self.cliente.enviar_lectura(0xFFFF, UID_PRUEBA)
        with self.assertRaises(ValueError):
            self.cliente.enviar_lectura(0x10000, UID_PRUEBA)
        self.assertEqual(len(ServidorPrueba.solicitudes), 1)
        self.assertEqual(
            ServidorPrueba.solicitudes[0]["cuerpo"]["secuencia"], 0xFFFF
        )

    def test_redireccion_no_se_sigue(self):
        destino = "http://127.0.0.1:{}/otro".format(
            self.servidor.server_address[1]
        )
        ServidorPrueba.respuestas = [
            (302, b"", {"Location": destino})
        ]
        with self.assertRaises(ErrorApi):
            self.cliente.enviar_lectura(42, UID_PRUEBA)
        self.assertEqual(len(ServidorPrueba.solicitudes), 1)

    def test_url_externa_se_rechaza(self):
        with self.assertRaises(ValueError):
            validar_url_local("http://example.com:8080")


if __name__ == "__main__":
    unittest.main()
