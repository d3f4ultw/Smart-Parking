"""Pruebas aisladas de lectura RFID2 y correlación serial."""

import pathlib
import sys
import time
import unittest

RAIZ_FIRMWARE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ_FIRMWARE))

if not hasattr(time, "ticks_diff"):
    time.ticks_diff = lambda nuevo, anterior: nuevo - anterior

from captura import GestorCaptura
from comunicacion.protocolo import Protocolo
from entrada_rfid2 import GestorEntradaRfid2


class PuertoFalso:
    def __init__(self):
        self.lineas = []

    def enviar_linea(self, texto):
        self.lineas.append(texto + "\n")


class PruebasEntradaRfid2(unittest.TestCase):
    def setUp(self):
        self.puerto = PuertoFalso()
        self.entrada = GestorEntradaRfid2(
            self.puerto, lambda: 0, lambda nuevo, anterior: nuevo - anterior,
            lambda cantidad: bytes(range(cantidad)),
        )
        self.captura = GestorCaptura(self.puerto, lambda: 0)
        self.protocolo = Protocolo(self.puerto, self.captura, lambda: 0, self.entrada)

    def test_uuid_unico_se_conserva_al_reintentar_hasta_respuesta(self):
        uid = bytes((0x04, 0xA1, 0xB2, 0xC3))
        self.assertFalse(self.entrada.procesar_tarjeta(uid, True, 0, 80))
        self.assertTrue(self.entrada.procesar_tarjeta(uid, True, 80, 80))
        lectura_id = self.entrada.pendiente["lectura_id"]
        trama = "RFID2,{},04A1B2C3\n".format(lectura_id)
        self.assertEqual(self.puerto.lineas, [trama])
        self.entrada.actualizar(1580)
        self.assertEqual(self.puerto.lineas, [trama, trama])

        self.protocolo.procesar_linea("RFID2_RESULT,otro-id,AUTORIZADA")
        self.assertIsNotNone(self.entrada.pendiente)
        self.protocolo.procesar_linea(
            "RFID2_RESULT,{},AUTORIZADA".format(lectura_id)
        )
        self.assertIsNone(self.entrada.pendiente)
        self.assertEqual(self.captura.pendiente, None)

    def test_respuesta_denegada_cierra_solo_lectura_correlacionada(self):
        uid = bytes((1, 2, 3, 4))
        self.entrada.procesar_tarjeta(uid, True, 0, 1)
        self.entrada.procesar_tarjeta(uid, True, 1, 1)
        lectura_id = self.entrada.pendiente["lectura_id"]
        self.protocolo.procesar_linea(
            "RFID2_RESULT,{},DENEGADA".format(lectura_id)
        )
        self.assertIsNone(self.entrada.pendiente)

    def test_no_reporta_uid_en_diagnostico_ni_usa_resultado_para_allow(self):
        uid = bytes((0x04, 0xA1, 0xB2, 0xC3))
        self.entrada.procesar_tarjeta(uid, True, 0, 1)
        self.entrada.procesar_tarjeta(uid, True, 1, 1)
        self.assertNotIn("ALLOW", repr(self.puerto.lineas))
        self.assertNotIn("SOUND_SIM", repr(self.puerto.lineas))

    def test_tarjeta_inmovil_no_duplica_y_rearme_requiere_700_ms_de_retiro(self):
        uid = bytes((0x04, 0xA1, 0xB2, 0xC3))
        self.assertFalse(self.entrada.procesar_tarjeta(uid, True, 0, 80))
        self.assertTrue(self.entrada.procesar_tarjeta(uid, True, 80, 80))
        lectura_id = self.entrada.pendiente["lectura_id"]
        self.assertTrue(self.entrada.recibir_resultado(lectura_id, "AUTORIZADA"))

        for ahora in (180, 380, 780):
            self.assertFalse(self.entrada.procesar_tarjeta(uid, True, ahora, 80))
        self.assertEqual(len(self.puerto.lineas), 1)

        self.entrada.procesar_tarjeta(None, False, 1479, 80)
        self.assertEqual(self.entrada.ultimo_uid, uid)
        self.entrada.procesar_tarjeta(None, False, 1480, 80)
        self.assertIsNone(self.entrada.ultimo_uid)
        self.assertFalse(self.entrada.procesar_tarjeta(uid, True, 1481, 80))
        self.assertTrue(self.entrada.procesar_tarjeta(uid, True, 1561, 80))
        self.assertEqual(len(self.puerto.lineas), 2)


if __name__ == "__main__":
    unittest.main()
