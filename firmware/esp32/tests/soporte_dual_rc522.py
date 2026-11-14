"""Aceptación aislada del bus SPI compartido y los lectores RFID1/RFID2."""

import sys
import time
import types
import unittest

RAIZ_FIRMWARE = __import__("pathlib").Path(__file__).resolve().parents[1]
RAIZ_PRUEBAS = __import__("pathlib").Path(__file__).resolve().parent
if str(RAIZ_FIRMWARE) not in sys.path:
    sys.path.insert(0, str(RAIZ_FIRMWARE))
if str(RAIZ_PRUEBAS) not in sys.path:
    sys.path.insert(0, str(RAIZ_PRUEBAS))

from rfid.bus_spi import BusSPICompartido
from rfid.lector import DetectorLecturaRfid, LectorRFID
from captura import GestorCaptura
from comunicacion.protocolo import Protocolo
from comunicacion.serial import PuertoSerial
from simulador_picc import MachinePICC, PinPICC, SPIPICC


class PinZumbadorFalso:
    """Pin de host dedicado al buzzer de la aplicación."""

    OUT = 1

    def __init__(self, numero, modo=None, value=None):
        self.numero = numero
        self.modo = modo
        self.nivel = value

    def value(self, nuevo=None):
        if nuevo is not None:
            self.nivel = nuevo
        return self.nivel


class PWMZumbadorFalso:
    """PWM de host que no accede al GPIO físico."""

    def __init__(self, pin, freq, duty_u16):
        self.pin = pin
        self.frecuencia = freq
        self.ciclo = duty_u16

    def duty_u16(self, ciclo):
        self.ciclo = ciclo

    def deinit(self):
        pass


def _importar_aplicacion_con_machine_falso():
    modulo_machine = types.ModuleType("machine")
    modulo_machine.Pin = PinZumbadorFalso
    modulo_machine.PWM = PWMZumbadorFalso
    machine_original = sys.modules.get("machine")
    sys.modules["machine"] = modulo_machine
    funciones_reloj = {
        nombre: getattr(time, nombre, None)
        for nombre in ("ticks_add", "ticks_diff", "ticks_ms")
    }
    time.ticks_add = lambda valor, delta: valor + delta
    time.ticks_diff = lambda nuevo, anterior: nuevo - anterior
    time.ticks_ms = lambda: int(time.monotonic() * 1000)
    try:
        import aplicacion
    finally:
        for nombre, funcion in funciones_reloj.items():
            if funcion is None:
                delattr(time, nombre)
            else:
                setattr(time, nombre, funcion)
        if machine_original is None:
            del sys.modules["machine"]
        else:
            sys.modules["machine"] = machine_original
    return aplicacion


aplicacion = _importar_aplicacion_con_machine_falso()

if not hasattr(time, "sleep_ms"):
    time.sleep_ms = lambda milisegundos: None
if not hasattr(time, "ticks_diff"):
    time.ticks_diff = lambda nuevo, anterior: ((nuevo - anterior + 2**29) % 2**30) - 2**29


class UARTFalso:
    def __init__(self, entradas=()):
        self.entradas = list(entradas)
        self.escritos = []

    def read(self):
        return self.entradas.pop(0) if self.entradas else None

    def write(self, texto):
        self.escritos.append(texto)
        return len(texto)

    def deinit(self):
        pass


class RelojFalso:
    def __init__(self, ahora=0):
        self.ahora = ahora

    def ticks_ms(self):
        return self.ahora


class PinFalso:
    """GPIO de host que registra dirección y nivel lógico."""

    OUT = 1
    IN = 0
    instancias = []

    def __init__(self, numero, modo=None, value=None):
        self.numero = numero
        self.modo = modo
        self.nivel = value
        PinFalso.instancias.append(self)

    def value(self, nuevo=None):
        if nuevo is not None:
            self.nivel = nuevo
        return self.nivel


class SPIFalso:
    """SPI compartido que falla si ningún CS o más de un CS está activo."""

    MSB = 0
    instancias = []

    def __init__(self, *args, **kwargs):
        self.argumentos = kwargs
        self.operaciones = []
        SPIFalso.instancias.append(self)

    def _lector_seleccionado(self):
        activos = [pin for pin in PinFalso.instancias if pin.numero in (5, 26) and pin.value() == 0]
        if len(activos) != 1:
            raise AssertionError("Debe haber exactamente un CS activo por transacción.")
        return activos[0].numero

    def write(self, datos):
        cs = self._lector_seleccionado()
        self.operaciones.append(("write", cs, bytes(datos)))

    def write_readinto(self, tx, rx):
        cs = self._lector_seleccionado()
        registro = ((tx[0] & 0x7E) >> 1) & 0x3F
        self.operaciones.append(("read", cs, registro))
        rx[1] = 0x92 if registro == 0x37 else 0


class MachineFalsa:
    Pin = PinFalso
    SPI = SPIFalso


