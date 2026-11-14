"""Pruebas acotadas del heartbeat RFID sin hardware físico."""

import contextlib
import io
import threading
import time
import unittest
from unittest.mock import patch

from estado_dispositivo import EstadoDispositivo


class ClienteHeartbeatSimulado:
    def __init__(self, fallos_iniciales=0):
        self.condicion = threading.Condition()
        self.llamadas = []
        self.fallos_restantes = fallos_iniciales

    def informar_estado_dispositivo(self, conectado):
        with self.condicion:
            self.llamadas.append((time.monotonic(), conectado))
            falla = self.fallos_restantes > 0
            if falla:
                self.fallos_restantes -= 1
            self.condicion.notify_all()
        if falla:
            raise OSError("Authorization: Bearer token-simulado UID=04A1B2C3")

    def esperar_llamadas(self, cantidad, tiempo_espera=1):
        limite = time.monotonic() + tiempo_espera
        with self.condicion:
            while len(self.llamadas) < cantidad:
                restante = limite - time.monotonic()
                if restante <= 0:
                    return False
                self.condicion.wait(restante)
            return True


class EstadoDispositivoTest(unittest.TestCase):
    def test_renueva_cada_intervalo_y_publica_el_cambio_a_false(self):
        cliente = ClienteHeartbeatSimulado()
        with patch("estado_dispositivo.INTERVALO_RENOVACION_ESTADO", 0.04):
            estado = EstadoDispositivo(cliente)
            try:
                estado.actualizar(True)
                self.assertTrue(cliente.esperar_llamadas(2))
                estado.actualizar(False)
                self.assertTrue(cliente.esperar_llamadas(3))
            finally:
                estado.cerrar()

        llamadas = cliente.llamadas
        self.assertEqual([valor for _, valor in llamadas[:3]], [True, True, False])
        self.assertGreaterEqual(llamadas[1][0] - llamadas[0][0], 0.03)
        self.assertLess(llamadas[1][0] - llamadas[0][0], 0.5)

    def test_api_temporalmente_no_disponible_se_reintenta_sin_filtrar_datos(self):
        cliente = ClienteHeartbeatSimulado(fallos_iniciales=1)
        salida = io.StringIO()
        with patch("estado_dispositivo.INTERVALO_RENOVACION_ESTADO", 0.04):
            estado = EstadoDispositivo(cliente)
            try:
                with contextlib.redirect_stdout(salida):
                    estado.actualizar(True)
                    self.assertTrue(cliente.esperar_llamadas(2))
            finally:
                with contextlib.redirect_stdout(salida):
                    estado.cerrar()

        self.assertEqual(
            [valor for _, valor in cliente.llamadas], [True, True, False]
        )
        self.assertIn("No se pudo renovar", salida.getvalue())
        self.assertNotIn("token-simulado", salida.getvalue())
        self.assertNotIn("04A1B2C3", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
