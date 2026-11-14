"""Pruebas de enrolamiento y reconexion sobre pseudo-terminal."""

import contextlib
import io
import os
import threading
import unittest
from unittest.mock import patch

from soporte_bridge_pty import (
    SoporteBridgePty,
    bridge,
    ClienteFalso,
    UID_PRUEBA,
    UID_ALTERNATIVO,
    CAPTURA_ID,
    ErrorApi,
)

class BridgePtyEnrolamientoTest(SoporteBridgePty):
    def test_pty_lectura_aceptada_detiene_lector_sin_asociar(self):
        self.cliente.activa = {"capturaId": CAPTURA_ID, "estado": "ESCANEANDO"}
        self.assertEqual(
            self._recibir_hasta("ENROLL_ARM,"), "ENROLL_ARM," + CAPTURA_ID
        )

        os.write(
            self.maestro,
            ("ENROLL_READ,{},{},{}\n".format(CAPTURA_ID, "0001", UID_PRUEBA)).encode("ascii"),
        )

        self.assertEqual(
            self._recibir_hasta("ENROLL_CANCEL,"), "ENROLL_CANCEL," + CAPTURA_ID
        )
        self.assertEqual(
            self.cliente.lecturas_capturadas, [(CAPTURA_ID, "0001", UID_PRUEBA)]
        )
        salida = self.salida.getvalue()
        self.assertIn("vista previa", salida)
        self.assertNotIn("asociación", salida)
        self.assertNotIn(UID_PRUEBA, salida)
        self.assertNotIn("ALLOW", salida)

    def test_ptty_uid_registrado_permite_otra_lectura_y_despues_detiene(self):
        self.cliente.activa = {"capturaId": CAPTURA_ID, "estado": "ESCANEANDO"}
        self.cliente.resultados_capturados = [
            {
                "capturaId": CAPTURA_ID,
                "estado": "ESCANEANDO",
                "resultado": "TARJETA_YA_REGISTRADA",
            },
            {
                "capturaId": CAPTURA_ID,
                "estado": "VISTA_PREVIA",
                "resultado": "PREVIEW_READY",
            },
        ]
        self.assertEqual(
            self._recibir_hasta("ENROLL_ARM,"), "ENROLL_ARM," + CAPTURA_ID
        )
        os.write(
            self.maestro,
            ("ENROLL_READ,{},{},{}\n".format(CAPTURA_ID, "0001", UID_PRUEBA)).encode("ascii"),
        )
        self.assertEqual(
            self._recibir_hasta("ENROLL_REARM,"),
            "ENROLL_REARM,{},0001".format(CAPTURA_ID),
        )

        os.write(
            self.maestro,
            ("ENROLL_READ,{},{},{}\n".format(CAPTURA_ID, "0002", UID_ALTERNATIVO)).encode("ascii"),
        )

        self.assertEqual(
            self._recibir_hasta("ENROLL_CANCEL,"), "ENROLL_CANCEL," + CAPTURA_ID
        )
        self.assertEqual(
            self.cliente.lecturas_capturadas,
            [
                (CAPTURA_ID, "0001", UID_PRUEBA),
                (CAPTURA_ID, "0002", UID_ALTERNATIVO),
            ],
        )
        salida = self.salida.getvalue()
        self.assertNotIn(UID_PRUEBA, salida)
        self.assertNotIn(UID_ALTERNATIVO, salida)
        self.assertNotIn("ALLOW", salida)

    def test_bucle_reabre_un_puerto_tras_desconexion_simulada(self):
        detener = threading.Event()
        puertos = []
        cliente = ClienteFalso()

        class PuertoSimulado:
            def __init__(self, falla):
                self.falla = falla
                self.cerrado = False
                self.escrituras = []

            def __enter__(self):
                return self

            def __exit__(self, tipo, valor, traza):
                self.cerrado = True

            def escribir_linea(self, linea):
                self.escrituras.append(linea)

            def leer_linea(self, tiempo_espera):
                if self.falla:
                    raise OSError("desconexión simulada")
                detener.set()
                return "PONG"

        def crear_puerto(ruta):
            puerto = PuertoSimulado(falla=not puertos)
            puertos.append(puerto)
            return puerto

        with patch("bridge.PuertoSerie", side_effect=crear_puerto), \
                patch("bridge.seleccionar_puerto", return_value="pty-simulado"), \
                patch("bridge.time.sleep", return_value=None):
            with contextlib.redirect_stdout(io.StringIO()):
                bridge.ejecutar(None, cliente, detener)

        self.assertEqual(len(puertos), 2)
        self.assertTrue(all(puerto.cerrado for puerto in puertos))
        self.assertEqual(puertos[0].escrituras, ["PING"])
        self.assertEqual(puertos[1].escrituras, ["PING"])
        self.assertIn(False, cliente.estados_dispositivo)


if __name__ == "__main__":
    unittest.main()
