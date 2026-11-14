"""Ensaya el bridge con API y UART simuladas, incluidas respuestas perdidas."""

import threading
import time
import unittest
import uuid
import base64
import hashlib
import hmac

from cliente_smartparking import ErrorApi
from salida_manual import GestorSalidaManual, _comprimir_uuid


OPERACION = "01234567-89ab-cdef-0123-456789abcdef"
BOOT = "A" * 22
TICKET = "B" * 21 + "A"
CLAVE = bytes(range(32))  # Solo se usa en esta API sintética.


def firmar(accion, operacion, boot, ticket, codigo=None):
    texto = "smartparking.manual.v1|{}|{}|{}|{}".format(
        accion, _comprimir_uuid(operacion), boot, ticket
    )
    if codigo is not None:
        texto += "|" + codigo
    return base64.urlsafe_b64encode(hmac.new(CLAVE, texto.encode("ascii"), hashlib.sha256).digest()[:12]).decode("ascii")


def trama_resultado(operacion, boot, ticket=TICKET, codigo="E", firma=None):
    firma = firma or firmar("RESULT", operacion, boot, ticket, codigo)
    return "SM_RES,{},{},{},{},{}".format(_comprimir_uuid(operacion), boot, ticket, codigo, firma)


class PuertoFalso:
    def __init__(self):
        self.lineas = []

    def escribir_linea(self, linea):
        self.lineas.append(linea)


class ClienteFalso:
    def __init__(self):
        self.estado = "PENDIENTE"
        self.emisiones = 0
        self.resultados = []
        self.rechazos_mac = 0
        self.perder_permiso = False
        self.bloqueo = None
        self.inicio = threading.Event()

    def consultar_salida_manual(self, despues=None):
        if self.estado is None:
            return None
        respuesta = {"operacionId": OPERACION, "estado": self.estado}
        if self.estado in ("EMITIDA", "INCIERTA"):
            respuesta["bootId"] = BOOT
            respuesta["ticketId"] = TICKET
        return respuesta

    def emitir_salida_manual(self, operacion, boot, ticket):
        self.emisiones += 1
        self.estado = "EMITIDA"
        self.inicio.set()
        if self.bloqueo is not None:
            self.bloqueo.wait(2)
        if self.perder_permiso:
            raise ErrorApi("Respuesta perdida", origen="COMUNICACION")
        return firmar("EXEC", operacion, boot, ticket)

    def informar_resultado_salida_manual(self, operacion, boot, ticket, resultado, firma):
        codigo = "E" if resultado == "EJECUTADA" else "N"
        if not hmac.compare_digest(firma, firmar("RESULT", operacion, boot, ticket, codigo)):
            self.rechazos_mac += 1
            raise ErrorApi("Acuse inválido", estado_http=409)
        self.resultados.append((operacion, boot, resultado))
        self.estado = None
        return {"operacionId": operacion, "movimientoId": 1, "estado": "CONFIRMADA"}


class PruebasBridgeManual(unittest.TestCase):
    def setUp(self):
        self.ahora = 0.0
        self.puerto = PuertoFalso()
        self.cliente = ClienteFalso()
        self.gestor = GestorSalidaManual(self.cliente, lambda: self.ahora)
        self.gestor.conectar()

    def avanzar_hasta(self, condicion, pasos=400):
        for _ in range(pasos):
            self.gestor.atender(self.puerto)
            if condicion():
                return
            self.ahora += 0.025
            time.sleep(0.001)
        self.fail("No se alcanzó la condición esperada en el bridge.")

    def preparar(self):
        self.avanzar_hasta(lambda: any(x.startswith("SM_PREP,") for x in self.puerto.lineas))
        self.gestor.recibir("SM_LISTA,{},{},{}".format(_comprimir_uuid(OPERACION), BOOT, TICKET), self.puerto)

    def test_permiso_unico_y_resultado_correlacionado(self):
        self.preparar()
        self.avanzar_hasta(lambda: any(x.startswith("SM_EXEC,") for x in self.puerto.lineas))
        self.gestor.recibir("SM_LISTA,{},{},{}".format(_comprimir_uuid(OPERACION), BOOT, TICKET), self.puerto)
        self.gestor.recibir(trama_resultado(OPERACION, "x" * 21 + "A"), self.puerto)
        self.gestor.recibir(trama_resultado(OPERACION, BOOT), self.puerto)
        self.avanzar_hasta(lambda: bool(self.cliente.resultados))
        self.assertEqual(self.cliente.resultados, [(OPERACION, BOOT, "EJECUTADA")])
        self.assertEqual(self.cliente.emisiones, 1)
        self.assertEqual(sum(x.startswith("SM_EXEC,") for x in self.puerto.lineas), 1)
        self.assertTrue(all(len(x) <= 96 for x in self.puerto.lineas))

    def test_acuse_falsificado_se_rechaza_y_no_bloquea_el_legitimo(self):
        self.preparar()
        self.avanzar_hasta(lambda: any(x.startswith("SM_EXEC,") for x in self.puerto.lineas))
        self.gestor.recibir(trama_resultado(OPERACION, BOOT, firma="A" * 16), self.puerto)
        self.avanzar_hasta(lambda: self.cliente.rechazos_mac == 1)
        self.assertEqual(self.cliente.resultados, [])
        self.gestor.recibir(trama_resultado(OPERACION, BOOT), self.puerto)
        self.avanzar_hasta(lambda: bool(self.cliente.resultados))
        self.assertEqual(self.cliente.resultados, [(OPERACION, BOOT, "EJECUTADA")])

    def test_permiso_perdido_no_envia_ejecucion_y_solo_consulta(self):
        self.cliente.perder_permiso = True
        self.preparar()
        self.avanzar_hasta(lambda: any(x.startswith("SM_GET,") for x in self.puerto.lineas))
        self.assertEqual(self.cliente.emisiones, 1)
        self.assertFalse(any(x.startswith("SM_EXEC,") for x in self.puerto.lineas))

    def test_reconexion_descarta_permiso_http_anterior(self):
        self.cliente.bloqueo = threading.Event()
        self.preparar()
        self.avanzar_hasta(lambda: self.cliente.inicio.is_set())
        self.gestor.desconectar()
        self.gestor.conectar()
        self.cliente.bloqueo.set()
        self.avanzar_hasta(lambda: any(x.startswith("SM_GET,") for x in self.puerto.lineas))
        self.assertFalse(any(x.startswith("SM_EXEC,") for x in self.puerto.lineas))

    def test_sin_capacidad_firmware_no_solicita_permiso(self):
        self.avanzar_hasta(lambda: len(self.puerto.lineas) >= 3)
        self.assertEqual(self.cliente.emisiones, 0)
        self.assertTrue(all(x.startswith("SM_PREP,") for x in self.puerto.lineas))

    def test_recuperacion_consulta_sin_reemitir_orden(self):
        self.cliente.estado = "INCIERTA"
        self.avanzar_hasta(lambda: any(x.startswith("SM_GET,") for x in self.puerto.lineas))
        self.gestor.recibir(trama_resultado(OPERACION, BOOT), self.puerto)
        self.avanzar_hasta(lambda: bool(self.cliente.resultados))
        self.assertEqual(self.cliente.emisiones, 0)
        self.assertFalse(any(x.startswith("SM_EXEC,") for x in self.puerto.lineas))

    def test_permiso_tardio_no_ejecuta_un_ticket_que_puede_haber_vencido(self):
        self.cliente.bloqueo = threading.Event()
        self.preparar()
        self.avanzar_hasta(lambda: self.cliente.inicio.is_set())
        self.ahora += 5
        self.cliente.bloqueo.set()
        self.avanzar_hasta(lambda: any(x.startswith("SM_GET,") for x in self.puerto.lineas))
        self.assertEqual(self.cliente.emisiones, 1)
        self.assertFalse(any(x.startswith("SM_EXEC,") for x in self.puerto.lineas))

    def test_operacion_caducada_libera_el_gestor_sin_nueva_ejecucion(self):
        self.avanzar_hasta(lambda: any(x.startswith("SM_PREP,") for x in self.puerto.lineas))
        self.cliente.estado = None
        self.avanzar_hasta(lambda: self.gestor.actual is None)
        self.assertFalse(any(x.startswith("SM_EXEC,") for x in self.puerto.lineas))

    def test_dos_inciertas_se_consultan_aunque_la_primera_no_tenga_resultado(self):
        segunda = "fedcba98-7654-3210-fedc-ba9876543210"
        boot_segundo = "C" * 21 + "A"

        def consultar(despues=None):
            if despues == OPERACION:
                return {"operacionId": segunda, "estado": "INCIERTA", "bootId": boot_segundo, "ticketId": TICKET}
            return {"operacionId": OPERACION, "estado": "INCIERTA", "bootId": BOOT, "ticketId": TICKET}

        self.cliente.consultar_salida_manual = consultar
        primero_hex = _comprimir_uuid(OPERACION)
        segundo_hex = _comprimir_uuid(segunda)
        self.avanzar_hasta(lambda: any(x == "SM_GET,{},{}".format(primero_hex, BOOT)
                                     for x in self.puerto.lineas))
        self.avanzar_hasta(lambda: any(x == "SM_GET,{},{}".format(segundo_hex, boot_segundo)
                                     for x in self.puerto.lineas))
        self.gestor.recibir(trama_resultado(segunda, boot_segundo), self.puerto)
        self.avanzar_hasta(lambda: bool(self.cliente.resultados))
        self.assertEqual(self.cliente.resultados, [(segunda, boot_segundo, "EJECUTADA")])
        self.assertEqual(self.cliente.emisiones, 0)
        self.assertFalse(any(x.startswith("SM_EXEC,") for x in self.puerto.lineas))

    def test_dos_acuses_consultados_se_notifican_sin_reabrir(self):
        segunda = "fedcba98-7654-3210-fedc-ba9876543210"
        boot_segundo = "C" * 21 + "A"

        def consultar(despues=None):
            if despues == OPERACION:
                return {"operacionId": segunda, "estado": "INCIERTA", "bootId": boot_segundo, "ticketId": TICKET}
            return {"operacionId": OPERACION, "estado": "INCIERTA", "bootId": BOOT, "ticketId": TICKET}

        self.cliente.consultar_salida_manual = consultar
        primero_hex = _comprimir_uuid(OPERACION)
        segundo_hex = _comprimir_uuid(segunda)
        self.avanzar_hasta(lambda: any(x == "SM_GET,{},{}".format(primero_hex, BOOT)
                                     for x in self.puerto.lineas))
        self.avanzar_hasta(lambda: any(x == "SM_GET,{},{}".format(segundo_hex, boot_segundo)
                                     for x in self.puerto.lineas))
        self.gestor.recibir(trama_resultado(OPERACION, BOOT), self.puerto)
        self.gestor.recibir(trama_resultado(segunda, boot_segundo), self.puerto)
        self.avanzar_hasta(lambda: len(self.cliente.resultados) == 2)
        self.assertEqual(set(self.cliente.resultados), {
            (OPERACION, BOOT, "EJECUTADA"), (segunda, boot_segundo, "EJECUTADA")
        })
        self.assertEqual(self.cliente.emisiones, 0)
        self.assertFalse(any(x.startswith("SM_EXEC,") for x in self.puerto.lineas))

    def test_preparacion_sin_respuesta_no_oculta_otra_incierta(self):
        segunda = "fedcba98-7654-3210-fedc-ba9876543210"
        boot_segundo = "C" * 21 + "A"

        def consultar(despues=None):
            if despues == OPERACION:
                return {"operacionId": segunda, "estado": "INCIERTA", "bootId": boot_segundo, "ticketId": TICKET}
            return {"operacionId": OPERACION, "estado": "PENDIENTE"}

        self.cliente.consultar_salida_manual = consultar
        segunda_hex = _comprimir_uuid(segunda)
        self.avanzar_hasta(lambda: any(x.startswith("SM_PREP,") for x in self.puerto.lineas))
        self.avanzar_hasta(lambda: any(x == "SM_GET,{},{}".format(segunda_hex, boot_segundo)
                                     for x in self.puerto.lineas), pasos=700)
        self.assertEqual(self.cliente.emisiones, 0)
        self.assertFalse(any(x.startswith("SM_EXEC,") for x in self.puerto.lineas))


if __name__ == "__main__":
    unittest.main()
