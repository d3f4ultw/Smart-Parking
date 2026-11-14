"""PTY: RFID 1/2 lentos no detienen PING ni la decisión correlacionada RFID 3."""

import contextlib
import io
import os
import pty
import select
import threading
import time
import unittest
import uuid

from bridge import SesionBridge
from puerto_serie import PuertoSerie


CAPTURA = "0123456789abcdef0123456789abcdef"
UID = "04A1B2C3"


class ClienteLento:
    def __init__(self, captura=False):
        self.estado = "PENDIENTE" if captura else None
        self.inicio_entrada = threading.Event()
        self.liberar_entrada = threading.Event()
        self.inicio_escaneo = threading.Event()
        self.liberar_escaneo = threading.Event()
        self.inicio_lectura = threading.Event()
        self.liberar_lectura = threading.Event()
        self.salidas = []

    def consultar_captura_activa(self):
        return None if self.estado is None else {"capturaId": CAPTURA, "estado": self.estado}

    def informar_estado_dispositivo(self, conectado):
        pass

    def informar_escaneando(self, captura):
        self.inicio_escaneo.set()
        self.liberar_escaneo.wait(3)
        self.estado = "ESCANEANDO"

    def enviar_lectura_capturada(self, captura, request_id, uid):
        self.inicio_lectura.set()
        self.liberar_lectura.wait(3)
        self.estado = "VISTA_PREVIA"
        return {"capturaId": captura, "estado": "VISTA_PREVIA", "resultado": "PREVIEW_READY"}

    def registrar_entrada_rfid2(self, uid, lectura_id):
        self.inicio_entrada.set()
        self.liberar_entrada.wait(3)
        return "AUTORIZADA"

    def registrar_salida_rfid3(self, uid, lectura_id):
        self.salidas.append((uid, lectura_id))
        return "AUTORIZADA"


class PuertoObservado:
    def __init__(self, puerto):
        self.puerto = puerto
        self.hilos = set()

    def escribir_linea(self, linea):
        self.hilos.add(threading.get_ident())
        self.puerto.escribir_linea(linea)

    def leer_linea(self, espera):
        self.hilos.add(threading.get_ident())
        return self.puerto.leer_linea(espera)


class BucleSerialLentoTest(unittest.TestCase):
    def iniciar(self, cliente):
        self.cliente = cliente
        self.maestro, esclavo = pty.openpty()
        ruta = os.ttyname(esclavo)
        os.close(esclavo)
        self.puerto = PuertoSerie(ruta)
        self.observado = PuertoObservado(self.puerto)
        self.sesion = SesionBridge(cliente, intervalo_ping=0.05,
                                   tiempo_espera_pong=0.3, intervalo_lectura=0.01)
        self.detener = threading.Event()
        self.errores = []
        self.buffer = bytearray()
        self.lineas = []
        self.salida = io.StringIO()
        self.captura_salida = contextlib.redirect_stdout(self.salida)
        self.captura_salida.__enter__()

        def ejecutar():
            try:
                self.sesion.ejecutar(self.observado, self.detener)
            except Exception as error:
                self.errores.append(type(error).__name__)

        self.hilo = threading.Thread(target=ejecutar, daemon=True)
        self.hilo.start()

    def tearDown(self):
        if not hasattr(self, "hilo"):
            return
        self.cliente.liberar_entrada.set()
        self.cliente.liberar_escaneo.set()
        self.cliente.liberar_lectura.set()
        self.detener.set()
        self.hilo.join(timeout=4)
        self.sesion.estado_dispositivo.cerrar()
        self.puerto.cerrar()
        os.close(self.maestro)
        self.captura_salida.__exit__(None, None, None)

    def esperar(self, condicion, plazo=2):
        limite = time.monotonic() + plazo
        while time.monotonic() < limite:
            if select.select([self.maestro], [], [], 0.02)[0]:
                self.buffer.extend(os.read(self.maestro, 4096))
            while b"\n" in self.buffer:
                linea, _, resto = self.buffer.partition(b"\n")
                self.buffer = bytearray(resto)
                linea = linea.rstrip(b"\r").decode("ascii")
                self.lineas.append(linea)
                if linea == "PING":
                    os.write(self.maestro, b"PONG\n")
            if condicion():
                return
        self.fail("El evento serial esperado no llegó durante la API lenta")

    def salida_en_vuelo(self):
        lectura_id = str(uuid.uuid4())
        os.write(self.maestro, "RFID3,{},{}\n".format(lectura_id, UID).encode("ascii"))
        esperada = "RFID3_RESULT,{},AUTORIZADA".format(lectura_id)
        self.esperar(lambda: esperada in self.lineas, plazo=1)
        self.assertEqual(self.cliente.salidas[-1], (UID, lectura_id))
        self.assertFalse(self.errores)

    def test_rfid2_lento_no_detiene_ping_ni_rfid3(self):
        cliente = ClienteLento()
        self.iniciar(cliente)
        lectura = str(uuid.uuid4())
        os.write(self.maestro, "RFID2,{},{}\n".format(lectura, UID).encode("ascii"))
        self.esperar(cliente.inicio_entrada.is_set)
        self.salida_en_vuelo()
        self.esperar(lambda: self.lineas.count("PING") >= 5)
        cliente.liberar_entrada.set()
        esperada = "RFID2_RESULT,{},AUTORIZADA".format(lectura)
        self.esperar(lambda: esperada in self.lineas)
        self.assertEqual(len(self.observado.hilos), 1)
        self.assertNotIn(UID, self.salida.getvalue())

    def test_armado_y_captura_lentos_no_detienen_ping_ni_rfid3(self):
        cliente = ClienteLento(captura=True)
        self.iniciar(cliente)
        self.esperar(cliente.inicio_escaneo.is_set)
        self.salida_en_vuelo()
        self.esperar(lambda: self.lineas.count("PING") >= 5)
        cliente.liberar_escaneo.set()
        self.esperar(lambda: "ENROLL_ARM," + CAPTURA in self.lineas)
        os.write(self.maestro, "ENROLL_READ,{},{},{}\n".format(CAPTURA, "0001", UID).encode("ascii"))
        self.esperar(cliente.inicio_lectura.is_set)
        self.salida_en_vuelo()
        cliente.liberar_lectura.set()
        self.esperar(lambda: "ENROLL_CANCEL," + CAPTURA in self.lineas)
        self.assertEqual(len(self.observado.hilos), 1)
        self.assertNotIn(UID, self.salida.getvalue())


if __name__ == "__main__":
    unittest.main()
