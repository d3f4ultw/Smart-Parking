"""Pruebas de protocolo RFID sobre un pseudo-terminal aislado."""

import os
import time
import unittest

from soporte_bridge_pty import (
    SoporteBridgePty,
    ClienteConTimeout,
    ErrorApi,
    ErrorProtocolo,
    UID_PRUEBA,
    UID_ALTERNATIVO,
    CAPTURA_ID,
    analizar_trama_rfid,
)

class BridgePtyProtocolTest(SoporteBridgePty):
    def test_ping_fragmentado_y_lectura_reciben_solo_deny(self):
        self.assertEqual(self._leer_linea(), "PING")
        os.write(self.maestro, b"PO")
        time.sleep(0.01)
        os.write(self.maestro, b"NG\n")

        os.write(self.maestro, b"RFID,002A,04A1")
        time.sleep(0.01)
        os.write(self.maestro, b"B2C3\n")
        self.assertEqual(self._recibir_hasta("ACK,"), "ACK,002A")
        self.assertEqual(self._recibir_hasta("RESULT,"), "RESULT,002A,DENY")

        os.write(self.maestro, b"RESULT_ACK,002A,DEN")
        time.sleep(0.01)
        os.write(self.maestro, b"Y\n")
        limite = time.monotonic() + 0.5
        while "002A" in self.sesion.pendientes and time.monotonic() < limite:
            time.sleep(0.01)
        self.assertNotIn("002A", self.sesion.pendientes)
        self.assertEqual(len(self.cliente.lecturas), 1)
        self.assertEqual(self.cliente.lecturas[0][:2], (42, UID_PRUEBA))
        self.assertNotIn("ALLOW", self.salida.getvalue())
        self.assertNotIn(UID_PRUEBA, self.salida.getvalue())

    def test_rfid2_ptty_correlaciona_decision_y_no_registra_uid(self):
        lectura_id = "550e8400-e29b-41d4-a716-446655440000"
        os.write(
            self.maestro,
            ("RFID2,{},{}\r\n".format(lectura_id, UID_PRUEBA)).encode("ascii"),
        )
        self.assertEqual(
            self._recibir_hasta("RFID2_RESULT,"),
            "RFID2_RESULT,{},AUTORIZADA".format(lectura_id),
        )
        self.assertEqual(self.cliente.entradas_rfid2, [(UID_PRUEBA, lectura_id)])
        self.assertNotIn(UID_PRUEBA, self.salida.getvalue())

    def test_rfid2_error_api_responde_denegada(self):
        def error(uid, lectura_id):
            raise ErrorApi("fallo sintético")

        self.cliente.registrar_entrada_rfid2 = error
        lectura_id = "550e8400-e29b-41d4-a716-446655440001"
        os.write(
            self.maestro,
            ("RFID2,{},{}\n".format(lectura_id, UID_PRUEBA)).encode("ascii"),
        )
        self.assertEqual(
            self._recibir_hasta("RFID2_RESULT,"),
            "RFID2_RESULT,{},DENEGADA".format(lectura_id),
        )
        self.assertNotIn("fallo sintético", self.salida.getvalue())

    def test_rfid2_errores_repetidos_no_interrumpen_el_bridge(self):
        respuestas = iter((
            ErrorApi("fallo privado", estado_http=400),
            ErrorApi("fallo privado", estado_http=503),
            ErrorApi("timeout privado", origen="COMUNICACION"),
            ErrorApi("fallo privado", estado_http=503),
            "AUTORIZADA",
        ))
        llamadas = []

        def registrar(uid, lectura_id):
            llamadas.append((uid, lectura_id))
            respuesta = next(respuestas)
            if isinstance(respuesta, Exception):
                raise respuesta
            return respuesta

        self.cliente.registrar_entrada_rfid2 = registrar
        ids = [
            "550e8400-e29b-41d4-a716-{:012x}".format(numero)
            for numero in range(1, 6)
        ]
        for indice, lectura_id in enumerate(ids):
            os.write(
                self.maestro,
                ("RFID2,{},{}\n".format(lectura_id, UID_PRUEBA)).encode("ascii"),
            )
            decision = "AUTORIZADA" if indice == 4 else "DENEGADA"
            self.assertEqual(
                self._recibir_hasta("RFID2_RESULT,"),
                "RFID2_RESULT,{},{}".format(lectura_id, decision),
            )
            self.assertTrue(self.hilo.is_alive())
            self.assertEqual(self.error, [])

        self.assertEqual(llamadas, [(UID_PRUEBA, lectura_id) for lectura_id in ids])
        self.assertIn("HTTP 400 sin decisión confirmada", self.salida.getvalue())
        self.assertIn("HTTP 503 sin decisión confirmada", self.salida.getvalue())
        self.assertIn("sin respuesta API (timeout/comunicación)", self.salida.getvalue())
        self.assertNotIn(UID_PRUEBA, self.salida.getvalue())
        self.assertNotIn("fallo privado", self.salida.getvalue())
        self.assertNotIn("timeout privado", self.salida.getvalue())

    def test_rfid2_distingue_denegacion_confirmada_de_timeout(self):
        lectura_id = "550e8400-e29b-41d4-a716-446655440002"
        self.cliente.resultado_rfid2 = "DENEGADA"
        os.write(
            self.maestro,
            ("RFID2,{},{}\n".format(lectura_id, UID_PRUEBA)).encode("ascii"),
        )
        self.assertEqual(
            self._recibir_hasta("RFID2_RESULT,"),
            "RFID2_RESULT,{},DENEGADA".format(lectura_id),
        )
        self.assertIn("RFID2: API confirmó DENEGADA", self.salida.getvalue())
        self.assertNotIn(UID_PRUEBA, self.salida.getvalue())

        def timeout(uid, lectura):
            raise ErrorApi("timeout sintético", origen="COMUNICACION")

        self.cliente.registrar_entrada_rfid2 = timeout
        lectura_id = "550e8400-e29b-41d4-a716-446655440003"
        os.write(
            self.maestro,
            ("RFID2,{},{}\n".format(lectura_id, UID_PRUEBA)).encode("ascii"),
        )
        self.assertEqual(
            self._recibir_hasta("RFID2_RESULT,"),
            "RFID2_RESULT,{},DENEGADA".format(lectura_id),
        )
        self.assertIn("sin respuesta API (timeout/comunicación)", self.salida.getvalue())
        self.assertNotIn(UID_PRUEBA, self.salida.getvalue())

    def test_uid_invalido_y_trama_mal_formada_no_llaman_api(self):
        os.write(self.maestro, b"RFID,002B,GGGGGGGG\n")
        self.assertEqual(self._recibir_hasta("ACK,"), "ACK,002B")
        self.assertEqual(self._recibir_hasta("RESULT,"), "RESULT,002B,ERROR")
        os.write(self.maestro, b"RFID,NOHEX,04A1B2C3\n")
        time.sleep(0.05)
        self.assertEqual(self.cliente.lecturas, [])

    def test_secuencia_serial_16_bits_ffff_valida_y_10000_invalida(self):
        self.assertEqual(
            analizar_trama_rfid("RFID,FFFF,{}".format(UID_PRUEBA)),
            ("FFFF", UID_PRUEBA),
        )
        with self.assertRaises(ErrorProtocolo):
            analizar_trama_rfid("RFID,10000,{}".format(UID_PRUEBA))

    def test_retransmision_de_misma_lectura_reutiliza_clave(self):
        os.write(self.maestro, b"PONG\n")
        trama = ("RFID,0030,{}\n".format(UID_PRUEBA)).encode("ascii")
        os.write(self.maestro, trama)
        self.assertEqual(self._recibir_hasta("ACK,"), "ACK,0030")
        self.assertEqual(self._recibir_hasta("RESULT,"), "RESULT,0030,DENY")
        os.write(self.maestro, b"RESULT_ACK,0030,DENY\n")

        os.write(self.maestro, trama)
        self.assertEqual(self._recibir_hasta("ACK,"), "ACK,0030")
        self.assertEqual(self._recibir_hasta("RESULT,"), "RESULT,0030,DENY")
        self.assertEqual(len(self.cliente.lecturas), 2)
        self.assertEqual(
            self.cliente.lecturas[0][2], self.cliente.lecturas[1][2]
        )

    def test_timeout_y_recuperacion_api_responden_error_y_luego_deny(self):
        cliente = ClienteConTimeout()
        self.sesion.cliente = cliente
        self.sesion.estado_dispositivo.cliente = cliente
        os.write(self.maestro, b"PONG\n")
        trama = ("RFID,0031,{}\n".format(UID_PRUEBA)).encode("ascii")
        os.write(self.maestro, trama)
        self.assertEqual(self._recibir_hasta("ACK,"), "ACK,0031")
        self.assertEqual(
            self._recibir_hasta("RESULT,"), "RESULT,0031,ERROR"
        )
        os.write(self.maestro, b"RESULT_ACK,0031,ERROR\n")

        os.write(self.maestro, trama)
        self.assertEqual(self._recibir_hasta("ACK,"), "ACK,0031")
        self.assertEqual(
            self._recibir_hasta("RESULT,"), "RESULT,0031,DENY"
        )
        self.assertEqual(len(cliente.lecturas), 2)
        self.assertEqual(cliente.lecturas[0][2], cliente.lecturas[1][2])



if __name__ == "__main__":
    unittest.main()
