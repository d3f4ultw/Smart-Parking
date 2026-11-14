"""Pruebas sin dispositivo de la autorización de salida RFID3."""

import pathlib
import os
import sys
import unittest
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from captura import GestorCaptura
from comunicacion.protocolo import Protocolo
from salida_rfid3 import GestorSalidaRfid3


class PuertoFalso:
    def __init__(self):
        self.lineas = []
        self.canceladas = []

    def enviar_linea(self, linea):
        self.lineas.append(linea)
        return True

    def cancelar_linea(self, linea):
        self.canceladas.append(linea)

    def leer_lineas(self):
        return ()


class ZumbadorFalso:
    def __init__(self):
        self.patrones = []

    def programar(self, cantidad):
        self.patrones.append(cantidad)
        return True


class PruebasSalidaRfid3(unittest.TestCase):
    def setUp(self):
        self.ahora = 0
        self.puerto = PuertoFalso()
        self.zumbador = ZumbadorFalso()
        self.salida = GestorSalidaRfid3(
            self.puerto, lambda: self.ahora, lambda a, b: a - b,
            lambda cantidad: bytes(range(cantidad)),
            zumbador=self.zumbador,
        )
        captura = GestorCaptura(self.puerto, lambda: self.ahora)
        self.protocolo = Protocolo(self.puerto, captura, lambda: self.ahora, None, self.salida)
        self.uid = bytes((1, 2, 3, 4))

    def iniciar(self):
        self.assertIsNone(self.salida.procesar_tarjeta(self.uid, True, 0, 80))
        evento = self.salida.procesar_tarjeta(self.uid, True, 80, 80)
        self.assertEqual(evento, ("RFID3", "DETECCION", "TARJETA_DETECTADA"))
        return self.salida.pendiente["lectura_id"]

    def test_uuid_v4_unico_para_la_presentacion_y_reintentos_acotados(self):
        lectura = self.iniciar()
        self.assertEqual(uuid.UUID(lectura).version, 4)
        self.assertEqual(uuid.UUID(lectura).variant, uuid.RFC_4122)
        trama = self.puerto.lineas[0]
        self.assertEqual(trama, "RFID3,{},01020304".format(lectura))
        self.salida.actualizar(1580)
        self.salida.actualizar(3080)
        self.assertEqual(self.puerto.lineas, [trama, trama, trama])
        self.salida.actualizar(4580)
        self.assertIsNone(self.salida.pendiente)
        self.assertEqual(self.salida.ultimo_resultado, "DENEGADA")
        self.assertEqual(self.puerto.canceladas, [trama])
        self.assertEqual(self.zumbador.patrones, [2])

    def test_respuesta_cruzada_invalida_duplicada_y_tardia_no_autoriza(self):
        lectura = self.iniciar()
        for trama in ("RFID2_RESULT,{},AUTORIZADA".format(lectura),
                      "RFID3_RESULT,otra,AUTORIZADA", "RFID3_RESULT,{},ALLOW".format(lectura)):
            self.protocolo.procesar_linea(trama)
            self.assertIsNotNone(self.salida.pendiente)
            self.assertEqual(self.zumbador.patrones, [])
        self.ahora = 4580
        self.protocolo.procesar_linea("RFID3_RESULT,{},AUTORIZADA".format(lectura))
        self.assertIsNone(self.salida.pendiente)
        self.assertEqual(self.salida.ultimo_resultado, "DENEGADA")
        self.assertEqual(self.zumbador.patrones, [2])
        self.protocolo.procesar_linea("RFID3_RESULT,{},AUTORIZADA".format(lectura))
        self.assertEqual(self.salida.ultimo_resultado, "DENEGADA")
        self.assertEqual(self.zumbador.patrones, [2])

    def test_autorizacion_programa_un_pitido_y_duplicado_no_repite(self):
        lectura = self.iniciar()
        self.assertEqual(self.zumbador.patrones, [])
        self.ahora = 100
        self.assertTrue(self.salida.recibir_resultado(lectura, "AUTORIZADA"))
        self.assertEqual(self.salida.ultimo_resultado, "AUTORIZADA")
        self.assertFalse(self.salida.recibir_resultado(lectura, "DENEGADA"))
        self.assertEqual(self.salida.ultimo_resultado, "AUTORIZADA")
        self.assertEqual(self.zumbador.patrones, [1])

    def test_denegacion_programa_dos_pitidos_una_vez(self):
        lectura = self.iniciar()
        self.assertEqual(self.zumbador.patrones, [])
        self.ahora = 100
        self.assertTrue(self.salida.recibir_resultado(lectura, "DENEGADA"))
        self.assertFalse(self.salida.recibir_resultado(lectura, "DENEGADA"))
        self.assertEqual(self.zumbador.patrones, [2])

    def test_deteccion_sola_no_programa_sonido(self):
        self.iniciar()
        self.assertEqual(self.zumbador.patrones, [])

    def test_presentacion_observada_durante_ocupacion_exige_retiro(self):
        lectura = self.iniciar()
        otra = bytes((5, 6, 7, 8))
        self.salida.procesar_tarjeta(otra, True, 90, 80)
        self.ahora = 100
        self.salida.recibir_resultado(lectura, "DENEGADA")
        self.salida.procesar_tarjeta(otra, True, 170, 80)
        self.salida.procesar_tarjeta(otra, True, 300, 80)
        self.assertEqual(len(self.puerto.lineas), 1)
        for ahora in (400, 750, 1099):
            self.salida.procesar_tarjeta(None, False, ahora, 80)
        self.assertTrue(self.salida.presentacion_bloqueada)
        self.salida.procesar_tarjeta(None, False, 1100, 80)
        self.assertFalse(self.salida.presentacion_bloqueada)
        self.salida.procesar_tarjeta(otra, True, 1420, 80)
        self.salida.procesar_tarjeta(otra, True, 1500, 80)
        self.assertEqual(len(self.puerto.lineas), 2)

    def test_ausencia_aislada_no_rearma_presentacion_ignorada(self):
        lectura = self.iniciar()
        for ahora in (100, 600, 1100):
            self.salida.procesar_tarjeta(None, False, ahora, 80)
        otra = bytes((5, 6, 7, 8))
        self.salida.procesar_tarjeta(otra, True, 1150, 80)
        self.salida.procesar_tarjeta(None, False, 1160, 80)
        self.ahora = 1170
        self.salida.recibir_resultado(lectura, "DENEGADA")
        self.salida.procesar_tarjeta(otra, True, 1200, 80)
        self.salida.procesar_tarjeta(otra, True, 1280, 80)
        self.assertEqual(len(self.puerto.lineas), 1)
        self.assertTrue(self.salida.presentacion_bloqueada)

    def test_presentacion_nueva_genera_otro_uuid(self):
        contador = [0]

        def aleatorio(cantidad):
            contador[0] += 1
            return bytes([contador[0]]) * cantidad

        self.salida.uuid_aleatorio = aleatorio
        primera = self.iniciar()
        self.salida.recibir_resultado(primera, "DENEGADA")
        for ahora in (100, 600, 1100):
            self.salida.procesar_tarjeta(None, False, ahora, 80)
        self.salida.procesar_tarjeta(self.uid, True, 1150, 80)
        self.salida.procesar_tarjeta(self.uid, True, 1230, 80)
        self.assertNotEqual(primera, self.salida.pendiente["lectura_id"])
        self.assertEqual(contador[0], 2)

    def test_fallo_de_aleatoriedad_no_emite_ni_crea_autorizacion(self):
        for generador in (lambda _: b"", lambda _: (_ for _ in ()).throw(OSError())):
            with self.subTest():
                puerto = PuertoFalso()
                salida = GestorSalidaRfid3(puerto, lambda: 0, lambda a, b: a - b, generador)
                salida.procesar_tarjeta(self.uid, True, 0, 80)
                salida.procesar_tarjeta(self.uid, True, 80, 80)
                self.assertIsNone(salida.pendiente)
                self.assertEqual(salida.ultimo_resultado, "DENEGADA")
                self.assertEqual(puerto.lineas, [])

    def test_ausencia_de_urandom_no_impide_iniciar_ni_autoriza(self):
        generador = os.urandom
        try:
            del os.urandom
            salida = GestorSalidaRfid3(self.puerto, lambda: 0, lambda a, b: a - b)
        finally:
            os.urandom = generador
        salida.procesar_tarjeta(self.uid, True, 0, 80)
        salida.procesar_tarjeta(self.uid, True, 80, 80)
        self.assertIsNone(salida.pendiente)
        self.assertEqual(salida.ultimo_resultado, "DENEGADA")
        self.assertEqual(self.puerto.lineas, [])

    def test_salto_del_reloj_y_wrap_no_extienden_la_ventana(self):
        periodo = 2**30
        diferencia = lambda a, b: ((a - b + periodo // 2) % periodo) - periodo // 2
        salida = GestorSalidaRfid3(self.puerto, lambda: 0, diferencia, lambda n: bytes(range(n)))
        inicio = periodo - 100
        salida.procesar_tarjeta(self.uid, True, inicio, 80)
        salida.procesar_tarjeta(self.uid, True, periodo - 20, 80)
        salida.actualizar(4480)
        self.assertIsNone(salida.pendiente)
        self.assertEqual(salida.ultimo_resultado, "DENEGADA")
        self.assertEqual(len(self.puerto.lineas), 1)


if __name__ == "__main__":
    unittest.main()
