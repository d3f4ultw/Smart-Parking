"""Pruebas HTTP locales para la reconciliación y lectura de capturas."""

import json
import io
import socket
import threading
import unittest
import uuid
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

from cliente_capturas import (
    ClienteCapturas,
    RUTA_CAPTURA_ACTIVA,
    RUTA_ESTADO_DISPOSITIVO,
    RUTA_ENTRADAS_RFID2,
    RUTA_LECTURAS,
)
from cliente_smartparking import ErrorApi
from entrada_rfid2 import procesar_trama_entrada_rfid2


CAPTURA_ID = "0123456789abcdef0123456789abcdef"
UID_PRUEBA = "04A1B2C3"


class ServidorCapturas(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), ManejadorCapturas)
        self.captura_activa = {
            "capturaId": CAPTURA_ID,
            "estado": "PENDIENTE",
            "expiraEn": "2026-10-27T12:00:00Z",
        }
        self.lecturas = []
        self.estados = []
        self.autorizaciones_estado = []
        self.codigo_error_lectura = None
        self.entradas_rfid2 = []
        self.respuestas_entrada_rfid2 = []


class ManejadorCapturas(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != RUTA_CAPTURA_ACTIVA:
            self.send_error(404)
            return
        if self.server.captura_activa is None:
            self.send_response(204)
            self.end_headers()
            return
        self._json(200, self.server.captura_activa)

    def do_POST(self):
        cuerpo = self.rfile.read(int(self.headers["Content-Length"]))
        objeto = json.loads(cuerpo) if cuerpo else None
        if self.path == RUTA_ENTRADAS_RFID2:
            self.server.entradas_rfid2.append((
                self.headers.get("Authorization"),
                self.headers.get("Idempotency-Key"),
                objeto,
            ))
            estado, respuesta = (
                self.server.respuestas_entrada_rfid2.pop(0)
                if self.server.respuestas_entrada_rfid2
                else (200, {"resultado": "AUTORIZADA"})
            )
            self._json(estado, respuesta)
            return
        if self.path.endswith("/estado"):
            self.server.estados.append((self.path, objeto))
            self.server.autorizaciones_estado.append(self.headers.get("Authorization"))
            if objeto == {"estado": "ESCANEANDO"}:
                self.server.captura_activa["estado"] = "ESCANEANDO"
            self.send_response(204)
            self.end_headers()
            return
        if self.path != RUTA_LECTURAS:
            self.send_error(404)
            return

        clave = self.headers.get("Idempotency-Key")
        self.server.lecturas.append((clave, objeto))
        if self.server.codigo_error_lectura is not None:
            self._json(409, {
                "codigo": self.server.codigo_error_lectura,
                "mensaje": "La tarjeta no se puede asociar.",
            })
            return
        resultado = {
            "capturaId": CAPTURA_ID,
            "estado": "VISTA_PREVIA",
            "resultado": "PREVIEW_READY",
        }
        if len(self.server.lecturas) == 1:
            contenido = json.dumps(resultado).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(contenido) + 20))
            self.end_headers()
            self.wfile.write(contenido[:1])
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        self._json(200, resultado)

    def _json(self, estado, objeto):
        contenido = json.dumps(objeto).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(contenido)))
        self.end_headers()
        self.wfile.write(contenido)

    def log_message(self, formato, *argumentos):
        pass


class ClienteCapturasTest(unittest.TestCase):
    def setUp(self):
        self.servidor = ServidorCapturas()
        self.hilo = threading.Thread(target=self.servidor.serve_forever)
        self.hilo.start()
        url = "http://127.0.0.1:{}".format(self.servidor.server_port)
        self.cliente = ClienteCapturas(url, "token-sintetico")

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=2)

    def test_consulta_y_estado_usan_rutas_de_dispositivo(self):
        captura = self.cliente.consultar_captura_activa()
        self.assertEqual(captura, {"capturaId": CAPTURA_ID, "estado": "PENDIENTE"})
        self.cliente.informar_escaneando(CAPTURA_ID)
        self.assertEqual(
            self.servidor.estados,
            [(
                "/api/v1/dispositivos/rfid-1/capturas/{}/estado".format(CAPTURA_ID),
                {"estado": "ESCANEANDO"},
            )],
        )

        self.servidor.captura_activa = None
        self.assertIsNone(self.cliente.consultar_captura_activa())

    def test_consulta_admite_vista_previa_sin_devolver_uid(self):
        self.servidor.captura_activa["estado"] = "VISTA_PREVIA"

        captura = self.cliente.consultar_captura_activa()

        self.assertEqual(captura, {"capturaId": CAPTURA_ID, "estado": "VISTA_PREVIA"})
        self.assertNotIn("uid", captura)

    def test_estado_dispositivo_usa_bearer_y_booleano(self):
        self.cliente.informar_estado_dispositivo(True)
        self.cliente.informar_estado_dispositivo(False)

        self.assertEqual(
            self.servidor.estados,
            [
                (RUTA_ESTADO_DISPOSITIVO, {"conectado": True}),
                (RUTA_ESTADO_DISPOSITIVO, {"conectado": False}),
            ],
        )
        self.assertEqual(
            self.servidor.autorizaciones_estado,
            ["Bearer token-sintetico"] * 2,
        )
        with self.assertRaises(ValueError):
            self.cliente.informar_estado_dispositivo(1)

    def test_entrada_rfid2_envia_uuid_uid_y_bearer_y_valida_decision(self):
        lectura_id = str(uuid.uuid4())
        resultado = self.cliente.registrar_entrada_rfid2(UID_PRUEBA.lower(), lectura_id)
        self.assertEqual(resultado, "AUTORIZADA")
        autorizacion, clave, cuerpo = self.servidor.entradas_rfid2[0]
        self.assertEqual(autorizacion, "Bearer token-sintetico")
        self.assertEqual(clave, lectura_id)
        self.assertEqual(cuerpo, {"uid": UID_PRUEBA, "lecturaId": lectura_id})

        self.servidor.respuestas_entrada_rfid2 = [
            (200, {"resultado": "DENEGADA", "motivo": "ENTRADA_PENDIENTE"})
        ]
        self.assertEqual(
            self.cliente.registrar_entrada_rfid2(UID_PRUEBA, lectura_id), "DENEGADA"
        )
        self.servidor.respuestas_entrada_rfid2 = [(200, {"resultado": "ALLOW"})]
        with self.assertRaises(ErrorApi):
            self.cliente.registrar_entrada_rfid2(UID_PRUEBA, str(uuid.uuid4()))

    def test_retry_rfid2_conserva_uuid_y_error_api_no_autoriza(self):
        lectura_id = str(uuid.uuid4())
        self.servidor.respuestas_entrada_rfid2 = [
            (503, {"codigo": "NO_DISPONIBLE"}),
            (200, {"resultado": "AUTORIZADA"}),
        ]
        self.assertEqual(
            self.cliente.registrar_entrada_rfid2(UID_PRUEBA, lectura_id), "AUTORIZADA"
        )
        self.assertEqual(len(self.servidor.entradas_rfid2), 2)
        self.assertEqual(
            self.servidor.entradas_rfid2[0], self.servidor.entradas_rfid2[1]
        )

    def test_errores_http_reales_deniegan_y_conservan_correlacion(self):
        for estado in (400, 500, 503):
            with self.subTest(estado=estado):
                lectura_id = str(uuid.uuid4())
                intentos = 2 if estado == 503 else 1
                self.servidor.entradas_rfid2.clear()
                self.servidor.respuestas_entrada_rfid2 = [
                    (estado, {"codigo": "ERROR_SINTETICO"})
                ] * intentos
                puerto = Mock()
                salida = io.StringIO()

                with redirect_stdout(salida):
                    procesar_trama_entrada_rfid2(
                        "RFID2,{},{}".format(lectura_id, UID_PRUEBA),
                        self.cliente,
                        puerto,
                    )

                puerto.escribir_linea.assert_called_once_with(
                    "RFID2_RESULT,{},DENEGADA".format(lectura_id)
                )
                self.assertEqual(len(self.servidor.entradas_rfid2), intentos)
                self.assertTrue(all(
                    clave == lectura_id and cuerpo["lecturaId"] == lectura_id
                    for _, clave, cuerpo in self.servidor.entradas_rfid2
                ))
                self.assertIn("HTTP {} sin decisión confirmada".format(estado), salida.getvalue())
                self.assertNotIn(UID_PRUEBA, salida.getvalue())
                self.assertNotIn("token-sintetico", salida.getvalue())

    def test_horario_cerrado_preserva_decision_y_trama_serial(self):
        lectura_id = str(uuid.uuid4())
        self.servidor.respuestas_entrada_rfid2 = [
            (200, {"resultado": "DENEGADA", "motivo": "FUERA_DE_HORARIO"})
        ]
        puerto = Mock()
        salida = io.StringIO()

        with redirect_stdout(salida):
            procesar_trama_entrada_rfid2(
                "RFID2,{},{}".format(lectura_id, UID_PRUEBA), self.cliente, puerto
            )

        puerto.escribir_linea.assert_called_once_with(
            "RFID2_RESULT,{},DENEGADA".format(lectura_id)
        )
        self.assertIn("API confirmó DENEGADA", salida.getvalue())

    def test_capacidad_completa_preserva_decision_y_trama_serial(self):
        lectura_id = str(uuid.uuid4())
        self.servidor.respuestas_entrada_rfid2 = [
            (200, {"resultado": "DENEGADA", "motivo": "CAPACIDAD_COMPLETA"})
        ]
        puerto = Mock()
        salida = io.StringIO()

        with redirect_stdout(salida):
            procesar_trama_entrada_rfid2(
                "RFID2,{},{}".format(lectura_id, UID_PRUEBA), self.cliente, puerto
            )

        puerto.escribir_linea.assert_called_once_with(
            "RFID2_RESULT,{},DENEGADA".format(lectura_id)
        )
        self.assertIn("API confirmó DENEGADA", salida.getvalue())
        self.assertNotIn(UID_PRUEBA, salida.getvalue())

    def test_membresia_no_vigente_confirma_denegacion_sin_cambiar_trama(self):
        lectura_id = str(uuid.uuid4())
        self.servidor.respuestas_entrada_rfid2 = [
            (200, {"resultado": "DENEGADA", "motivo": "MEMBRESIA_NO_VIGENTE"})
        ]
        puerto = Mock()
        salida = io.StringIO()
        with redirect_stdout(salida):
            procesar_trama_entrada_rfid2(
                "RFID2,{},{}".format(lectura_id, UID_PRUEBA), self.cliente, puerto
            )
        puerto.escribir_linea.assert_called_once_with(
            "RFID2_RESULT,{},DENEGADA".format(lectura_id)
        )
        self.assertIn("API confirmó DENEGADA", salida.getvalue())
        self.assertNotIn(UID_PRUEBA, salida.getvalue())

    def test_membresia_no_amplia_otros_contratos_de_respuesta(self):
        for respuesta in (
            {"resultado": "DENEGADA", "motivo": "MOTIVO_ARBITRARIO"},
            {"resultado": "AUTORIZADA", "motivo": "MEMBRESIA_NO_VIGENTE"},
            {"resultado": "DENEGADA", "motivo": "MEMBRESIA_NO_VIGENTE", "extra": True},
        ):
            with self.subTest(respuesta=respuesta):
                self.servidor.respuestas_entrada_rfid2 = [(200, respuesta)]
                with self.assertRaises(ErrorApi):
                    self.cliente.registrar_entrada_rfid2(UID_PRUEBA, str(uuid.uuid4()))

    def test_read_reintenta_con_misma_clave_y_cuerpo_tras_respuesta_perdida(self):
        respuesta = self.cliente.enviar_lectura_capturada(CAPTURA_ID, "00af", UID_PRUEBA)
        self.assertEqual(
            respuesta,
            {"capturaId": CAPTURA_ID, "estado": "VISTA_PREVIA", "resultado": "PREVIEW_READY"},
        )
        clave_esperada = str(uuid.uuid5(uuid.UUID(CAPTURA_ID), "00AF"))
        self.assertEqual(len(self.servidor.lecturas), 2)
        self.assertEqual(
            self.servidor.lecturas,
            [
                (
                    clave_esperada,
                    {"capturaId": CAPTURA_ID, "requestId": "00AF", "uid": UID_PRUEBA},
                ),
                (
                    clave_esperada,
                    {"capturaId": CAPTURA_ID, "requestId": "00AF", "uid": UID_PRUEBA},
                ),
            ],
        )

    def test_uid_registrado_se_mapea_a_rechazo_no_terminal_sin_uid(self):
        self.servidor.codigo_error_lectura = "TARJETA_YA_REGISTRADA"

        respuesta = self.cliente.enviar_lectura_capturada(CAPTURA_ID, "0002", UID_PRUEBA)

        self.assertEqual(
            respuesta,
            {
                "capturaId": CAPTURA_ID,
                "estado": "ESCANEANDO",
                "resultado": "TARJETA_YA_REGISTRADA",
            },
        )
        self.assertNotIn(UID_PRUEBA, str(respuesta))
        self.assertEqual(len(self.servidor.lecturas), 1)

    def test_conflicto_distinto_de_uid_registrado_se_rechaza(self):
        self.servidor.codigo_error_lectura = "CAPTURA_NO_VIGENTE"

        with self.assertRaises(ErrorApi):
            self.cliente.enviar_lectura_capturada(CAPTURA_ID, "0003", UID_PRUEBA)
        self.assertEqual(len(self.servidor.lecturas), 1)

    def test_captura_y_request_id_invalidos_no_llegan_a_la_api(self):
        with self.assertRaises(ValueError):
            self.cliente.enviar_lectura_capturada("invalid", "0001", UID_PRUEBA)
        with self.assertRaises(ValueError):
            self.cliente.enviar_lectura_capturada(CAPTURA_ID, "XYZ", UID_PRUEBA)
        self.assertEqual(self.servidor.lecturas, [])


if __name__ == "__main__":
    unittest.main()
