"""Pruebas sintéticas del heartbeat de capacidad y su caducidad."""

import base64
import hashlib
import hmac
import threading
import time
import unittest

from capacidad_manual import CapacidadManual
from cliente_smartparking import ErrorApi


CLAVE = bytes(range(32))
BOOT = "A" * 22


def token(valor):
    return base64.urlsafe_b64encode(valor.to_bytes(16, "big")).rstrip(b"=").decode("ascii")


def firma(clave, boot, desafio):
    texto = "smartparking.manual.v1|PROBE|{}|{}".format(boot, desafio)
    mac = hmac.new(clave, texto.encode("ascii"), hashlib.sha256).digest()[:12]
    return base64.urlsafe_b64encode(mac).decode("ascii")


class Puerto:
    def __init__(self):
        self.lineas = []

    def escribir_linea(self, linea):
        self.lineas.append(linea)


class Api:
    def __init__(self):
        self.contador = 0
        self.desafio = None
        self.disponible = False
        self.invalidaciones = 0
        self.confirmaciones = 0
        self.inicio = threading.Event()
        self.bloqueo = None

    def solicitar_desafio_salida_manual(self):
        self.contador += 1
        self.desafio = token(self.contador)
        return self.desafio

    def confirmar_capacidad_salida_manual(self, desafio, boot, mac):
        self.inicio.set()
        if self.bloqueo is not None:
            self.bloqueo.wait(2)
        if desafio != self.desafio or not hmac.compare_digest(mac, firma(CLAVE, boot, desafio)):
            self.disponible = False
            raise ErrorApi("Prueba no válida", estado_http=409)
        self.desafio = None
        self.confirmaciones += 1
        self.disponible = True

    def invalidar_capacidad_salida_manual(self):
        self.invalidaciones += 1
        self.disponible = False


class PruebasCapacidadManual(unittest.TestCase):
    def setUp(self):
        self.ahora = 0.0
        self.puerto = Puerto()
        self.api = Api()
        self.gestor = CapacidadManual(self.api, lambda: self.ahora)
        self.gestor.conectar()
        self.addCleanup(self.gestor.cerrar)

    def esperar(self, condicion, pasos=600):
        for _ in range(pasos):
            self.gestor.atender(self.puerto)
            if condicion():
                return
            self.ahora += 0.01
            time.sleep(0.001)
        self.fail("No terminó el paso de capacidad en el tiempo esperado.")

    def esperar_desafio(self):
        self.esperar(lambda: bool(self.puerto.lineas))
        return self.puerto.lineas[-1].split(",")[1]

    def responder(self, desafio, clave=CLAVE):
        self.gestor.recibir("SM_PROBE_OK,{},{},{}".format(
            desafio, BOOT, firma(clave, BOOT, desafio)
        ))

    def test_reto_valido_renueva_y_no_envia_un_comando_de_ejecucion(self):
        desafio = self.esperar_desafio()
        self.responder(desafio)
        self.esperar(lambda: self.gestor.disponible())
        self.assertTrue(self.api.disponible)
        self.assertEqual(self.api.confirmaciones, 1)
        self.assertTrue(all(linea.startswith("SM_PROBE,") for linea in self.puerto.lineas))
        self.ahora += 3.1
        self.esperar(lambda: len(self.puerto.lineas) == 2)
        self.assertNotEqual(self.puerto.lineas[0], self.puerto.lineas[1])

    def test_clave_distinta_no_confirma_capacidad(self):
        desafio = self.esperar_desafio()
        self.responder(desafio, bytes(reversed(range(32))))
        self.esperar(lambda: self.api.invalidaciones >= 2)
        self.assertFalse(self.gestor.disponible())
        self.assertFalse(self.api.disponible)
        self.assertEqual(self.api.confirmaciones, 0)

    def test_firmware_viejo_timeout_invalida_y_rechaza_acuse_tardio(self):
        desafio = self.esperar_desafio()
        self.ahora += 2.1
        self.gestor.atender(self.puerto)
        self.responder(desafio)
        self.esperar(lambda: self.api.invalidaciones >= 2)
        self.assertFalse(self.gestor.disponible())
        self.assertEqual(self.api.confirmaciones, 0)

    def test_conexion_perdida_invalida_aunque_la_verificacion_termine_tarde(self):
        self.api.bloqueo = threading.Event()
        desafio = self.esperar_desafio()
        self.responder(desafio)
        self.esperar(lambda: self.api.inicio.is_set())
        self.gestor.desconectar()
        self.api.bloqueo.set()
        for _ in range(500):
            if self.api.invalidaciones >= 2:
                break
            time.sleep(0.001)
        self.assertGreaterEqual(self.api.invalidaciones, 2)
        self.assertFalse(self.api.disponible)
        self.assertFalse(self.gestor.disponible())

    def test_capacidad_local_caduca_si_no_llega_otra_prueba(self):
        desafio = self.esperar_desafio()
        self.responder(desafio)
        self.esperar(lambda: self.gestor.disponible())
        self.ahora += 6.1
        self.assertFalse(self.gestor.disponible())


if __name__ == "__main__":
    unittest.main()
