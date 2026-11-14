"""Regresiones de cierre seguro para las decisiones RFID2 del bridge."""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock

from cliente_smartparking import ErrorApi
from entrada_rfid2 import procesar_trama_entrada_rfid2


LECTURA = "550e8400-e29b-41d4-a716-446655440123"
UID_PRUEBA = "04A1B2C3"


class EntradaRfid2Test(unittest.TestCase):
    def test_errores_http_deniegan_y_no_exponen_detalles_privados(self):
        for estado in (200, 400, 401, 403, 500, 503):
            with self.subTest(estado=estado):
                cliente = Mock()
                cliente.registrar_entrada_rfid2.side_effect = ErrorApi(
                    "detalle-privado-sintetico", estado_http=estado
                )
                puerto = Mock()
                salida = io.StringIO()

                with redirect_stdout(salida):
                    procesar_trama_entrada_rfid2(
                        "RFID2,{},{}".format(LECTURA, UID_PRUEBA), cliente, puerto
                    )

                cliente.registrar_entrada_rfid2.assert_called_once_with(
                    UID_PRUEBA, LECTURA
                )
                puerto.escribir_linea.assert_called_once_with(
                    "RFID2_RESULT,{},DENEGADA".format(LECTURA)
                )
                self.assertIn("HTTP {} sin decisión confirmada".format(estado), salida.getvalue())
                self.assertNotIn(UID_PRUEBA, salida.getvalue())
                self.assertNotIn("detalle-privado-sintetico", salida.getvalue())

    def test_timeout_conserva_denegacion_y_registro_sin_detalles(self):
        cliente = Mock()
        cliente.registrar_entrada_rfid2.side_effect = ErrorApi(
            "timeout privado", origen="COMUNICACION"
        )
        puerto = Mock()
        salida = io.StringIO()

        with redirect_stdout(salida):
            procesar_trama_entrada_rfid2(
                "RFID2,{},{}".format(LECTURA, UID_PRUEBA), cliente, puerto
            )

        puerto.escribir_linea.assert_called_once_with(
            "RFID2_RESULT,{},DENEGADA".format(LECTURA)
        )
        self.assertIn("sin respuesta API (timeout/comunicación)", salida.getvalue())
        self.assertNotIn(UID_PRUEBA, salida.getvalue())
        self.assertNotIn("timeout privado", salida.getvalue())

    def test_error_http_sin_codigo_conserva_cierre_seguro(self):
        cliente = Mock()
        cliente.registrar_entrada_rfid2.side_effect = ErrorApi(
            "sin codigo", origen="HTTP"
        )
        puerto = Mock()
        with redirect_stdout(io.StringIO()):
            procesar_trama_entrada_rfid2(
                "RFID2,{},{}".format(LECTURA, UID_PRUEBA), cliente, puerto
            )
        puerto.escribir_linea.assert_called_once_with(
            "RFID2_RESULT,{},DENEGADA".format(LECTURA)
        )


if __name__ == "__main__":
    unittest.main()
