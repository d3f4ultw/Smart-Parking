"""Pruebas del estado de decisiones y reintentos de RFID3."""

import contextlib
import io
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from cliente_smartparking import ErrorApi
from soporte_salida_rfid3 import (
    ClienteControlado,
    GestorSalidaRfid3,
    PuertoFalso,
    UID,
    esperar_resultado,
)


class GestorSalidaTest(unittest.TestCase):
    def setUp(self):
        self.id = str(uuid.uuid4())
        self.puerto = PuertoFalso()

    def trama(self, uid=UID, lectura_id=None):
        return "RFID3,{},{}".format(lectura_id or self.id, uid)

    def test_retransmision_en_vuelo_y_terminal_se_agrupa(self):
        cliente = ClienteControlado(espera=True)
        gestor = GestorSalidaRfid3(cliente)
        gestor.recibir(self.trama(), self.puerto)
        gestor.recibir(self.trama(), self.puerto)
        self.assertEqual(self.puerto.lineas, [])
        cliente.liberar.set()
        esperar_resultado(gestor, self.puerto)
        gestor.recibir(self.trama(), self.puerto)
        self.assertEqual(len(cliente.solicitudes), 1)
        self.assertEqual(self.puerto.lineas, [
            "RFID3_RESULT,{},AUTORIZADA".format(self.id),
            "RFID3_RESULT,{},AUTORIZADA".format(self.id),
        ])

    def test_error_terminal_rechaza_retransmisiones_sin_reenviar(self):
        cliente = ClienteControlado(resultado=ErrorApi("timeout"))
        gestor = GestorSalidaRfid3(cliente)
        gestor.recibir(self.trama(), self.puerto)
        esperar_resultado(gestor, self.puerto)
        gestor.recibir(self.trama(), self.puerto)
        self.assertEqual(len(cliente.solicitudes), 1)
        self.assertEqual(self.puerto.lineas, [
            "RFID3_RESULT,{},DENEGADA".format(self.id),
            "RFID3_RESULT,{},DENEGADA".format(self.id),
        ])

    def test_cada_retransmision_extiende_retencion_de_denegacion(self):
        tiempo = [0.0]
        cliente = ClienteControlado(resultado="DENEGADA")
        gestor = GestorSalidaRfid3(cliente, reloj=lambda: tiempo[0])
        gestor.recibir(self.trama(), self.puerto)
        esperar_resultado(gestor, self.puerto)
        tiempo[0] = 14.9
        gestor.recibir(self.trama(), self.puerto)
        tiempo[0] = 15.1
        gestor.recibir(self.trama(), self.puerto)
        self.assertEqual(len(cliente.solicitudes), 1)
        self.assertTrue(all(linea.endswith(",DENEGADA") for linea in self.puerto.lineas))

    def test_respuesta_tardia_no_cambia_denegacion_local(self):
        tiempo = [0.0]
        cliente = ClienteControlado(espera=True)
        gestor = GestorSalidaRfid3(cliente, reloj=lambda: tiempo[0])
        gestor.recibir(self.trama(), self.puerto)
        tiempo[0] = 3.6
        gestor.atender(self.puerto)
        cliente.liberar.set()
        esperar_resultado(gestor, self.puerto)
        gestor.recibir(self.trama(), self.puerto)
        self.assertEqual(len(cliente.solicitudes), 1)
        self.assertEqual(self.puerto.lineas, [
            "RFID3_RESULT,{},DENEGADA".format(self.id),
            "RFID3_RESULT,{},DENEGADA".format(self.id),
        ])

    def test_colision_durante_vuelo_invalida_autorizacion_posterior(self):
        cliente = ClienteControlado(espera=True)
        gestor = GestorSalidaRfid3(cliente)
        gestor.recibir(self.trama(), self.puerto)
        gestor.recibir(self.trama(uid="12345678"), self.puerto)
        cliente.liberar.set()
        esperar_resultado(gestor, self.puerto)
        gestor.recibir(self.trama(), self.puerto)
        self.assertTrue(all(linea.endswith(",DENEGADA") for linea in self.puerto.lineas))
        self.assertEqual(len(cliente.solicitudes), 1)

    def test_capacidad_llena_cierra_durante_drenaje_sin_reenvio(self):
        tiempo = [0.0]
        cliente = ClienteControlado(resultado="DENEGADA")
        gestor = GestorSalidaRfid3(cliente, capacidad=1, reloj=lambda: tiempo[0])
        gestor.recibir(self.trama(), self.puerto)
        esperar_resultado(gestor, self.puerto)
        segundo = str(uuid.uuid4())
        gestor.recibir(self.trama(lectura_id=segundo), self.puerto)
        tiempo[0] = 14.9
        gestor.recibir(self.trama(lectura_id=segundo), self.puerto)
        tiempo[0] = 15.1
        gestor.recibir(self.trama(lectura_id=segundo), self.puerto)
        self.assertEqual(len(cliente.solicitudes), 1)
        self.assertTrue(self.puerto.lineas[-1].endswith(",DENEGADA"))

    def test_tramas_invalidas_y_reinicio_fallan_cerrado(self):
        cliente = ClienteControlado(resultado=ErrorApi("sin conexión"))
        gestor = GestorSalidaRfid3(cliente)
        gestor.recibir("RFID3,no-es-uuid,12345678", self.puerto)
        gestor.recibir(self.trama(uid="no-es-uid"), self.puerto)
        gestor.recibir(self.trama(), self.puerto)
        self.assertEqual(cliente.solicitudes, [])
        self.assertTrue(all(linea.endswith(",DENEGADA") for linea in self.puerto.lineas))
        reiniciado = GestorSalidaRfid3(cliente)
        reiniciado.recibir(self.trama(), self.puerto)
        esperar_resultado(reiniciado, self.puerto)
        self.assertTrue(self.puerto.lineas[-1].endswith(",DENEGADA"))

    def test_api_denegada_se_distingue_de_timeout_sin_registrar_uid(self):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            gestor = GestorSalidaRfid3(ClienteControlado(resultado="DENEGADA"))
            gestor.recibir(self.trama(), self.puerto)
            esperar_resultado(gestor, self.puerto)
        self.assertIn("API confirmó DENEGADA", salida.getvalue())
        self.assertNotIn(UID, salida.getvalue())

        salida = io.StringIO()
        cliente = ClienteControlado(resultado=ErrorApi("timeout", origen="COMUNICACION"))
        with contextlib.redirect_stdout(salida):
            gestor = GestorSalidaRfid3(cliente)
            gestor.recibir(self.trama(), self.puerto)
            esperar_resultado(gestor, self.puerto)
        self.assertIn("sin respuesta API (timeout/comunicación)", salida.getvalue())
        self.assertNotIn("API confirmó DENEGADA", salida.getvalue())
        self.assertTrue(self.puerto.lineas[-1].endswith(",DENEGADA"))




if __name__ == "__main__":
    unittest.main()
