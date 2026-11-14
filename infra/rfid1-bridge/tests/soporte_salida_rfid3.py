"""Contratos de salida RFID 3 con errores y transporte serial simulado."""

import contextlib
import io
import json
import os
import pty
import select
import socket
import threading
import time
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from bridge import SesionBridge
from cliente_capturas import ClienteCapturas
from cliente_smartparking import ErrorApi
from puerto_serie import PuertoSerie
from salida_rfid3 import GestorSalidaRfid3


UID = "04A1B2C3"
TOKEN = "token-sintetico-rfid3"


class PuertoFalso:
    def __init__(self):
        self.lineas = []

    def escribir_linea(self, linea):
        self.lineas.append(linea)


class ClienteControlado:
    def __init__(self, resultado="AUTORIZADA", espera=False):
        self.resultado = resultado
        self.solicitudes = []
        self.liberar = threading.Event()
        if not espera:
            self.liberar.set()

    def registrar_salida_rfid3(self, uid, lectura_id):
        self.solicitudes.append((uid, lectura_id))
        self.liberar.wait(2)
        if isinstance(self.resultado, Exception):
            raise self.resultado
        return self.resultado

    def consultar_captura_activa(self):
        return None

    def informar_estado_dispositivo(self, conectado):
        pass


def esperar_resultado(gestor, puerto):
    limite = time.monotonic() + 2
    while time.monotonic() < limite:
        gestor.atender(puerto)
        if gestor.en_curso is None:
            return
        time.sleep(0.005)
    raise AssertionError("El trabajo HTTP simulado no terminó")


