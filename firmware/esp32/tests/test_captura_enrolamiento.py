"""Pruebas de bloqueo de lectura tras capturar una tarjeta RFID1."""

import sys
import time
import unittest
from pathlib import Path

RAIZ_FIRMWARE = Path(__file__).resolve().parents[1]
if str(RAIZ_FIRMWARE) not in sys.path:
    sys.path.insert(0, str(RAIZ_FIRMWARE))

if not hasattr(time, "ticks_diff"):
    time.ticks_diff = lambda nuevo, anterior: nuevo - anterior

from captura import GestorCaptura
from comunicacion.protocolo import Protocolo


class PuertoFalso:
    def __init__(self):
        self.lineas = []

    def enviar_linea(self, linea):
        self.lineas.append(linea)


class SonidoFalso:
    def indicar(self, decision):
        pass


class PruebasBloqueoCapturaRfid1(unittest.TestCase):
    def setUp(self):
        self.puerto = PuertoFalso()
        self.captura = GestorCaptura(self.puerto, lambda: 0, SonidoFalso())
        self.protocolo = Protocolo(self.puerto, self.captura, lambda: 0)
        self.uid_sintetico = bytes((0x04, 0x11, 0x22, 0x33))
        self.pitidos = []

    def _escanear(self, ahora, presente=True, uid=None):
        if self.captura.pendiente is not None:
            return
        secuencia_previa = self.captura.secuencia
        uid = (uid if uid is not None else self.uid_sintetico) if presente else None
        self.captura.procesar_tarjeta(uid, presente, ahora, 80)
        if self.captura.secuencia != secuencia_previa:
            self.pitidos.append(1)

    def _iniciar_y_capturar(self, identificador, inicio=0):
        self.protocolo.procesar_linea("ENROLL_ARM," + identificador)
        self._escanear(inicio)
        self._escanear(inicio + 80)

    def test_cancelar_y_ausencia_no_repite_el_pitido_de_la_captura(self):
        sesion = "a" * 32
        self._iniciar_y_capturar(sesion)
        self.assertEqual(self.pitidos, [1])

        self.captura.resultado(self.captura.pendiente["id"], "DENY")
        self._escanear(100, presente=False)
        self._escanear(1100, presente=False)
        self.assertEqual(self.captura.ultimo_uid, self.uid_sintetico)
        self.assertEqual(self.captura.secuencia, 1)

        self.protocolo.procesar_linea("ENROLL_CANCEL," + sesion)
        self._escanear(1120)
        self._escanear(1200)

        self.assertEqual(self.captura.secuencia, 1)
        self.assertEqual(self.pitidos, [1])
        self.assertIsNone(self.captura.enrolamiento)

    def test_sesion_nueva_acepta_la_misma_tarjeta(self):
        self._iniciar_y_capturar("a" * 32)
        self.captura.resultado(self.captura.pendiente["id"], "DENY")
        self.protocolo.procesar_linea("ENROLL_CANCEL," + "a" * 32)
        self._escanear(1000, presente=False)
        self._escanear(2000, presente=False)
        self.assertEqual(self.pitidos, [1])

        self._iniciar_y_capturar("b" * 32, inicio=2100)

        self.assertEqual(self.captura.secuencia, 2)
        self.assertEqual(self.pitidos, [1, 1])
        self.assertEqual(self.captura.enrolamiento["state"], "CAPTURED")

    def test_rechazo_autoritativo_rearma_solo_la_solicitud_y_acepta_otra_tarjeta(self):
        sesion = "c" * 32
        self._iniciar_y_capturar(sesion)
        request_id = self.captura.pendiente["id"]
        self.captura.resultado(request_id, "DENY")

        self.protocolo.procesar_linea("ENROLL_REARM,{},FFFF".format(sesion))
        self.assertTrue(self.captura.bloqueo_captura_exitosa)
        self.assertEqual(self.captura.enrolamiento["state"], "CAPTURED")

        self.protocolo.procesar_linea(
            "ENROLL_REARM,{},{}".format(sesion, request_id)
        )
        self.assertFalse(self.captura.bloqueo_captura_exitosa)
        self.assertEqual(self.captura.enrolamiento["state"], "REJECTED")

        self._escanear(100)
        self._escanear(180)
        self.assertEqual(self.captura.secuencia, 1)
        self.assertEqual(self.pitidos, [1])

        self._escanear(200, presente=False)
        self._escanear(1200, presente=False)
        tarjeta_b = bytes((0x04, 0x55, 0x66, 0x77))
        self._escanear(1300, uid=tarjeta_b)
        self._escanear(1380, uid=tarjeta_b)

        self.assertEqual(self.captura.secuencia, 2)
        self.assertEqual(self.pitidos, [1, 1])
        self.assertEqual(self.captura.enrolamiento["state"], "CAPTURED")
        self.assertEqual(self.captura.enrolamiento["request_id"], "0002")
        lecturas = [linea for linea in self.puerto.lineas if linea.startswith("ENROLL_READ,")]
        self.assertEqual(len(lecturas), 2)


if __name__ == "__main__":
    unittest.main()
