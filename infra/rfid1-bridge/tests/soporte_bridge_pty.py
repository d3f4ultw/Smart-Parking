"""Aceptación serial simulada de handshake, RFID y correlación de resultados."""

import contextlib
import io
import os
import pty
import select
import threading
import time
import unittest
from unittest.mock import patch

import bridge
from bridge import SesionBridge, analizar_trama_rfid
from cliente_smartparking import ErrorApi
from puerto_serie import ErrorProtocolo, PuertoSerie


UID_PRUEBA = "04A1B2C3"
UID_ALTERNATIVO = "04112233"
CAPTURA_ID = "0123456789abcdef0123456789abcdef"


class ClienteFalso:
    def __init__(self):
        self.lecturas = []
        self.lecturas_capturadas = []
        self.resultados_capturados = []
        self.estados_dispositivo = []
        self.entradas_rfid2 = []
        self.resultado_rfid2 = "AUTORIZADA"
        self.activa = None

    def consultar_captura_activa(self):
        return self.activa

    def informar_escaneando(self, captura_id):
        if self.activa is not None:
            self.activa["estado"] = "ESCANEANDO"

    def enviar_lectura_capturada(self, captura_id, request_id, uid):
        self.lecturas_capturadas.append((captura_id, request_id, uid))
        if self.resultados_capturados:
            return self.resultados_capturados.pop(0)
        return {
            "capturaId": captura_id,
            "estado": "VISTA_PREVIA",
            "resultado": "PREVIEW_READY",
        }

    def enviar_lectura(self, secuencia, uid, clave_idempotencia):
        self.lecturas.append((secuencia, uid, clave_idempotencia))

    def registrar_entrada_rfid2(self, uid, lectura_id):
        self.entradas_rfid2.append((uid, lectura_id))
        return self.resultado_rfid2

    def informar_estado_dispositivo(self, conectado):
        self.estados_dispositivo.append(conectado)


class ClienteConTimeout:
    def __init__(self):
        self.lecturas = []
        self.estados_dispositivo = []

    def enviar_lectura(self, secuencia, uid, clave_idempotencia):
        self.lecturas.append((secuencia, uid, clave_idempotencia))
        if len(self.lecturas) == 1:
            raise ErrorApi("timeout simulado")

    def consultar_captura_activa(self):
        return None

    def informar_escaneando(self, captura_id):
        pass

    def enviar_lectura_capturada(self, captura_id, request_id, uid):
        pass

    def informar_estado_dispositivo(self, conectado):
        self.estados_dispositivo.append(conectado)


class SoporteBridgePty(unittest.TestCase):
    def setUp(self):
        self.maestro, esclavo = pty.openpty()
        self.buffer_maestro = bytearray()
        ruta = os.ttyname(esclavo)
        os.close(esclavo)
        self.puerto = PuertoSerie(ruta)
        self.cliente = ClienteFalso()
        self.sesion = SesionBridge(
            self.cliente,
            intervalo_ping=0.05,
            tiempo_espera_pong=0.8,
            intervalo_lectura=0.01,
        )
        self.detener = threading.Event()
        self.error = []
        self.salida = io.StringIO()
        self.hilo = threading.Thread(target=self._ejecutar, daemon=True)
        self.hilo.start()

    def _ejecutar(self):
        try:
            with contextlib.redirect_stdout(self.salida):
                self.sesion.ejecutar(self.puerto, self.detener)
        except Exception as error:
            self.error.append(error)

    def tearDown(self):
        self.detener.set()
        self.hilo.join(timeout=2)
        self.sesion.estado_dispositivo.cerrar()
        self.puerto.cerrar()
        os.close(self.maestro)

    def _leer_linea(self, tiempo_espera=1):
        limite = time.monotonic() + tiempo_espera
        while time.monotonic() < limite:
            separador = self.buffer_maestro.find(b"\n")
            if separador >= 0:
                linea = bytes(self.buffer_maestro[:separador])
                del self.buffer_maestro[:separador + 1]
                return linea.decode("ascii").removesuffix("\r")
            listos, _, _ = select.select([self.maestro], [], [], 0.05)
            if not listos:
                continue
            self.buffer_maestro.extend(os.read(self.maestro, 1024))
        self.fail("No llegó una trama serial a tiempo.")

    def _recibir_hasta(self, prefijo):
        limite = time.monotonic() + 1
        while time.monotonic() < limite:
            linea = self._leer_linea(max(0.05, limite - time.monotonic()))
            if linea == "PING":
                os.write(self.maestro, b"PONG\n")
            elif linea.startswith(prefijo):
                return linea
        self.fail("No llegó la trama serial esperada.")

