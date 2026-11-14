"""Aceptación del heartbeat RFID con puerto serial simulado."""

import contextlib
import io
import threading
import time
import unittest

from bridge import SesionBridge


class ClienteDispositivoSimulado:
    def __init__(self, bloquear=False):
        self.estados = []
        self.intentos = []
        self.bloquear = bloquear
        self.iniciado = threading.Event()
        self.liberar = threading.Event()

    def consultar_captura_activa(self):
        return None

    def informar_estado_dispositivo(self, conectado):
        self.intentos.append(conectado)
        self.iniciado.set()
        if self.bloquear and conectado:
            self.liberar.wait(timeout=1)
            raise RuntimeError("Authorization: Bearer token-simulado UID=04A1B2C3")
        self.estados.append(conectado)


class HeartbeatBridgeTest(unittest.TestCase):
    def test_pong_vigente_publica_true_y_timeout_publica_false(self):
        cliente = ClienteDispositivoSimulado()

        class PuertoSinPong:
            def __init__(self):
                self.envio_pong = False

            def escribir_linea(self, _linea):
                pass

            def leer_linea(self, tiempo_espera):
                if not self.envio_pong:
                    self.envio_pong = True
                    return "PONG"
                time.sleep(min(tiempo_espera, 0.005))
                return None

        sesion = SesionBridge(
            cliente,
            intervalo_ping=0.01,
            tiempo_espera_pong=0.05,
            intervalo_lectura=0.005,
        )
        salida = io.StringIO()
        try:
            with contextlib.redirect_stdout(salida):
                with self.assertRaises(TimeoutError):
                    sesion.ejecutar(PuertoSinPong())
        finally:
            with contextlib.redirect_stdout(salida):
                sesion.estado_dispositivo.cerrar()

        self.assertIn(True, cliente.estados)
        self.assertFalse(cliente.estados[-1])
        self.assertNotIn("04A1B2C3", salida.getvalue())
        self.assertNotIn("token-simulado", salida.getvalue())

    def test_fallo_heartbeat_no_bloquea_el_ciclo_serial(self):
        cliente = ClienteDispositivoSimulado(bloquear=True)

        class PuertoSimulado:
            def __init__(self):
                self.lecturas = 0

            def escribir_linea(self, _linea):
                pass

            def leer_linea(self, _tiempo_espera):
                if self.lecturas == 0:
                    cliente.iniciado.wait(timeout=1)
                self.lecturas += 1
                time.sleep(0.005)
                return None

        sesion = SesionBridge(cliente, tiempo_espera_pong=0.05, intervalo_lectura=0.005)
        sesion.ultimo_pong = time.monotonic()
        puerto = PuertoSimulado()
        salida = io.StringIO()
        try:
            with contextlib.redirect_stdout(salida):
                with self.assertRaises(TimeoutError):
                    sesion.ejecutar(puerto)
                self.assertTrue(cliente.iniciado.is_set())
                self.assertFalse(cliente.liberar.is_set())
                self.assertGreaterEqual(puerto.lecturas, 6)
        finally:
            cliente.liberar.set()
            with contextlib.redirect_stdout(salida):
                sesion.estado_dispositivo.cerrar()

        self.assertIn(True, cliente.intentos)
        self.assertFalse(cliente.estados[-1])
        self.assertNotIn("token-simulado", salida.getvalue())
        self.assertNotIn("04A1B2C3", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
