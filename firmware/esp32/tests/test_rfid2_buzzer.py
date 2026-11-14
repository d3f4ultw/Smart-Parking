"""Pruebas enfocadas del sonido asociado a decisiones RFID2 correlacionadas."""

import pathlib
import sys
import unittest

RAIZ_FIRMWARE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ_FIRMWARE))

from entrada_rfid2 import GestorEntradaRfid2


class PuertoFalso:
    def __init__(self):
        self.lineas = []

    def enviar_linea(self, texto):
        self.lineas.append(texto + "\n")


class ZumbadorFalso:
    def __init__(self):
        self.patrones = []

    def programar(self, cantidad):
        self.patrones.append(cantidad)


class PruebasBuzzerRfid2(unittest.TestCase):
    def setUp(self):
        self.puerto = PuertoFalso()
        self.zumbador = ZumbadorFalso()
        self.entrada = GestorEntradaRfid2(
            self.puerto, lambda: 0, lambda nuevo, anterior: nuevo - anterior,
            lambda cantidad: bytes(range(cantidad)), zumbador=self.zumbador,
        )

    def iniciar_lectura(self, uid=bytes((1, 2, 3, 4))):
        self.assertFalse(self.entrada.procesar_tarjeta(uid, True, 0, 1))
        self.assertTrue(self.entrada.procesar_tarjeta(uid, True, 1, 1))
        return self.entrada.pendiente["lectura_id"]

    def test_autorizada_programa_un_pitido_y_duplicado_no_repite(self):
        lectura_id = self.iniciar_lectura()
        self.assertTrue(self.entrada.recibir_resultado(lectura_id, "AUTORIZADA"))
        self.assertFalse(self.entrada.recibir_resultado(lectura_id, "AUTORIZADA"))
        self.assertEqual(self.zumbador.patrones, [1])

    def test_denegada_por_decision_api_programa_dos_pitidos(self):
        lectura_id = self.iniciar_lectura()
        self.assertTrue(self.entrada.recibir_resultado(lectura_id, "DENEGADA"))
        self.assertEqual(self.zumbador.patrones, [2])

    def test_respuesta_de_otra_lectura_no_programa_sonido(self):
        lectura_id = self.iniciar_lectura()
        self.assertFalse(self.entrada.recibir_resultado("otra", "DENEGADA"))
        self.assertIsNotNone(self.entrada.pendiente)
        self.assertEqual(self.zumbador.patrones, [])
        self.assertTrue(self.entrada.recibir_resultado(lectura_id, "AUTORIZADA"))
        self.assertEqual(self.zumbador.patrones, [1])

    def test_tres_envios_agotados_programan_dos_y_resultado_tardio_no_repite(self):
        lectura_id = self.iniciar_lectura()
        primera_trama = self.puerto.lineas[0]
        self.entrada.actualizar(1501)
        self.entrada.actualizar(3001)
        self.assertEqual(self.puerto.lineas, [primera_trama] * 3)
        self.entrada.actualizar(4501)
        self.assertIsNone(self.entrada.pendiente)
        self.assertEqual(self.zumbador.patrones, [2])
        self.assertFalse(self.entrada.recibir_resultado(lectura_id, "AUTORIZADA"))
        self.assertEqual(self.zumbador.patrones, [2])


if __name__ == "__main__":
    unittest.main()
