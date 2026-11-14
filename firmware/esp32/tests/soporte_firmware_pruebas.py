"""Pruebas de host para contratos RFID1 sin acceso al ESP32."""

import pathlib
import sys
import types
import unittest
import zipfile


RAIZ_FIRMWARE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ_FIRMWARE))

import time

if not hasattr(time, "sleep_ms"):
    time.sleep_ms = lambda milisegundos: None
if not hasattr(time, "ticks_diff"):
    time.ticks_diff = lambda nuevo, anterior: ((nuevo - anterior + 2**29) % 2**30) - 2**29
if not hasattr(time, "ticks_ms"):
    time.ticks_ms = lambda: 1234

from captura import GestorCaptura
from comunicacion.protocolo import Protocolo
from comunicacion.serial import PuertoSerial
from entrada_rfid2 import GestorEntradaRfid2
from rfid.lector import DetectorLecturaRfid
from rfid.rc522 import LectorRC522


def cargar_firmware_recuperado():
    """Carga la implementación monolítica conservada, sin extraer archivos."""
    archivo_zip = RAIZ_FIRMWARE / "source-original" / "snapshot-20261029-061132.zip"
    with zipfile.ZipFile(archivo_zip) as respaldo:
        codigo = respaldo.read("esp32_test.py")
    modulo = types.ModuleType("firmware_original_recuperado")
    exec(compile(codigo, "esp32_test.py (snapshot recuperado)", "exec"), modulo.__dict__)
    return modulo


FIRMWARE_ORIGINAL = cargar_firmware_recuperado()


class UARTFalso:
    """UART de prueba con entrada fragmentable y salida recolectada."""

    def __init__(self, entradas=()):
        self.entradas = list(entradas)
        self.escritos = []
        self.cerrado = False

    def read(self):
        return self.entradas.pop(0) if self.entradas else None

    def write(self, texto):
        self.escritos.append(texto)
        return len(texto)

    def deinit(self):
        self.cerrado = True


class RelojFalso:
    def __init__(self, ahora=0):
        self.ahora = ahora

    def ticks_ms(self):
        return self.ahora

    def avanzar(self, milisegundos):
        self.ahora = (self.ahora + milisegundos) % 2**30


class PinFalso:
    OUT = 1

    def __init__(self, numero, modo=None, value=None):
        self.numero = numero
        self.valor = value

    def value(self, nuevo=None):
        if nuevo is not None:
            self.valor = nuevo
        return self.valor


class SPIFalso:
    MSB = 0
    instancia = None

    def __init__(self, *args, **kwargs):
        self.registros = {0x37: 0x92, 0x14: 0x00}
        self.registro_actual = 0
        self.espera_sin_respuesta = False
        SPIFalso.instancia = self

    def write(self, datos):
        registro = (datos[0] >> 1) & 0x3F
        self.registros[registro] = datos[1]
        self.registro_actual = registro

    def write_readinto(self, tx, rx):
        registro = ((tx[0] & 0x7E) >> 1) & 0x3F
        if registro == 0x04 and self.espera_sin_respuesta:
            rx[1] = 0
        else:
            rx[1] = self.registros.get(registro, 0)


class MachineFalsa:
    Pin = PinFalso
    SPI = SPIFalso


