"""Comprueba la recuperación de capturas y la entrega ágil de decisiones."""

import contextlib
import io
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import bridge
from bridge import SesionBridge
from bucle_serial import BucleSerial


CAPTURA = "a" * 32
OTRA_CAPTURA = "b" * 32
UID_SINTETICO = "A" * 8


class ClienteCapturaFalso:
    def consultar_captura_activa(self):
        return None

    def enviar_lectura_capturada(self, captura_id, request_id, uid):
        return {
            "capturaId": captura_id,
            "estado": "VISTA_PREVIA",
            "resultado": "PREVIEW_READY",
        }


class PuertoFalso:
    def __init__(self):
        self.tramas = []

    def escribir_linea(self, linea):
        self.tramas.append(linea)


class RecuperacionCapturaTest(unittest.TestCase):
    def setUp(self):
        self.sesion = SesionBridge(ClienteCapturaFalso())
        self.puerto = PuertoFalso()
        self.captura = {"capturaId": CAPTURA, "estado": "ESCANEANDO"}

    def test_reintenta_armado_perdido_solo_mientras_la_captura_sigue_vigente(self):
        reloj = SimpleNamespace(monotonic=Mock(side_effect=[10.0, 10.5, 11.1]))
        with patch.object(bridge, "time", reloj):
            for _ in range(3):
                self.sesion._reconciliar_captura(self.puerto, self.captura)

        self.assertEqual(self.puerto.tramas, [
            "ENROLL_ARM," + CAPTURA,
            "ENROLL_ARM," + CAPTURA,
        ])

        self.sesion._reconciliar_captura(self.puerto, None)
        self.sesion._reconciliar_captura(self.puerto, None)
        self.assertEqual(self.puerto.tramas[-1], "ENROLL_CANCEL," + CAPTURA)
        self.assertEqual(len(self.puerto.tramas), 3)

    def test_respuesta_antigua_no_rearma_una_vista_previa_confirmada(self):
        self.sesion._reconciliar_captura(self.puerto, self.captura)
        self.sesion.procesar_linea(
            "ENROLL_READ,{},{},{}".format(CAPTURA, "0001", UID_SINTETICO),
            self.puerto,
        )
        self.sesion._reconciliar_captura(self.puerto, self.captura)

        self.assertEqual(self.puerto.tramas, [
            "ENROLL_ARM," + CAPTURA,
            "ENROLL_CANCEL," + CAPTURA,
        ])
        self.assertEqual(self.sesion.captura_estado_api, "VISTA_PREVIA")

        nueva = {"capturaId": OTRA_CAPTURA, "estado": "ESCANEANDO"}
        self.sesion._reconciliar_captura(self.puerto, nueva)
        self.assertEqual(self.puerto.tramas[-1], "ENROLL_ARM," + OTRA_CAPTURA)

    def test_no_rearma_mientras_una_lectura_espera_respuesta(self):
        reloj = SimpleNamespace(monotonic=Mock(side_effect=[10.0, 11.1]))
        with patch.object(bridge, "time", reloj):
            self.sesion._reconciliar_captura(self.puerto, self.captura)
            self.sesion.lectura_capturada_pendiente = (CAPTURA, "0001", UID_SINTETICO)
            self.sesion._reconciliar_captura(self.puerto, self.captura)

        self.assertEqual(self.puerto.tramas, ["ENROLL_ARM," + CAPTURA])

    def test_reinicio_de_placa_rearma_sin_esperar_el_siguiente_intervalo(self):
        reloj = SimpleNamespace(monotonic=Mock(side_effect=[10.0, 10.1]))
        with patch.object(bridge, "time", reloj):
            self.sesion._reconciliar_captura(self.puerto, self.captura)
            self.sesion.procesar_linea("READY,1", self.puerto)
            self.sesion._reconciliar_captura(self.puerto, self.captura)

        self.assertEqual(self.puerto.tramas, [
            "ENROLL_ARM," + CAPTURA,
            "ENROLL_ARM," + CAPTURA,
        ])

    def test_reinicio_de_placa_no_rearma_una_vista_previa(self):
        self.sesion._reconciliar_captura(self.puerto, self.captura)
        self.sesion.procesar_linea(
            "ENROLL_READ,{},{},{}".format(CAPTURA, "0001", UID_SINTETICO),
            self.puerto,
        )
        self.sesion.procesar_linea("READY,1", self.puerto)
        self.sesion._reconciliar_captura(self.puerto, self.captura)

        self.assertEqual(self.puerto.tramas, [
            "ENROLL_ARM," + CAPTURA,
            "ENROLL_CANCEL," + CAPTURA,
        ])
        self.assertEqual(self.sesion.captura_estado_api, "VISTA_PREVIA")

    def test_respuesta_de_lectura_anterior_no_desarma_la_captura_nueva(self):
        self.sesion._reconciliar_captura(self.puerto, self.captura)
        self.sesion.lectura_capturada_pendiente = (CAPTURA, "0001", UID_SINTETICO)
        nueva = {"capturaId": OTRA_CAPTURA, "estado": "ESCANEANDO"}
        self.sesion._reconciliar_captura(self.puerto, nueva)
        self.sesion._reenviar_lectura_capturada(self.puerto)
        self.sesion._reconciliar_captura(self.puerto, nueva)

        self.assertEqual(self.sesion.captura_id_activa, OTRA_CAPTURA)
        self.assertEqual(self.sesion.captura_id_armada, OTRA_CAPTURA)
        self.assertEqual(self.sesion.captura_estado_api, "ESCANEANDO")
        self.assertEqual(self.puerto.tramas, [
            "ENROLL_ARM," + CAPTURA,
            "ENROLL_CANCEL," + CAPTURA,
            "ENROLL_ARM," + OTRA_CAPTURA,
        ])

    def test_rechazo_tardio_no_rearma_una_captura_cancelada(self):
        self.sesion._reconciliar_captura(self.puerto, self.captura)
        self.sesion.lectura_capturada_pendiente = (CAPTURA, "0001", UID_SINTETICO)
        self.sesion._reconciliar_captura(self.puerto, None)
        self.sesion.cliente.enviar_lectura_capturada = Mock(return_value={
            "capturaId": CAPTURA,
            "estado": "ESCANEANDO",
            "resultado": "TARJETA_YA_REGISTRADA",
        })
        self.sesion._reenviar_lectura_capturada(self.puerto)

        self.assertEqual(self.puerto.tramas, [
            "ENROLL_ARM," + CAPTURA,
            "ENROLL_CANCEL," + CAPTURA,
        ])
        self.assertIsNone(self.sesion.lectura_capturada_pendiente)
        self.assertIsNone(self.sesion.captura_id_activa)

    def test_estado_rfid1_se_informa_solo_al_cambiar_y_sin_datos_de_tarjeta(self):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            self.sesion.procesar_linea("RFID_READER,READY,92", self.puerto)
            self.sesion.procesar_linea("RFID_READER,READY,92", self.puerto)
            self.sesion.procesar_linea("RFID_READER,ERROR,OSError", self.puerto)
            self.sesion.procesar_linea("RFID_READER,READY," + UID_SINTETICO, self.puerto)

        self.assertEqual(salida.getvalue().splitlines(), [
            "RFID1: lector inicializado.",
            "RFID1: lector no inicializado.",
        ])
        self.assertNotIn(UID_SINTETICO, salida.getvalue())


class PuertoConEspera:
    def __init__(self):
        self.leyendo = threading.Event()
        self.entrada_entregada = threading.Event()
        self.salida_entregada = threading.Event()

    def leer_linea(self, espera):
        self.leyendo.set()
        time.sleep(espera)
        return None

    def escribir_linea(self, linea):
        if linea == "DECISION_ENTRADA":
            self.entrada_entregada.set()
        elif linea == "DECISION_SALIDA":
            self.salida_entregada.set()


class SalidaFalsa:
    def __init__(self):
        self.resultado_listo = threading.Event()

    def atender(self, puerto):
        if self.resultado_listo.is_set():
            self.resultado_listo.clear()
            puerto.escribir_linea("DECISION_SALIDA")


class EntregaDecisionTest(unittest.TestCase):
    def setUp(self):
        self.puerto = PuertoConEspera()
        self.salida = SalidaFalsa()
        sesion = SimpleNamespace(
            intervalo_ping=60.0,
            intervalo_lectura=bridge.INTERVALO_LECTURA,
            ultimo_pong=None,
            salida_rfid3=self.salida,
            estado_dispositivo=SimpleNamespace(actualizar=lambda conectado: None),
            _perdio_handshake=lambda ahora, inicio: False,
        )
        self.bucle = BucleSerial(sesion, self.puerto, None)
        self.bucle.iniciar()
        self.addCleanup(self.bucle.cerrar)
        self.assertTrue(self.puerto.leyendo.wait(0.5))

    def test_decision_de_entrada_no_espera_doscientos_milisegundos(self):
        self.bucle.escribir_linea("DECISION_ENTRADA")
        self.assertTrue(self.puerto.entrada_entregada.wait(0.15))

    def test_decision_de_salida_no_espera_doscientos_milisegundos(self):
        self.salida.resultado_listo.set()
        self.assertTrue(self.puerto.salida_entregada.wait(0.15))


if __name__ == "__main__":
    unittest.main()
