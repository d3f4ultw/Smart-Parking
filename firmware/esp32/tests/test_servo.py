"""Simulación de servos integrada con los resultados seriales RFID2/RFID3."""

import pathlib
import sys
import unittest
from unittest.mock import patch

RAIZ_FIRMWARE = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ_FIRMWARE) not in sys.path:
    sys.path.insert(0, str(RAIZ_FIRMWARE))

import config
import entrada_rfid2
from captura import GestorCaptura
from comunicacion.protocolo import Protocolo
from entrada_rfid2 import GestorEntradaRfid2
from salida_rfid3 import GestorSalidaRfid3
from soporte_app_diagnostico import SoporteAplicacionDiagnostico, aplicacion
import servo as modulo_servo


class RelojFalso:
    def __init__(self):
        self.ahora = 0

    def ticks_ms(self):
        return self.ahora

    def ticks_diff(self, nuevo, anterior):
        return nuevo - anterior

    def avanzar(self, milisegundos):
        self.ahora += milisegundos


class PWMFalso:
    instancias = []

    def __init__(self, pin, freq, duty_u16):
        self.pin = pin
        self.frecuencia = freq
        self.ciclo = duty_u16
        self.ordenes = [duty_u16]
        self.liberado = False
        self.__class__.instancias.append(self)

    def duty_u16(self, ciclo):
        self.ciclo = ciclo
        self.ordenes.append(ciclo)

    def deinit(self):
        self.liberado = True


class PuertoFalso:
    def __init__(self):
        self.lineas = []
        self.canceladas = []

    def enviar_linea(self, linea):
        self.lineas.append(linea)

    def cancelar_linea(self, linea):
        self.canceladas.append(linea)


class ZumbadorFalso:
    def __init__(self):
        self.patrones = []

    def programar(self, cantidad):
        self.patrones.append(cantidad)


class PruebasServo(SoporteAplicacionDiagnostico):
    def setUp(self):
        PWMFalso.instancias = []
        self.pwm_original = modulo_servo.PWM
        modulo_servo.PWM = PWMFalso
        self.reloj = RelojFalso()
        self.puerto = PuertoFalso()
        self.zumbador_entrada = ZumbadorFalso()
        self.zumbador_salida = ZumbadorFalso()
        self.servo_entrada = self._crear_servo(
            config.PIN_SERVO_ENTRADA_RFID2,
            config.ANGULO_CERRADO_SERVO_RFID2,
            config.ANGULO_ABIERTO_SERVO_RFID2,
            config.PULSO_ABIERTO_SERVO_RFID2_US,
            config.DURACION_SERVO_ENTRADA_ABIERTO_MS,
        )
        self.servo_salida = self._crear_servo(
            config.PIN_SERVO_SALIDA_RFID3,
            config.ANGULO_CERRADO_SERVO_RFID3,
            config.ANGULO_ABIERTO_SERVO_RFID3,
        )
        self.entrada = GestorEntradaRfid2(
            self.puerto, self.reloj.ticks_ms, self.reloj.ticks_diff,
            lambda cantidad: bytes([0x11] * cantidad),
            zumbador=self.zumbador_entrada, servo=self.servo_entrada,
        )
        self.salida = GestorSalidaRfid3(
            self.puerto, self.reloj.ticks_ms, self.reloj.ticks_diff,
            lambda cantidad: bytes([0x22] * cantidad),
            zumbador=self.zumbador_salida, servo=self.servo_salida,
        )
        captura = GestorCaptura(self.puerto, self.reloj.ticks_ms)
        self.protocolo = Protocolo(
            self.puerto, captura, self.reloj.ticks_ms, self.entrada, self.salida,
        )

    def tearDown(self):
        modulo_servo.PWM = self.pwm_original

    def _crear_servo(self, pin, angulo_cerrado, angulo_abierto,
                     pulso_abierto_us=None, duracion_ms=None):
        if duracion_ms is None:
            duracion_ms = config.DURACION_SERVO_ABIERTO_MS
        return modulo_servo.ControladorServo(
            pin, angulo_cerrado, angulo_abierto,
            duracion_ms,
            self.reloj.ticks_ms, self.reloj.ticks_diff,
            pulso_abierto_us=pulso_abierto_us,
        )

    def _iniciar_entrada(self, uid=bytes((1, 2, 3, 4))):
        ahora = self.reloj.ahora
        self.assertFalse(self.entrada.procesar_tarjeta(uid, True, ahora, 80))
        self.reloj.avanzar(80)
        ahora = self.reloj.ahora
        self.assertTrue(self.entrada.procesar_tarjeta(uid, True, ahora, 80))
        return self.entrada.pendiente["lectura_id"]

    def _iniciar_salida(self, uid=bytes((5, 6, 7, 8))):
        ahora = self.reloj.ahora
        self.assertIsNone(self.salida.procesar_tarjeta(uid, True, ahora, 80))
        self.reloj.avanzar(80)
        ahora = self.reloj.ahora
        self.assertEqual(
            self.salida.procesar_tarjeta(uid, True, ahora, 80),
            ("RFID3", "DETECCION", "TARJETA_DETECTADA"),
        )
        return self.salida.pendiente["lectura_id"]

    def _iniciar_ambos(self):
        entrada_uid = bytes((1, 2, 3, 4))
        salida_uid = bytes((5, 6, 7, 8))
        self.assertFalse(self.entrada.procesar_tarjeta(entrada_uid, True, 0, 80))
        self.assertIsNone(self.salida.procesar_tarjeta(salida_uid, True, 0, 80))
        self.reloj.avanzar(80)
        self.assertTrue(self.entrada.procesar_tarjeta(entrada_uid, True, 80, 80))
        self.assertEqual(
            self.salida.procesar_tarjeta(salida_uid, True, 80, 80),
            ("RFID3", "DETECCION", "TARJETA_DETECTADA"),
        )
        return (
            self.entrada.pendiente["lectura_id"],
            self.salida.pendiente["lectura_id"],
        )

    def _actualizar_servos(self):
        self.servo_entrada.actualizar(self.reloj.ahora)
        self.servo_salida.actualizar(self.reloj.ahora)

    def test_gpio_y_pulso_pwm_de_apertura_y_cierre(self):
        self.assertEqual(config.PIN_SERVO_ENTRADA_RFID2, 13)
        self.assertEqual(config.PIN_SERVO_SALIDA_RFID3, 14)
        pwm_entrada = self.servo_entrada.pwm
        pwm_salida = self.servo_salida.pwm
        self.assertEqual(pwm_entrada.pin.numero, 13)
        self.assertEqual(pwm_salida.pin.numero, 14)
        self.assertEqual(pwm_entrada.frecuencia, 50)
        self.assertEqual(pwm_salida.frecuencia, 50)
        self.assertEqual(pwm_salida.ordenes, [4640])
        self.assertEqual(pwm_entrada.ordenes, [4460])
        self.assertEqual(pwm_entrada.ciclo, 4460)

        self.servo_entrada.abrir()
        self.assertEqual(pwm_entrada.ciclo, 2621)
        self.servo_entrada.cerrar()
        self.assertEqual(pwm_entrada.ordenes, [4460, 2621, 4460])

    def test_pulso_calibrado_fuera_de_rango_se_rechaza_antes_de_crear_pwm(self):
        instancias_anteriores = len(PWMFalso.instancias)
        for pulso in (799, 2001):
            with self.assertRaises(ValueError):
                self._crear_servo(13, 65, 90, pulso)
        self.assertEqual(len(PWMFalso.instancias), instancias_anteriores)

    def test_autorizacion_rfid2_abre_entrada_y_cierra_a_los_3500_ms(self):
        lectura_id = self._iniciar_entrada()
        self.protocolo.procesar_linea(
            "RFID2_RESULT,{},AUTORIZADA".format(lectura_id)
        )
        self.assertEqual(self.servo_entrada.pwm.ciclo, 2621)
        self.assertEqual(self.servo_salida.pwm.ciclo, 4640)
        self.assertEqual(self.zumbador_entrada.patrones, [1])

        self.reloj.avanzar(3499)
        self._actualizar_servos()
        self.assertTrue(self.servo_entrada.abierto)
        self.reloj.avanzar(1)
        self._actualizar_servos()
        self.assertFalse(self.servo_entrada.abierto)
        self.assertEqual(self.servo_entrada.pwm.ciclo, 4460)
        self.assertEqual(self.servo_salida.pwm.ciclo, 4640)

    def test_denegacion_rfid2_no_abre_ningun_servo(self):
        lectura_id = self._iniciar_entrada()
        self.protocolo.procesar_linea("RFID2_RESULT,{},DENEGADA".format(lectura_id))
        self.assertEqual(self.servo_entrada.pwm.ordenes, [4460])
        self.assertEqual(self.servo_salida.pwm.ordenes, [4640])
        self.assertEqual(self.zumbador_entrada.patrones, [2])

    def test_autorizacion_rfid3_abre_salida_y_cierra_a_los_3500_ms(self):
        lectura_id = self._iniciar_salida()
        self.protocolo.procesar_linea(
            "RFID3_RESULT,{},AUTORIZADA".format(lectura_id)
        )
        self.assertEqual(self.servo_entrada.pwm.ciclo, 4460)
        self.assertEqual(self.servo_salida.pwm.ciclo, 3365)
        self.assertEqual(self.zumbador_salida.patrones, [1])

        self.reloj.avanzar(3499)
        self._actualizar_servos()
        self.assertTrue(self.servo_salida.abierto)
        self.reloj.avanzar(1)
        self._actualizar_servos()
        self.assertFalse(self.servo_salida.abierto)
        self.assertEqual(self.servo_salida.pwm.ciclo, 4640)
        self.assertEqual(self.servo_entrada.pwm.ciclo, 4460)

    def test_denegacion_rfid3_no_abre_ningun_servo(self):
        lectura_id = self._iniciar_salida()
        self.protocolo.procesar_linea("RFID3_RESULT,{},DENEGADA".format(lectura_id))
        self.assertEqual(self.servo_entrada.pwm.ordenes, [4460])
        self.assertEqual(self.servo_salida.pwm.ordenes, [4640])
        self.assertEqual(self.zumbador_salida.patrones, [2])

    def test_resultados_invalidos_cruzados_o_sin_id_no_abren(self):
        lectura_entrada, lectura_salida = self._iniciar_ambos()
        tramas_invalidas = (
            "RFID2_RESULT,desconocida,AUTORIZADA",
            "RFID2_RESULT,{},ALLOW".format(lectura_entrada),
            "RFID2_RESULT,{},AUTORIZADA".format(lectura_salida),
            "RFID3_RESULT,{},AUTORIZADA".format(lectura_entrada),
            "RFID3_RESULT,{},ALLOW".format(lectura_salida),
        )
        for trama in tramas_invalidas:
            self.protocolo.procesar_linea(trama)

        self.assertEqual(self.servo_entrada.pwm.ordenes, [4460])
        self.assertEqual(self.servo_salida.pwm.ordenes, [4640])
        self.assertIsNotNone(self.entrada.pendiente)
        self.assertIsNotNone(self.salida.pendiente)
        self.assertEqual(self.zumbador_entrada.patrones, [])
        self.assertEqual(self.zumbador_salida.patrones, [])

    def test_resultado_vencido_de_ambos_lectores_no_abre(self):
        lectura_entrada, lectura_salida = self._iniciar_ambos()
        self.reloj.ahora = 1580
        self.entrada.actualizar(self.reloj.ahora)
        self.salida.actualizar(self.reloj.ahora)
        self.reloj.ahora = 3080
        self.entrada.actualizar(self.reloj.ahora)
        self.salida.actualizar(self.reloj.ahora)
        self.reloj.ahora = 4580

        self.protocolo.procesar_linea(
            "RFID2_RESULT,{},AUTORIZADA".format(lectura_entrada)
        )
        self.protocolo.procesar_linea(
            "RFID3_RESULT,{},AUTORIZADA".format(lectura_salida)
        )

        self.assertIsNone(self.entrada.pendiente)
        self.assertIsNone(self.salida.pendiente)
        self.assertEqual(self.servo_entrada.pwm.ordenes, [4460])
        self.assertEqual(self.servo_salida.pwm.ordenes, [4640])
        self.assertEqual(self.zumbador_entrada.patrones, [2])
        self.assertEqual(self.zumbador_salida.patrones, [2])

    def test_temporizadores_de_entrada_y_salida_son_independientes(self):
        lectura_entrada, lectura_salida = self._iniciar_ambos()
        self.protocolo.procesar_linea(
            "RFID2_RESULT,{},AUTORIZADA".format(lectura_entrada)
        )
        self.reloj.avanzar(1000)
        self.protocolo.procesar_linea(
            "RFID3_RESULT,{},AUTORIZADA".format(lectura_salida)
        )
        self.assertTrue(self.servo_entrada.abierto)
        self.assertTrue(self.servo_salida.abierto)

        self.reloj.avanzar(2500)
        self._actualizar_servos()
        self.assertFalse(self.servo_entrada.abierto)
        self.assertTrue(self.servo_salida.abierto)
        self.assertEqual(self.servo_entrada.pwm.ciclo, 4460)
        self.assertEqual(self.servo_salida.pwm.ciclo, 3365)

        self.reloj.avanzar(999)
        self._actualizar_servos()
        self.assertTrue(self.servo_salida.abierto)
        self.reloj.avanzar(1)
        self._actualizar_servos()
        self.assertFalse(self.servo_salida.abierto)
        self.assertEqual(self.servo_salida.pwm.ciclo, 4640)

    def test_el_bucle_de_aplicacion_sigue_atendiendo_ping_con_servo_abierto(self):
        clase_servo_original = aplicacion.ControladorServo
        servos = []

        class ServoAplicacionFalso:
            def __init__(self, pin_numero, angulo_cerrado, angulo_abierto,
                         duracion_abierta_ms, reloj, diferencia_tiempo,
                         pulso_abierto_us=None):
                self.pin_numero = pin_numero
                self.angulo_cerrado = angulo_cerrado
                self.angulo_abierto = angulo_abierto
                self.pulso_abierto_us = pulso_abierto_us
                self.duracion_abierta_ms = duracion_abierta_ms
                self.reloj = reloj
                self.diferencia_tiempo = diferencia_tiempo
                self.abierto = False
                self.inicio = None
                self.actualizaciones_abierto = []
                self.finalizado = False
                servos.append(self)

            def abrir(self):
                self.abierto = True
                self.inicio = self.reloj()

            def actualizar(self, ahora):
                self.actualizaciones_abierto.append(self.abierto)
                if (self.abierto and
                        self.diferencia_tiempo(ahora, self.inicio) >= self.duracion_abierta_ms):
                    self.abierto = False

            def finalizar(self):
                self.abierto = False
                self.finalizado = True

        entradas = [(), (), ("RFID2_RESULT,lectura-fija,AUTORIZADA",), ("PING",)]
        entradas.extend([()] * 34)
        aplicacion.ControladorServo = ServoAplicacionFalso
        try:
            with patch.object(
                entrada_rfid2, "generar_uuid_v4", lambda aleatorio: "lectura-fija",
            ):
                puerto = self.ejecutar_main(
                    None, activos={"RFID2"}, iteraciones=38,
                    entradas_por_iteracion=entradas, intervalo_ms=100,
                )
        finally:
            aplicacion.ControladorServo = clase_servo_original

        self.assertEqual([servo.pin_numero for servo in servos], [13, 14])
        self.assertEqual([servo.pulso_abierto_us for servo in servos], [800, None])
        self.assertEqual([servo.duracion_abierta_ms for servo in servos], [3500, 3500])
        self.assertEqual(servos[0].actualizaciones_abierto.count(True), 36)
        self.assertEqual(servos[1].actualizaciones_abierto.count(True), 0)
        self.assertFalse(servos[0].abierto)
        self.assertFalse(servos[1].abierto)
        self.assertTrue(all(servo.finalizado for servo in servos))
        self.assertIn("PONG", puerto.lineas)


if __name__ == "__main__":
    unittest.main()
