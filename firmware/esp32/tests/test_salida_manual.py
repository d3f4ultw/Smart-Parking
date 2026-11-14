"""Contrato del ciclo manual con reloj y PWM simulados, sin tocar la placa."""

import pathlib
import importlib.util
import base64
import hashlib
import hmac
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from captura import GestorCaptura
from comunicacion.protocolo import Protocolo
from salida_manual import GestorSalidaManual
from salida_rfid3 import GestorSalidaRfid3


OPERACION = "ASNFZ4mrze8BI0VniavN7w"
CLAVE = bytes(range(32))  # Únicamente para pruebas aisladas.


def firmar(accion, boot, ticket, codigo=None, operacion=OPERACION):
    texto = "smartparking.manual.v1|{}|{}|{}|{}".format(accion, operacion, boot, ticket)
    if codigo is not None:
        texto += "|" + codigo
    firma = hmac.new(CLAVE, texto.encode("ascii"), hashlib.sha256).digest()[:12]
    return base64.urlsafe_b64encode(firma).decode("ascii")


class PuertoFalso:
    def __init__(self):
        self.lineas = []

    def enviar_linea(self, linea):
        self.lineas.append(linea)
        return True

    def leer_lineas(self):
        return ()

    def cancelar_linea(self, _linea):
        pass


class ServoFalso:
    def __init__(self):
        self.abierto = False
        self.aperturas = 0
        self.error_pwm = False

    def abrir(self):
        self.aperturas += 1
        if self.error_pwm:
            raise OSError("PWM simulado")
        self.abierto = True

    def cerrar(self):
        self.abierto = False


class PruebasSalidaManual(unittest.TestCase):
    def setUp(self):
        self.ahora = 0
        self.contador = 0
        self.puerto = PuertoFalso()
        self.servo = ServoFalso()
        self.rfid3 = GestorSalidaRfid3(
            self.puerto, lambda: self.ahora, lambda a, b: a - b,
            self.aleatorio, servo=self.servo,
        )
        self.manual = GestorSalidaManual(
            self.puerto, self.servo, self.rfid3,
            lambda: self.ahora, lambda a, b: a - b, self.aleatorio, clave=CLAVE,
        )
        self.rfid3.salida_manual = self.manual
        captura = GestorCaptura(self.puerto, lambda: self.ahora)
        self.protocolo = Protocolo(
            self.puerto, captura, lambda: self.ahora, None, self.rfid3, self.manual,
        )

    def aleatorio(self, cantidad):
        self.contador += 1
        return bytes([self.contador]) * cantidad

    def preparar(self):
        self.protocolo.procesar_linea("SM_PREP," + OPERACION)
        partes = self.puerto.lineas[-1].split(",")
        self.assertEqual(partes[:2], ["SM_LISTA", OPERACION])
        return partes[2], partes[3]

    def ejecutar(self, boot, ticket):
        self.protocolo.procesar_linea("SM_EXEC,{},{},{},{}".format(
            OPERACION, boot, ticket, firmar("EXEC", boot, ticket)
        ))

    def test_preparar_no_abre_y_repetir_no_renueva(self):
        boot, ticket = self.preparar()
        self.ahora = 4900
        self.assertEqual((boot, ticket), self.preparar())
        self.assertEqual(self.servo.aperturas, 0)
        self.ahora = 5000
        self.ejecutar(boot, ticket)
        self.assertEqual(self.servo.aperturas, 0)
        self.assertEqual(self.puerto.lineas[-1], "SM_RES,{},{},{},N,{}".format(
            OPERACION, boot, ticket, firmar("RESULT", boot, ticket, "N")
        ))

    def test_abre_una_vez_y_confirma_solo_tras_cierre(self):
        boot, ticket = self.preparar()
        self.ejecutar(boot, ticket)
        self.ejecutar(boot, ticket)
        self.assertEqual(self.servo.aperturas, 1)
        self.manual.actualizar(3500)
        self.assertNotIn("EJECUTADA", self.puerto.lineas[-1])
        self.servo.cerrar()
        self.manual.actualizar(3500)
        esperado = "SM_RES,{},{},{},E,{}".format(
            OPERACION, boot, ticket, firmar("RESULT", boot, ticket, "E")
        )
        self.assertEqual(self.puerto.lineas[-1], esperado)
        self.ejecutar(boot, ticket)
        self.manual.consultar(OPERACION, boot)
        self.assertEqual(self.servo.aperturas, 1)
        self.assertEqual(self.puerto.lineas[-1], esperado)
        self.assertTrue(all(len(linea) <= 96 for linea in self.puerto.lineas))

    def test_ticket_incorrecto_y_boot_viejo_no_ejecutan(self):
        boot, ticket = self.preparar()
        self.ejecutar(boot, "x" * 22)
        nuevo = GestorSalidaManual(
            self.puerto, self.servo, self.rfid3,
            lambda: self.ahora, lambda a, b: a - b, self.aleatorio, clave=CLAVE,
        )
        nuevo.ejecutar(OPERACION, boot, ticket, firmar("EXEC", boot, ticket))
        self.assertEqual(self.servo.aperturas, 0)
        self.assertNotEqual(nuevo.boot_id, boot)

    def test_pwm_incierto_no_fabrica_confirmacion_y_bloquea_otra_apertura(self):
        boot, ticket = self.preparar()
        self.servo.error_pwm = True
        self.ejecutar(boot, ticket)
        self.servo.error_pwm = False
        self.ejecutar(boot, ticket)
        self.manual.consultar(OPERACION, boot)
        self.assertEqual(self.servo.aperturas, 1)
        self.assertTrue(self.manual.bloqueada())
        self.assertFalse(any(linea.startswith("SM_RES,") for linea in self.puerto.lineas))

    def test_error_pwm_al_cerrar_no_emite_acuse_de_exito(self):
        class PwmFalso:
            def __init__(self, *argumentos, **opciones):
                self.fallar = False

            def duty_u16(self, _valor):
                if self.fallar:
                    raise OSError("Cierre PWM simulado")

        maquina = types.SimpleNamespace(Pin=lambda numero: numero, PWM=PwmFalso)
        spec = importlib.util.spec_from_file_location(
            "servo_manual_prueba", pathlib.Path(__file__).resolve().parents[1] / "servo.py"
        )
        modulo = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"machine": maquina}):
            spec.loader.exec_module(modulo)
        servo_real = modulo.ControladorServo(14, 75, 5, 3500, lambda: self.ahora, lambda a, b: a - b)
        self.manual.servo = servo_real
        boot, ticket = self.preparar()
        self.ejecutar(boot, ticket)
        self.ahora = 3500
        servo_real.pwm.fallar = True
        with self.assertRaises(OSError):
            servo_real.actualizar(self.ahora)
        self.manual.consultar(OPERACION, boot)
        self.assertTrue(self.manual.bloqueada())
        self.assertFalse(any(linea.startswith("SM_RES,") for linea in self.puerto.lineas))

    def test_no_preempta_rfid3_ni_abre_si_servo_ocupado(self):
        self.rfid3.pendiente = {"inicio": 0, "ultimo_envio": 0, "intentos": 1}
        self.manual.preparar(OPERACION)
        self.assertTrue(self.puerto.lineas[-1].startswith("SM_OCUPADA,"))
        self.rfid3.pendiente = None
        self.servo.abierto = True
        self.manual.preparar(OPERACION)
        self.assertTrue(self.puerto.lineas[-1].startswith("SM_OCUPADA,"))
        self.assertEqual(self.servo.aperturas, 0)

    def test_bloquea_nuevas_lecturas_durante_reserva_y_ciclo(self):
        boot, ticket = self.preparar()
        uid = bytes((1, 2, 3, 4))
        self.rfid3.procesar_tarjeta(uid, True, 0, 80)
        self.rfid3.procesar_tarjeta(uid, True, 80, 80)
        self.ejecutar(boot, ticket)
        self.rfid3.procesar_tarjeta(uid, True, 160, 80)
        self.assertIsNone(self.rfid3.pendiente)
        self.assertTrue(self.rfid3.presentacion_bloqueada)
        self.assertFalse(any(linea.startswith("RFID3,") for linea in self.puerto.lineas))

    def test_ping_y_protocolo_invalido_no_crean_operacion(self):
        self.protocolo.procesar_linea("PING")
        self.protocolo.procesar_linea("SM_PREP," + "z" * 32)
        self.protocolo.procesar_linea("SM_EXEC,irrelevante")
        self.assertEqual(self.puerto.lineas, ["PONG"])
        self.assertEqual(self.servo.aperturas, 0)

    def test_sin_clave_no_ofrece_capacidad_ni_mueve_servo(self):
        with patch("salida_manual._leer_clave", return_value=None):
            sin_clave = GestorSalidaManual(
                self.puerto, self.servo, self.rfid3,
                lambda: self.ahora, lambda a, b: a - b, self.aleatorio,
            )
        sin_clave.preparar(OPERACION)
        sin_clave.ejecutar(OPERACION, "A" * 22, "A" * 22, "A" * 16)
        self.assertEqual(self.puerto.lineas, [])
        self.assertEqual(self.servo.aperturas, 0)

    def test_sin_sha256_no_habilita_salida_y_ping_sigue_funcionando(self):
        with patch("salida_manual.sha256", None):
            sin_sha = GestorSalidaManual(
                self.puerto, self.servo, self.rfid3,
                lambda: self.ahora, lambda a, b: a - b, self.aleatorio, clave=CLAVE,
            )
        protocolo = Protocolo(self.puerto, None, lambda: self.ahora, salida_manual=sin_sha)
        protocolo.procesar_linea("SM_PREP," + OPERACION)
        protocolo.procesar_linea("PING")
        self.assertEqual(self.puerto.lineas, ["PONG"])
        self.assertEqual(self.servo.aperturas, 0)

    def test_error_hash_no_abre_ni_emite_resultado(self):
        boot, ticket = self.preparar()
        with patch("salida_manual.sha256", side_effect=MemoryError):
            self.ejecutar(boot, ticket)
        self.assertEqual(self.servo.aperturas, 0)
        self.assertFalse(any(linea.startswith("SM_RES,") for linea in self.puerto.lineas))

    def test_sondeo_firma_reto_sin_reservar_ni_mover_servo(self):
        desafio = "A" * 22
        self.protocolo.procesar_linea("SM_PROBE," + desafio)
        linea = self.puerto.lineas[-1]
        tipo, recibido, boot, firma = linea.split(",")
        esperado = hmac.new(
            CLAVE, "smartparking.manual.v1|PROBE|{}|{}".format(boot, desafio).encode("ascii"),
            hashlib.sha256,
        ).digest()[:12]
        self.assertEqual(tipo, "SM_PROBE_OK")
        self.assertEqual(recibido, desafio)
        self.assertEqual(firma, base64.urlsafe_b64encode(esperado).decode("ascii"))
        self.assertEqual(self.servo.aperturas, 0)
        self.assertIsNone(self.manual.activa)
        self.assertEqual(self.manual.operaciones, {})
        self.assertLessEqual(len(linea), 96)

    def test_sondeo_no_responde_sin_clave_o_despues_de_error_pwm(self):
        with patch("salida_manual._leer_clave", return_value=None):
            sin_clave = GestorSalidaManual(
                self.puerto, self.servo, self.rfid3,
                lambda: self.ahora, lambda a, b: a - b, self.aleatorio,
            )
        sin_clave.sondear("A" * 22)
        self.manual.fallo_pwm = True
        self.manual.sondear("A" * 22)
        self.assertEqual(self.puerto.lineas, [])
        self.assertEqual(self.servo.aperturas, 0)

    def test_mac_falsificada_o_de_otro_proposito_no_abre(self):
        boot, ticket = self.preparar()
        self.protocolo.procesar_linea("SM_EXEC,{},{},{},{}".format(
            OPERACION, boot, ticket, "A" * 16
        ))
        self.protocolo.procesar_linea("SM_EXEC,{},{},{},{}".format(
            OPERACION, boot, ticket, firmar("RESULT", boot, ticket, "E")
        ))
        self.assertEqual(self.servo.aperturas, 0)
        self.ejecutar(boot, ticket)
        self.assertEqual(self.servo.aperturas, 1)


if __name__ == "__main__":
    unittest.main()
