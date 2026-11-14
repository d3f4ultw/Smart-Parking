"""Pruebas de ruta, cliente HTTP y puente serial para RFID3."""

import contextlib
import io
import json
import os
import pty
import select
import socket
import threading
import time
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from soporte_salida_rfid3 import (
    ClienteCapturas,
    ClienteControlado,
    ErrorApi,
    PuertoFalso,
    PuertoSerie,
    SesionBridge,
    TOKEN,
    UID,
)


class BridgeRfid3RutaTest(unittest.TestCase):
    def test_bridge_entrega_rfid3_al_cliente_y_correlaciona(self):
        cliente = ClienteControlado()
        sesion = SesionBridge(cliente)
        puerto = PuertoFalso()
        lectura_id = str(uuid.uuid4())
        sesion.procesar_linea("RFID3,{},{}".format(lectura_id, UID), puerto)

        limite = time.monotonic() + 2
        while time.monotonic() < limite and not puerto.lineas:
            sesion.salida_rfid3.atender(puerto)
            time.sleep(0.005)

        self.assertEqual(cliente.solicitudes, [(UID, lectura_id)])
        self.assertEqual(
            puerto.lineas,
            ["RFID3_RESULT,{},AUTORIZADA".format(lectura_id)],
        )


class ManejadorRespuestaPerdida(BaseHTTPRequestHandler):
    def log_message(self, formato, *argumentos):
        pass

    def do_POST(self):
        tamano = int(self.headers["Content-Length"])
        lectura = json.loads(self.rfile.read(tamano))
        self.server.solicitudes.append((self.path, self.headers.get("Authorization"), lectura))
        if len(self.server.solicitudes) == 1:
            self.server.confirmado = lectura
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        cuerpo = b'{"resultado":"AUTORIZADA"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)


class ClienteSalidaTest(unittest.TestCase):
    def test_json_inesperado_jamas_se_interpreta_como_autorizacion(self):
        cliente = ClienteCapturas("http://127.0.0.1:30001", TOKEN)
        lectura_id = str(uuid.uuid4())
        for contenido in (b'{}', b'{"resultado":"AUTORIZADA","motivo":null}',
                          b'{"resultado":"DENEGADA","motivo":"OTRO"}', b'no-json'):
            with self.subTest(contenido=contenido), patch.object(
                cliente, "_solicitar", return_value=(200, contenido)
            ):
                with self.assertRaises(ErrorApi):
                    cliente.registrar_salida_rfid3(UID, lectura_id)

    def test_respuesta_perdida_reintenta_uuid_original(self):
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), ManejadorRespuestaPerdida)
        servidor.solicitudes = []
        servidor.confirmado = None
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        try:
            cliente = ClienteCapturas("http://127.0.0.1:{}".format(servidor.server_port), TOKEN)
            lectura_id = str(uuid.uuid4())
            resultado = cliente.registrar_salida_rfid3(UID, lectura_id)
            self.assertEqual(resultado, "AUTORIZADA")
            self.assertEqual(len(servidor.solicitudes), 2)
            self.assertTrue(all(item[0] == "/api/v1/dispositivos/rfid-3/salidas"
                                and item[1] == "Bearer " + TOKEN
                                and item[2] == {"uid": UID, "lecturaId": lectura_id}
                                for item in servidor.solicitudes))
            self.assertEqual(servidor.confirmado, servidor.solicitudes[1][2])
        finally:
            servidor.shutdown()
            servidor.server_close()
            hilo.join(timeout=2)


class BridgeSalidaPtyTest(unittest.TestCase):
    def test_api_lenta_no_interrumpe_ping_y_fragmentos_se_correlacionan(self):
        class ClienteLento(ClienteControlado):
            def consultar_captura_activa(self):
                time.sleep(0.8)
                return None

            def registrar_salida_rfid3(self, uid, lectura_id):
                time.sleep(0.8)
                return super().registrar_salida_rfid3(uid, lectura_id)

        maestro, esclavo = pty.openpty()
        ruta = os.ttyname(esclavo)
        os.close(esclavo)
        puerto = PuertoSerie(ruta)
        cliente = ClienteLento()
        sesion = SesionBridge(cliente, intervalo_ping=0.08,
                              tiempo_espera_pong=0.45, intervalo_lectura=0.01)
        detener = threading.Event()
        errores = []
        salida = io.StringIO()

        def bucle():
            try:
                sesion.ejecutar(puerto, detener)
            except Exception as error:
                errores.append(type(error).__name__)

        lectura_id = str(uuid.uuid4())
        trama = "RFID3,{},{}\n".format(lectura_id, UID).encode("ascii")
        with contextlib.redirect_stdout(salida):
            hilo = threading.Thread(target=bucle, daemon=True)
            hilo.start()
            try:
                os.write(maestro, b"RFID3,malformada\n" + trama[:20])
                time.sleep(0.02)
                os.write(maestro, trama[20:])
                buffer = bytearray()
                lineas = []
                limite = time.monotonic() + 2.8
                while time.monotonic() < limite:
                    if select.select([maestro], [], [], 0.05)[0]:
                        buffer.extend(os.read(maestro, 4096))
                    while b"\n" in buffer:
                        linea, _, resto = buffer.partition(b"\n")
                        buffer = bytearray(resto)
                        linea = linea.rstrip(b"\r").decode("ascii")
                        lineas.append(linea)
                        if linea == "PING":
                            os.write(maestro, b"PONG\n")
                    if "RFID3_RESULT,{},AUTORIZADA".format(lectura_id) in lineas:
                        break
                self.assertIn("RFID3_RESULT,{},AUTORIZADA".format(lectura_id), lineas)
                self.assertGreaterEqual(lineas.count("PING"), 3)
                self.assertFalse(errores)
                self.assertNotIn(UID, salida.getvalue())
                self.assertNotIn(TOKEN, salida.getvalue())
            finally:
                detener.set()
                hilo.join(timeout=2)
                sesion.estado_dispositivo.cerrar()
                puerto.cerrar()
                os.close(maestro)


if __name__ == "__main__":
    unittest.main()
