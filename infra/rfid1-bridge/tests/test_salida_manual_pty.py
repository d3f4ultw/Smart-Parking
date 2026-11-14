"""Bridge real sobre PTY y protocolo ESP32 simulado, sin dispositivo físico."""

import importlib.util
import base64
import hashlib
import hmac
import os
import pathlib
import pty
import select
import threading
import time
import unittest
import uuid

from bridge import SesionBridge
from puerto_serie import PuertoSerie
from salida_manual import _comprimir_uuid


RAIZ = pathlib.Path(__file__).resolve().parents[3]
RUTA_FIRMWARE = RAIZ / "firmware" / "esp32"
OPERACION = "01234567-89ab-cdef-0123-456789abcdef"
CLAVE = bytes(range(32))  # Únicamente API y ESP32 simulados reciben esta clave.


def firmar(accion, operacion, boot, ticket, codigo=None):
    texto = "smartparking.manual.v1|{}|{}|{}|{}".format(
        accion, _comprimir_uuid(operacion), boot, ticket
    )
    if codigo is not None:
        texto += "|" + codigo
    mac = hmac.new(CLAVE, texto.encode("ascii"), hashlib.sha256).digest()[:12]
    return base64.urlsafe_b64encode(mac).decode("ascii")


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


firmware_manual = cargar("firmware_manual_prueba", RUTA_FIRMWARE / "salida_manual.py")
firmware_protocolo = cargar("firmware_protocolo_prueba", RUTA_FIRMWARE / "comunicacion" / "protocolo.py")


class ApiFalsa:
    def __init__(self):
        self.estado = "PENDIENTE"
        self.boot = None
        self.ticket = None
        self.emisiones = 0
        self.resultados = []
        self.desafio = None
        self.capacidad = False

    def consultar_captura_activa(self):
        return None

    def informar_estado_dispositivo(self, _conectado):
        pass

    def solicitar_desafio_salida_manual(self):
        self.desafio = _comprimir_uuid(str(uuid.uuid4()))
        return self.desafio

    def confirmar_capacidad_salida_manual(self, desafio, boot, firma):
        texto = "smartparking.manual.v1|PROBE|{}|{}".format(boot, desafio)
        esperado = base64.urlsafe_b64encode(hmac.new(CLAVE, texto.encode("ascii"), hashlib.sha256).digest()[:12]).decode("ascii")
        if desafio != self.desafio or not hmac.compare_digest(firma, esperado):
            raise AssertionError("Desafío no válido.")
        self.desafio = None
        self.capacidad = True

    def invalidar_capacidad_salida_manual(self):
        self.capacidad = False

    def consultar_salida_manual(self, despues=None):
        if self.estado is None:
            return None
        respuesta = {"operacionId": OPERACION, "estado": self.estado}
        if self.estado == "EMITIDA":
            respuesta["bootId"] = self.boot
            respuesta["ticketId"] = self.ticket
        return respuesta

    def emitir_salida_manual(self, operacion, boot, ticket):
        if self.estado != "PENDIENTE":
            raise AssertionError("No se puede emitir dos veces.")
        self.estado = "EMITIDA"
        self.boot = boot
        self.ticket = ticket
        self.emisiones += 1
        return firmar("EXEC", operacion, boot, ticket)

    def informar_resultado_salida_manual(self, operacion, boot, ticket, resultado, firma):
        codigo = "E" if resultado == "EJECUTADA" else "N"
        if (operacion != OPERACION or boot != self.boot or ticket != self.ticket
                or self.estado != "EMITIDA"
                or not hmac.compare_digest(firma, firmar("RESULT", operacion, boot, ticket, codigo))):
            raise AssertionError("Resultado sin correlación.")
        self.resultados.append(resultado)
        self.estado = None
        return {"operacionId": OPERACION, "movimientoId": 1, "estado": "CONFIRMADA"}


class ServoSimulado:
    def __init__(self):
        self.abierto = False
        self.aperturas = 0
        self.inicio = None

    def abrir(self):
        self.aperturas += 1
        self.abierto = True
        self.inicio = time.monotonic()

    def actualizar(self):
        if self.abierto and time.monotonic() - self.inicio >= 0.05:
            self.abierto = False


class PuertoFirmware:
    def __init__(self, descriptor, perder_resultado):
        self.descriptor = descriptor
        self.perder_resultado = perder_resultado
        self.tramas = []

    def enviar_linea(self, linea):
        self.tramas.append(linea)
        if linea.startswith("SM_RES,") and self.perder_resultado:
            self.perder_resultado = False
            return True
        os.write(self.descriptor, (linea + "\n").encode("ascii"))
        return True


class SimuladorFirmware:
    def __init__(self, descriptor, perder_resultado):
        self.descriptor = descriptor
        self.puerto = PuertoFirmware(descriptor, perder_resultado)
        self.servo = ServoSimulado()
        self.salida_rfid3 = type("Rfid3", (), {"pendiente": None})()
        reloj = lambda: int(time.monotonic() * 1000)
        self.manual = firmware_manual.GestorSalidaManual(
            self.puerto, self.servo, self.salida_rfid3, reloj, lambda a, b: a - b,
            clave=CLAVE,
        )
        self.protocolo = firmware_protocolo.Protocolo(
            self.puerto, None, reloj, salida_manual=self.manual,
        )
        self.detener = threading.Event()
        self.comandos = []
        self.error = None
        self.hilo = threading.Thread(target=self.ejecutar, daemon=True)

    def ejecutar(self):
        buffer = bytearray()
        try:
            while not self.detener.is_set():
                self.servo.actualizar()
                self.manual.actualizar(int(time.monotonic() * 1000))
                listos, _, _ = select.select([self.descriptor], [], [], 0.01)
                if not listos:
                    continue
                buffer.extend(os.read(self.descriptor, 1024))
                while b"\n" in buffer:
                    linea, _, resto = buffer.partition(b"\n")
                    buffer = bytearray(resto)
                    texto = linea.rstrip(b"\r").decode("ascii")
                    self.comandos.append(texto)
                    self.protocolo.procesar_linea(texto)
                    if texto.startswith("SM_EXEC,"):
                        # Una entrega serial duplicada jamás reinicia el servo.
                        self.protocolo.procesar_linea(texto)
        except OSError:
            pass
        except Exception as error:
            self.error = error


class PruebasPtyManual(unittest.TestCase):
    def test_respuesta_perdida_se_consulta_sin_repetir_apertura(self):
        maestro, esclavo = pty.openpty()
        ruta = os.ttyname(esclavo)
        os.close(esclavo)
        puerto = PuertoSerie(ruta)
        api = ApiFalsa()
        sesion = SesionBridge(api, intervalo_ping=0.05, tiempo_espera_pong=0.8, intervalo_lectura=0.01)
        detener = threading.Event()
        errores = []

        def ejecutar_bridge():
            try:
                sesion.ejecutar(puerto, detener)
            except Exception as error:
                errores.append(error)

        simulador = SimuladorFirmware(maestro, perder_resultado=True)
        hilo_bridge = threading.Thread(target=ejecutar_bridge, daemon=True)
        simulador.hilo.start()
        hilo_bridge.start()
        try:
            limite = time.monotonic() + 8
            while not api.resultados and time.monotonic() < limite:
                time.sleep(0.01)
            self.assertEqual(api.resultados, ["EJECUTADA"])
            self.assertEqual(api.emisiones, 1)
            self.assertEqual(simulador.servo.aperturas, 1)
            self.assertFalse(simulador.servo.abierto)
            self.assertEqual(sum(x.startswith("SM_EXEC,") for x in simulador.comandos), 1)
            self.assertTrue(any(x.startswith("SM_GET,") for x in simulador.comandos))
            self.assertTrue(any(x.startswith("SM_PROBE,") for x in simulador.comandos))
            self.assertIn("PING", simulador.comandos)
            self.assertIsNone(simulador.error)
            self.assertEqual(errores, [])
        finally:
            detener.set()
            simulador.detener.set()
            hilo_bridge.join(timeout=2)
            simulador.hilo.join(timeout=2)
            sesion.estado_dispositivo.cerrar()
            sesion.capacidad_manual.cerrar()
            puerto.cerrar()
            os.close(maestro)


if __name__ == "__main__":
    unittest.main()
