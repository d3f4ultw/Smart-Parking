"""Pruebas enfocadas del protocolo de captura RFID 1 en el bridge."""

import unittest

from bridge import SesionBridge


CAPTURA_A = "0123456789abcdef0123456789abcdef"
CAPTURA_B = "fedcba9876543210fedcba9876543210"
UID_PRUEBA = "04A1B2C3"


class ClienteCapturasFalso:
    def __init__(self):
        self.activa = None
        self.estados = []
        self.lecturas = []
        self.fallar_primera_lectura = False

    def consultar_captura_activa(self):
        return self.activa

    def informar_escaneando(self, captura_id):
        self.estados.append(captura_id)
        if self.activa is not None:
            self.activa["estado"] = "ESCANEANDO"

    def enviar_lectura(self, secuencia, uid, clave_idempotencia):
        pass

    def enviar_lectura_capturada(self, captura_id, request_id, uid):
        self.lecturas.append((captura_id, request_id, uid))
        if self.fallar_primera_lectura and len(self.lecturas) == 1:
            from cliente_smartparking import ErrorApi

            raise ErrorApi("timeout simulado")
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


class CapturasRfid1Test(unittest.TestCase):
    def setUp(self):
        self.cliente = ClienteCapturasFalso()
        self.puerto = PuertoFalso()
        self.sesion = SesionBridge(self.cliente)

    def test_captura_activa_se_arma_y_una_cancelada_se_desarma(self):
        self.cliente.activa = {"capturaId": CAPTURA_A, "estado": "PENDIENTE"}
        self.sesion._reconciliar_captura(self.puerto)
        self.assertEqual(self.puerto.tramas, ["ENROLL_ARM," + CAPTURA_A])
        self.sesion._reconciliar_captura(self.puerto)
        self.assertEqual(len(self.puerto.tramas), 1)

        self.cliente.activa = None
        self.sesion._reconciliar_captura(self.puerto)
        self.assertEqual(
            self.puerto.tramas[-1], "ENROLL_CANCEL," + CAPTURA_A
        )

    def test_cambio_de_captura_cancela_la_anterior_y_arma_la_nueva(self):
        self.cliente.activa = {"capturaId": CAPTURA_A, "estado": "PENDIENTE"}
        self.sesion._reconciliar_captura(self.puerto)
        self.cliente.activa = {"capturaId": CAPTURA_B, "estado": "PENDIENTE"}
        self.sesion._reconciliar_captura(self.puerto)
        self.assertEqual(
            self.puerto.tramas[-2:],
            ["ENROLL_CANCEL," + CAPTURA_A, "ENROLL_ARM," + CAPTURA_B],
        )

    def test_estado_scanning_se_reporta_solo_para_captura_activa(self):
        self.cliente.activa = {"capturaId": CAPTURA_A, "estado": "PENDIENTE"}
        self.sesion._reconciliar_captura(self.puerto)
        self.sesion.procesar_linea(
            "ENROLL_STATE,{},SCANNING".format(CAPTURA_A), self.puerto
        )
        self.assertEqual(self.cliente.estados, [CAPTURA_A])
        self.sesion.procesar_linea(
            "ENROLL_STATE,{},SCANNING".format(CAPTURA_B), self.puerto
        )
        self.assertEqual(self.puerto.tramas[-1], "ENROLL_CANCEL," + CAPTURA_B)
        self.assertEqual(self.cliente.estados, [CAPTURA_A])

    def test_read_se_correlaciona_y_reintenta_la_misma_solicitud(self):
        self.cliente.activa = {"capturaId": CAPTURA_A, "estado": "ESCANEANDO"}
        self.sesion._reconciliar_captura(self.puerto)
        self.cliente.fallar_primera_lectura = True
        trama = "ENROLL_READ,{},{},{}".format(CAPTURA_A, "00af", UID_PRUEBA)
        self.sesion.procesar_linea(trama, self.puerto)
        self.assertEqual(
            self.cliente.lecturas,
            [(CAPTURA_A, "00AF", UID_PRUEBA)],
        )

        self.sesion.proximo_reintento_captura = 0
        self.sesion._reenviar_lectura_capturada()
        self.assertEqual(
            self.cliente.lecturas,
            [(CAPTURA_A, "00AF", UID_PRUEBA)] * 2,
        )
        self.assertIsNone(self.sesion.lectura_capturada_pendiente)

    def test_reinicio_rearma_estado_autoritativo_y_no_acepta_lectura_vieja(self):
        self.cliente.activa = {"capturaId": CAPTURA_A, "estado": "ESCANEANDO"}
        sesion_nueva = SesionBridge(self.cliente)
        sesion_nueva._reconciliar_captura(self.puerto)
        self.assertEqual(self.puerto.tramas[-1], "ENROLL_ARM," + CAPTURA_A)
        sesion_nueva.procesar_linea(
            "ENROLL_READ,{},{},{}".format(CAPTURA_B, "0001", UID_PRUEBA),
            self.puerto,
        )
        self.assertEqual(self.puerto.tramas[-1], "ENROLL_CANCEL," + CAPTURA_B)
        self.assertEqual(self.cliente.lecturas, [])

    def test_reinicio_cancela_vista_previa_sin_rearmar(self):
        self.cliente.activa = {"capturaId": CAPTURA_A, "estado": "VISTA_PREVIA"}
        sesion_nueva = SesionBridge(self.cliente)

        sesion_nueva._reconciliar_captura(self.puerto)
        sesion_nueva._reconciliar_captura(self.puerto)

        self.assertEqual(self.puerto.tramas, ["ENROLL_CANCEL," + CAPTURA_A])
        self.assertIsNone(sesion_nueva.captura_id_armada)

    def test_uid_registrado_rearma_explicito_y_la_siguiente_lectura_crea_vista_previa(self):
        self.cliente.activa = {"capturaId": CAPTURA_A, "estado": "ESCANEANDO"}
        self.sesion._reconciliar_captura(self.puerto)
        self.cliente.enviar_lectura_capturada = self._respuestas_cola(
            {
                "capturaId": CAPTURA_A,
                "estado": "ESCANEANDO",
                "resultado": "TARJETA_YA_REGISTRADA",
            },
            {
                "capturaId": CAPTURA_A,
                "estado": "VISTA_PREVIA",
                "resultado": "PREVIEW_READY",
            },
        )

        self.sesion.procesar_linea(
            "ENROLL_READ,{},{},{}".format(CAPTURA_A, "0001", UID_PRUEBA),
            self.puerto,
        )
        self.assertEqual(self.puerto.tramas[-1], "ENROLL_REARM,{},0001".format(CAPTURA_A))
        self.assertEqual(self.sesion.captura_estado_api, "ESCANEANDO")
        self.assertEqual(self.sesion.captura_id_armada, CAPTURA_A)
        self.assertEqual(self.sesion.captura_id_escanendo, CAPTURA_A)
        self.assertIsNone(self.sesion.lectura_capturada_pendiente)

        self.sesion.procesar_linea(
            "ENROLL_READ,{},{},{}".format(CAPTURA_A, "0002", UID_PRUEBA),
            self.puerto,
        )
        self.assertEqual(self.puerto.tramas[-1], "ENROLL_CANCEL," + CAPTURA_A)
        self.assertEqual(self.sesion.captura_estado_api, "VISTA_PREVIA")
        self.assertIsNone(self.sesion.lectura_capturada_pendiente)

    def test_uid_registrado_conserva_el_reintento_si_el_puerto_no_esta_disponible(self):
        solicitud = (CAPTURA_A, "0001", UID_PRUEBA)
        self.sesion.lectura_capturada_pendiente = solicitud
        self.cliente.enviar_lectura_capturada = self._respuestas_cola(
            {
                "capturaId": CAPTURA_A,
                "estado": "ESCANEANDO",
                "resultado": "TARJETA_YA_REGISTRADA",
            }
        )

        self.sesion._reenviar_lectura_capturada()

        self.assertEqual(self.sesion.lectura_capturada_pendiente, solicitud)
        self.assertFalse(any(trama.startswith("ENROLL_REARM,") for trama in self.puerto.tramas))

    def _respuestas_cola(self, *respuestas):
        pendientes = list(respuestas)

        def enviar(captura_id, request_id, uid):
            self.cliente.lecturas.append((captura_id, request_id, uid))
            return pendientes.pop(0)

        return enviar

    def test_lectura_ordinaria_sigue_siendo_deny_y_no_usa_enrollment(self):
        self.cliente.activa = {"capturaId": CAPTURA_A, "estado": "ESCANEANDO"}
        self.sesion._reconciliar_captura(self.puerto)
        self.sesion.procesar_linea("RFID,002A,{}".format(UID_PRUEBA), self.puerto)
        self.assertIn("RESULT,002A,DENY", self.puerto.tramas)
        self.assertEqual(self.cliente.lecturas, [])

    def test_respuesta_de_asociacion_no_emite_allow(self):
        self.cliente.activa = {"capturaId": CAPTURA_A, "estado": "ESCANEANDO"}
        self.sesion._reconciliar_captura(self.puerto)
        self.sesion.procesar_linea(
            "ENROLL_READ,{},{},{}".format(CAPTURA_A, "0002", UID_PRUEBA),
            self.puerto,
        )
        self.assertNotIn("ALLOW", self.puerto.tramas)


if __name__ == "__main__":
    unittest.main()
