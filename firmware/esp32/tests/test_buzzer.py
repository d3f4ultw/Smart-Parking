"""Pruebas aisladas del controlador de buzzer con machine y time simulados."""

import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

RAIZ_FIRMWARE = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ_FIRMWARE) not in sys.path:
    sys.path.insert(0, str(RAIZ_FIRMWARE))

from entrada_rfid2 import GestorEntradaRfid2


class RelojFalso:
    def __init__(self):
        self.ahora = 0

    def ticks_ms(self):
        return self.ahora

    def ticks_add(self, instante, delta):
        return instante + delta

    def ticks_diff(self, primero, segundo):
        return primero - segundo

    def avanzar(self, milisegundos):
        self.ahora += milisegundos


class PinFalso:
    OUT = 1

    def __init__(self, numero, modo, value=0):
        self.numero = numero
        self.estado = value

    def value(self, nuevo=None):
        if nuevo is not None:
            self.estado = nuevo
        return self.estado


class PWMFalso:
    def __init__(self, pin, freq, duty_u16):
        self.pin = pin
        self.frecuencia = freq
        self.ciclo = duty_u16
        self.liberado = False

    def duty_u16(self, valor):
        self.ciclo = valor

    def deinit(self):
        self.liberado = True


class BuzzerTest(unittest.TestCase):
    def setUp(self):
        self.reloj = RelojFalso()
        machine = types.ModuleType("machine")
        machine.Pin = PinFalso
        machine.PWM = PWMFalso
        config = types.ModuleType("config")
        config.PIN_ZUMBADOR = 25
        config.PIN_ZUMBADOR_RFID1 = 4
        reloj = types.ModuleType("time")
        reloj.ticks_ms = self.reloj.ticks_ms
        reloj.ticks_add = self.reloj.ticks_add
        reloj.ticks_diff = self.reloj.ticks_diff
        ruta = pathlib.Path(__file__).parents[1] / "buzzer.py"
        spec = importlib.util.spec_from_file_location("buzzer_bajo_prueba", ruta)
        self.modulo = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "machine": machine,
            "config": config,
            "time": reloj,
        }):
            spec.loader.exec_module(self.modulo)

    def test_un_pitido_dura_150_ms_y_termina_inactivo(self):
        buzzer = self.modulo.ControladorZumbador()
        self.assertEqual(buzzer.pin.numero, 25)
        self.assertEqual(buzzer.pin.estado, 0)
        self.assertTrue(buzzer.programar(1))
        self.assertEqual(buzzer.pin.estado, 1)
        self.reloj.avanzar(149)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 1)
        self.reloj.avanzar(1)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 0)
        self.reloj.avanzar(300)
        self.assertFalse(buzzer.actualizar())

    def test_compensacion_rfid3_acorta_pitidos_y_conserva_pausa(self):
        zumbadores = [
            self.modulo.ControladorZumbador(pin_numero=4),
            self.modulo.ControladorZumbador(pin_numero=21),
            self.modulo.ControladorZumbador(pin_numero=25, duracion_pitido_ms=130),
        ]

        self.assertEqual([buzzer.pin.numero for buzzer in zumbadores], [4, 21, 25])
        self.assertEqual([buzzer.duracion_pitido_ms for buzzer in zumbadores], [150, 150, 130])
        for buzzer in zumbadores:
            self.assertTrue(buzzer.programar(2))
            self.assertEqual(buzzer.pin.estado, 1)

        self.reloj.avanzar(130)
        for buzzer in zumbadores:
            self.assertTrue(buzzer.actualizar())
        self.assertEqual([buzzer.pin.estado for buzzer in zumbadores], [1, 1, 0])
        self.assertEqual([buzzer.limite_ms for buzzer in zumbadores], [150, 150, 230])

        self.reloj.avanzar(20)
        for buzzer in zumbadores:
            self.assertTrue(buzzer.actualizar())
        self.assertEqual([buzzer.pin.estado for buzzer in zumbadores], [0, 0, 0])
        self.assertEqual([buzzer.limite_ms for buzzer in zumbadores], [250, 250, 230])

        self.reloj.avanzar(80)
        for buzzer in zumbadores:
            self.assertTrue(buzzer.actualizar())
        self.assertEqual([buzzer.pin.estado for buzzer in zumbadores], [0, 0, 1])

        self.reloj.avanzar(20)
        for buzzer in zumbadores:
            self.assertTrue(buzzer.actualizar())
        self.assertEqual([buzzer.pin.estado for buzzer in zumbadores], [1, 1, 1])

        self.reloj.avanzar(130)
        for buzzer in zumbadores:
            self.assertTrue(buzzer.actualizar())
        self.assertEqual([buzzer.pin.estado for buzzer in zumbadores], [1, 1, 0])

        self.reloj.avanzar(20)
        for buzzer in zumbadores:
            self.assertTrue(buzzer.actualizar())
        self.assertEqual([buzzer.pin.estado for buzzer in zumbadores], [0, 0, 0])

        self.reloj.avanzar(300)
        for buzzer in zumbadores:
            self.assertFalse(buzzer.actualizar())
            self.assertEqual(buzzer.pin.estado, 0)

    def test_dos_pitidos_separados_por_100_ms(self):
        buzzer = self.modulo.ControladorZumbador()
        self.assertTrue(buzzer.programar(2))
        self.reloj.avanzar(150)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 0)
        self.reloj.avanzar(99)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 0)
        self.reloj.avanzar(1)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 1)
        self.reloj.avanzar(150)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 0)
        self.reloj.avanzar(300)
        self.assertFalse(buzzer.actualizar())

    def test_conserva_patrones_concurrentes_y_los_separa(self):
        buzzer = self.modulo.ControladorZumbador()
        self.assertTrue(buzzer.programar(1))
        self.assertTrue(buzzer.programar(2))
        self.assertTrue(buzzer.programar(1))
        self.reloj.avanzar(150)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 0)
        self.reloj.avanzar(299)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 0)
        self.reloj.avanzar(1)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 1)
        self.reloj.avanzar(150)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 0)
        self.reloj.avanzar(100)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 1)
        self.reloj.avanzar(150)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 0)
        self.reloj.avanzar(300)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 1)
        self.reloj.avanzar(150)
        self.assertTrue(buzzer.actualizar())
        self.assertEqual(buzzer.pin.estado, 0)
        self.reloj.avanzar(300)
        self.assertFalse(buzzer.actualizar())

    def test_cola_acotada_rechaza_exceso_y_finalizar_la_limpia(self):
        buzzer = self.modulo.ControladorZumbador()
        self.assertTrue(buzzer.programar(1))
        for _ in range(self.modulo.MAXIMO_PATRONES_ESPERA):
            self.assertTrue(buzzer.programar(2))
        self.assertFalse(buzzer.programar(1))
        self.assertFalse(buzzer.programar(3))
        self.assertEqual(len(buzzer.patrones_pendientes), self.modulo.MAXIMO_PATRONES_ESPERA)
        buzzer.finalizar()
        self.assertEqual(buzzer.patrones_pendientes, [])
        self.assertEqual(buzzer.pin.estado, 0)
        self.assertEqual(buzzer.fase, "inactivo")

    def test_decision_rfid2_conserva_su_patron_mientras_suena_una_deteccion(self):
        for resultado, cantidad in (("AUTORIZADA", 1), ("DENEGADA", 2)):
            with self.subTest(resultado=resultado):
                buzzer = self.modulo.ControladorZumbador()
                entrada = GestorEntradaRfid2(
                    None, self.reloj.ticks_ms, self.reloj.ticks_diff, zumbador=buzzer,
                )
                self.assertTrue(buzzer.programar(1))
                entrada.pendiente = {
                    "lectura_id": "sintetica",
                    "ultimo_envio": self.reloj.ticks_ms(),
                    "intentos": 1,
                }
                self.assertTrue(entrada.recibir_resultado("sintetica", resultado))
                self.assertEqual(buzzer.patrones_pendientes, [cantidad])
                self.reloj.avanzar(150)
                buzzer.actualizar()
                self.reloj.avanzar(300)
                buzzer.actualizar()
                self.assertEqual(buzzer.pin.estado, 1)
                self.assertEqual(buzzer.pitidos_restantes, cantidad)
                buzzer.finalizar()

    def test_pwm_pasivo_y_finalizacion(self):
        buzzer = self.modulo.ControladorZumbador("pasivo")
        pwm = buzzer.pwm
        self.assertEqual(pwm.ciclo, 0)
        self.assertTrue(buzzer.programar(1))
        self.assertEqual(pwm.ciclo, self.modulo.CICLO_ZUMBADOR_U16)
        buzzer.finalizar()
        self.assertTrue(pwm.liberado)
        self.assertIsNone(buzzer.pwm)
        self.assertEqual(pwm.ciclo, 0)


if __name__ == "__main__":
    unittest.main()
