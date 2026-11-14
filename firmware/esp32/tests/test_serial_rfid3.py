"""Verifica framing y escritura UART parcial sin acceder a hardware."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from captura import GestorCaptura
from comunicacion.protocolo import Protocolo
from comunicacion.serial import MAXIMO_TRAMAS_PENDIENTES, PuertoSerial
from salida_rfid3 import GestorSalidaRfid3


class UARTFragmentada:
    def __init__(self, escrituras=(), lecturas=()):
        self.escrituras = list(escrituras)
        self.lecturas = list(lecturas)
        self.salida = ""

    def read(self):
        return self.lecturas.pop(0) if self.lecturas else None

    def write(self, texto):
        accion = self.escrituras.pop(0) if self.escrituras else len(texto)
        if accion == "incierta":
            self.salida += texto[:5]
            return None
        if accion is None:
            return None
        cantidad = min(accion, len(texto))
        self.salida += texto[:cantidad]
        return cantidad

    def deinit(self):
        pass


class PruebasSerialRfid3(unittest.TestCase):
    def test_escritura_parcial_no_entrelaza_evento_y_pong(self):
        uart = UARTFragmentada((7, 2, 4, 1))
        puerto = PuertoSerial(uart)
        evento = "RFID3,00000000-0000-4000-8000-000000000001,01020304"
        puerto.enviar_linea(evento)
        puerto.enviar_linea("PONG")
        for _ in range(10):
            puerto.atender_salida()
        self.assertEqual(uart.salida, evento + "\nPONG\n")

    def test_none_incierto_invalida_prefijo_y_recupera_pong(self):
        uart = UARTFragmentada(("incierta", 1, 1))
        puerto = PuertoSerial(uart)
        puerto.enviar_linea("RFID3,00000000-0000-4000-8000-000000000001,01020304")
        puerto.enviar_linea("PONG")
        for _ in range(10):
            puerto.atender_salida()
        self.assertEqual(uart.salida, "RFID3!\nPONG\n")
        self.assertFalse(any(linea.startswith("RFID3,") for linea in uart.salida.splitlines()))

    def test_cancelacion_de_uid_parcial_no_puede_formar_uid_valida(self):
        # El prefijo puede coincidir con una UID más corta: se invalida antes del LF.
        evento = "RFID3,00000000-0000-4000-8000-000000000001,01020304050607"
        uart = UARTFragmentada((len(evento) - 6,))
        puerto = PuertoSerial(uart)
        puerto.enviar_linea(evento)
        puerto.cancelar_linea(evento)
        puerto.enviar_linea("PONG")
        for _ in range(5):
            puerto.atender_salida()
        self.assertTrue(uart.salida.splitlines()[0].endswith("!"))
        self.assertTrue(uart.salida.endswith("\nPONG\n"))

    def test_saturacion_y_sin_progreso_son_acotados(self):
        uart = UARTFragmentada([0] * 100)
        puerto = PuertoSerial(uart)
        for numero in range(MAXIMO_TRAMAS_PENDIENTES + 10):
            puerto.enviar_linea("X{}".format(numero))
        self.assertLessEqual(len(puerto._salida), MAXIMO_TRAMAS_PENDIENTES)
        self.assertEqual(uart.salida, "")
        uart.escrituras = []
        for _ in range(30):
            puerto.atender_salida()
        self.assertEqual(puerto._salida, [])

    def test_lectura_fragmentada_descarta_trama_larga_y_atiende_ping(self):
        uart = UARTFragmentada(lecturas=(b"X" * 97 + b"PING\nPI", b"NG\r\n"))
        puerto = PuertoSerial(uart)
        captura = GestorCaptura(puerto, lambda: 0)
        protocolo = Protocolo(puerto, captura, lambda: 0)
        protocolo.atender()
        self.assertEqual(uart.salida, "")
        protocolo.atender()
        self.assertEqual(uart.salida, "PONG\n")

    def test_retorno_de_carro_interior_no_transforma_trama_en_valida(self):
        uart = UARTFragmentada(lecturas=(b"PI\rNG\n PING \nPING\r\n",))
        puerto = PuertoSerial(uart)
        captura = GestorCaptura(puerto, lambda: 0)
        protocolo = Protocolo(puerto, captura, lambda: 0)
        protocolo.atender()
        self.assertEqual(uart.salida, "PONG\n")

    def test_respuesta_fragmentada_correlacionada_y_tardia(self):
        ahora = [0]
        uart = UARTFragmentada()
        puerto = PuertoSerial(uart)
        salida = GestorSalidaRfid3(puerto, lambda: ahora[0], lambda a, b: a - b,
                                  lambda n: bytes(range(n)))
        captura = GestorCaptura(puerto, lambda: ahora[0])
        protocolo = Protocolo(puerto, captura, lambda: ahora[0], None, salida)
        uid = bytes((1, 2, 3, 4))
        salida.procesar_tarjeta(uid, True, 0, 80)
        salida.procesar_tarjeta(uid, True, 80, 80)
        lectura = salida.pendiente["lectura_id"]
        respuesta = "RFID3_RESULT,{},AUTORIZADA\r\n".format(lectura).encode()
        uart.lecturas = [respuesta[:10], respuesta[10:]]
        ahora[0] = 4580
        protocolo.atender()
        protocolo.atender()
        self.assertIsNone(salida.pendiente)
        self.assertEqual(salida.ultimo_resultado, "DENEGADA")


if __name__ == "__main__":
    unittest.main()
