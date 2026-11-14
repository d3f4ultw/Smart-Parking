"""inicia y organiza el intercambio de mensajes entre la placa ESP32 y el servicio"""

import argparse
import collections
import hashlib
import os
import re
import signal
import threading
import time

from cliente_capturas import ClienteCapturas
from bucle_serial import BucleSerial
from cliente_smartparking import ErrorApi
from consulta_captura import ConsultaCaptura
from estado_dispositivo import EstadoDispositivo
from puerto_serie import ErrorProtocolo, PuertoSerie, seleccionar_puerto
from tramas_rfid1 import CacheClavesLectura, PATRON_UID, analizar_trama_rfid
from entrada_rfid2 import procesar_trama_entrada_rfid2
from salida_rfid3 import GestorSalidaRfid3
from salida_manual import GestorSalidaManual
from capacidad_manual import CapacidadManual


INTERVALO_PING = 2.0
TIEMPO_ESPERA_PONG = 6.0
INTERVALO_LECTURA = 0.02
INTERVALO_RECONEXION = 2.0
INTERVALO_CONSULTA_CAPTURA = 0.25
INTERVALO_REINTENTO_CAPTURA = 1.0
INTERVALO_REARMADO_CAPTURA = 1.0
MAXIMO_RESULTADOS_PENDIENTES = 128
PATRON_RESULT_ACK = re.compile(r"RESULT_ACK,([0-9A-Fa-f]{1,4}),(ALLOW|DENY|ERROR)\Z")
PATRON_ENROLL_STATE = re.compile(
    r"ENROLL_STATE,([0-9a-f]{32}),(SCANNING|CANCELLED)\Z"
)
PATRON_ENROLL_READ = re.compile(
    r"ENROLL_READ,([0-9a-f]{32}),([0-9A-Fa-f]{1,4}),"
    r"([0-9A-Fa-f]{8}|[0-9A-Fa-f]{14}|[0-9A-Fa-f]{20})\Z"
)
PATRON_LECTOR_LISTO = re.compile(r"RFID_READER,READY,[0-9A-Fa-f]{2}\Z")
PATRON_LECTOR_ERROR = re.compile(r"RFID_READER,ERROR,[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


class SesionBridge:
    """coordina las lecturas, las capturas y las salidas entre el ESP32 y el servicio"""

    def __init__(
        self,
        cliente,
        intervalo_ping=INTERVALO_PING,
        tiempo_espera_pong=TIEMPO_ESPERA_PONG,
        intervalo_lectura=INTERVALO_LECTURA,
    ):
        self.cliente = cliente
        self.intervalo_ping = intervalo_ping
        self.tiempo_espera_pong = tiempo_espera_pong
        self.intervalo_lectura = intervalo_lectura
        self.claves = CacheClavesLectura()
        self.pendientes = collections.OrderedDict()
        self.ultimo_pong = None
        self.captura_id_activa = None
        self.captura_estado_api = None
        self.captura_id_armada = None
        self.captura_id_escanendo = None
        self.captura_id_cancelada = None
        self.lectura_capturada_pendiente = None
        self.estado_lector_rfid1 = None
        self.proximo_armado_captura = 0.0
        self.proxima_consulta_captura = 0.0
        self.proximo_reintento_captura = 0.0
        self.estado_dispositivo = EstadoDispositivo(cliente)
        self.salida_rfid3 = GestorSalidaRfid3(cliente)
        self.salida_manual = GestorSalidaManual(cliente)
        self.capacidad_manual = CapacidadManual(cliente)
        self.consulta_captura = ConsultaCaptura(cliente)

    def ejecutar(self, puerto, detener=None):
        """mantiene el intercambio con la placa ESP32 mientras responda; termina si deja de responder o se pide cerrar"""
        serial = BucleSerial(self, puerto, detener)
        self.salida_manual.conectar()
        self.capacidad_manual.conectar()
        serial.iniciar()
        try:
            while detener is None or not detener.is_set():
                ahora = time.monotonic()
                if ahora >= self.proxima_consulta_captura:
                    try:
                        captura = self.consulta_captura.obtener()
                        if captura is not ...:
                            self._reconciliar_captura(serial, captura)
                        self.proxima_consulta_captura = (
                            time.monotonic() + INTERVALO_CONSULTA_CAPTURA
                        )
                    except ErrorApi:
                        print("No se pudo consultar la captura; se reintentará.")
                        self.proxima_consulta_captura = (
                            time.monotonic() + INTERVALO_RECONEXION
                        )
                self._reenviar_lectura_capturada(serial)
                self.capacidad_manual.atender(serial)
                self.salida_manual.atender(serial, self.capacidad_manual.disponible())
                linea = serial.leer_linea(self.intervalo_lectura)
                if linea:
                    self.procesar_linea(linea, serial)
        finally:
            self.salida_manual.desconectar()
            self.capacidad_manual.desconectar()
            serial.cerrar()

    def _perdio_handshake(self, ahora, inicio):
        """indica si la placa ESP32 lleva más tiempo del permitido sin responder, incluso antes de su primera respuesta"""
        referencia = self.ultimo_pong if self.ultimo_pong is not None else inicio
        return ahora - referencia > self.tiempo_espera_pong

    def procesar_linea(self, linea, puerto):
        """interpreta los mensajes de la placa ESP32 y los entrega al proceso de entrada, salida, captura o confirmación que corresponda"""
        if linea == "PONG":
            self.ultimo_pong = time.monotonic()
            print("USB: PONG")
            return
        if linea == "READY,1":
            self.captura_id_armada = None
            self.captura_id_escanendo = None
            self.proximo_armado_captura = 0.0
            self.proxima_consulta_captura = 0.0
            self.estado_lector_rfid1 = None
            return
        if linea.startswith("RFID_READER,"):
            self._procesar_estado_lector(linea)
            return
        if linea.startswith("RFID2,"):
            procesar_trama_entrada_rfid2(linea, self.cliente, puerto)
            return
        if linea.startswith("RFID3,"):
            self.salida_rfid3.recibir(linea, puerto)
            return
        if linea.startswith("SM_PROBE_OK,"):
            self.capacidad_manual.recibir(linea)
            return
        if linea.startswith("SM_"):
            self.salida_manual.recibir(linea, puerto)
            return
        if linea == "RFID" or linea.startswith("RFID,"):
            self._procesar_lectura(linea, puerto)
            return
        if linea.startswith("ENROLL_STATE,"):
            self._procesar_estado_enrolamiento(linea, puerto)
            return
        if linea.startswith("ENROLL_READ,"):
            self._procesar_lectura_enrolamiento(linea, puerto)
            return
        if linea.startswith("RESULT_ACK,"):
            self._procesar_confirmacion(linea)

    def _procesar_estado_lector(self, linea):
        """Registra cambios de inicialización de RFID1 sin publicar datos de tarjetas."""
        if PATRON_LECTOR_LISTO.fullmatch(linea):
            estado = "READY"
            mensaje = "RFID1: lector inicializado."
        elif PATRON_LECTOR_ERROR.fullmatch(linea):
            estado = "ERROR"
            mensaje = "RFID1: lector no inicializado."
        else:
            return
        if estado != self.estado_lector_rfid1:
            self.estado_lector_rfid1 = estado
            print(mensaje)

    def _reconciliar_captura(self, puerto, captura=...):
        """compara la captura activa del servicio con la que sigue el puente e indica a la placa ESP32 cuándo empezar o detener la lectura"""
        if captura is ...:
            captura = self.cliente.consultar_captura_activa()
        if captura is None:
            if self.captura_id_activa is not None:
                self._cancelar_lector(self.captura_id_activa, puerto)
            self.captura_id_activa = None
            self.captura_estado_api = None
            self.captura_id_armada = None
            self.captura_id_escanendo = None
            self.captura_id_cancelada = None
            self.proximo_armado_captura = 0.0
            return

        captura_id = captura["capturaId"]
        estado_api = captura["estado"]
        if (
            self.captura_id_activa == captura_id
            and self.captura_estado_api == "VISTA_PREVIA"
            and estado_api in ("PENDIENTE", "ESCANEANDO")
        ):
            # Una consulta anterior no puede volver a armar una vista previa ya confirmada.
            self._cancelar_lector(captura_id, puerto)
            return
        if self.captura_id_activa != captura_id:
            if self.captura_id_activa is not None:
                self._cancelar_lector(self.captura_id_activa, puerto)
            self.captura_id_activa = captura_id
            self.captura_id_armada = None
            self.captura_id_escanendo = None
            self.captura_id_cancelada = None

        self.captura_estado_api = estado_api
        if estado_api == "VISTA_PREVIA":
            self._cancelar_lector(captura_id, puerto)
            return
        if estado_api == "PENDIENTE":
            # El lector empieza a buscar una tarjeta solo después de que el servicio confirme el inicio de la lectura.
            if not self._informar_escaneando(captura_id):
                return
            estado_api = "ESCANEANDO"
        pendiente = self.lectura_capturada_pendiente
        if estado_api == "ESCANEANDO" and (
            pendiente is None or pendiente[0] != captura_id
        ):
            self._armar_lector(captura_id, puerto)
            self.captura_id_escanendo = captura_id

    def _armar_lector(self, captura_id, puerto):
        ahora = time.monotonic()
        if self.captura_id_armada != captura_id or ahora >= self.proximo_armado_captura:
            puerto.escribir_linea("ENROLL_ARM,{}".format(captura_id))
            self.captura_id_armada = captura_id
            self.proximo_armado_captura = ahora + INTERVALO_REARMADO_CAPTURA
        self.captura_id_cancelada = None

    def _cancelar_lector(self, captura_id, puerto):
        if self.captura_id_cancelada != captura_id:
            puerto.escribir_linea("ENROLL_CANCEL,{}".format(captura_id))
            self.captura_id_cancelada = captura_id
        self.captura_id_armada = None
        self.captura_id_escanendo = None
        self.proximo_armado_captura = 0.0

    def _procesar_estado_enrolamiento(self, linea, puerto):
        """procesa los avisos de captura de la placa ESP32, pide detener las que no son la vigente y avisa al servicio cuando empieza esa lectura"""
        coincidencia = PATRON_ENROLL_STATE.fullmatch(linea)
        if coincidencia is None:
            print("Se ignoró un estado de captura serial mal formado.")
            return
        captura_id, estado = coincidencia.groups()
        if captura_id != self.captura_id_activa:
            puerto.escribir_linea("ENROLL_CANCEL,{}".format(captura_id))
            return
        if estado == "CANCELLED":
            self.captura_id_armada = None
            self.captura_id_escanendo = None
            self.proximo_armado_captura = 0.0
            return

        if self.captura_estado_api == "VISTA_PREVIA":
            self._cancelar_lector(captura_id, puerto)
            return
        self.captura_id_escanendo = captura_id
        if self.captura_estado_api != "ESCANEANDO":
            self._informar_escaneando(captura_id)

    def _informar_escaneando(self, captura_id):
        try:
            self.cliente.informar_escaneando(captura_id)
        except ErrorApi as error:
            if error.estado_http in (404, 409):
                self.proxima_consulta_captura = 0.0
            print("La API aún no confirmó el estado de captura.")
            return False
        self.captura_estado_api = "ESCANEANDO"
        return True

    def _procesar_lectura_enrolamiento(self, linea, puerto):
        """acepta una lectura de la captura vigente y espera la respuesta del servicio antes de aceptar otra"""
        coincidencia = PATRON_ENROLL_READ.fullmatch(linea)
        if coincidencia is None:
            print("Se ignoró una lectura de captura serial mal formada.")
            return
        captura_id, request_id, uid = coincidencia.groups()
        if captura_id != self.captura_id_activa:
            puerto.escribir_linea("ENROLL_CANCEL,{}".format(captura_id))
            return

        solicitud = (captura_id, request_id.upper(), uid.upper())
        if self.lectura_capturada_pendiente is not None:
            if self.lectura_capturada_pendiente != solicitud:
                print("Se ignoró una lectura mientras otra espera confirmación.")
            return
        self.lectura_capturada_pendiente = solicitud
        self.proximo_reintento_captura = 0.0
        self._reenviar_lectura_capturada(puerto)

    def _reenviar_lectura_capturada(self, puerto=None):
        """reintenta ante fallos temporales o respuestas que no confirman el resultado

        deja de reenviarla y vuelve a consultar la captura si recibe 400, 404 o un
        409 que no indique que la tarjeta ya estaba registrada; si sí lo indica,
        pide a la placa ESP32 que lea otra tarjeta
        """
        solicitud = self.lectura_capturada_pendiente
        if solicitud is None or time.monotonic() < self.proximo_reintento_captura:
            return
        try:
            respuesta = self.cliente.enviar_lectura_capturada(*solicitud)
        except ErrorApi as error:
            if error.estado_http in (400, 404, 409):
                self.lectura_capturada_pendiente = None
                self.proxima_consulta_captura = 0.0
                print("La API rechazó la lectura; se conciliará la captura.")
            else:
                self.proximo_reintento_captura = (
                    time.monotonic() + INTERVALO_REINTENTO_CAPTURA
                )
                print("La API no confirmó la lectura; se reintentará.")
            return

        captura_id = solicitud[0]
        tarjeta_registrada = respuesta == {
            "capturaId": captura_id,
            "estado": "ESCANEANDO",
            "resultado": "TARJETA_YA_REGISTRADA",
        }
        vista_lista = respuesta == {
            "capturaId": captura_id,
            "estado": "VISTA_PREVIA",
            "resultado": "PREVIEW_READY",
        }
        if (
            (tarjeta_registrada or vista_lista)
            and captura_id != self.captura_id_activa
            and (puerto is not None or self.captura_id_activa is not None)
        ):
            # Una respuesta tardía no debe cambiar la captura que sustituyó a esta.
            self.lectura_capturada_pendiente = None
            self.proximo_reintento_captura = 0.0
            self.proxima_consulta_captura = 0.0
            return
        if tarjeta_registrada:
            if puerto is None:
                self.proximo_reintento_captura = (
                    time.monotonic() + INTERVALO_REINTENTO_CAPTURA
                )
                print("La lectura repetida se reintentará al reconectar el lector.")
                return
            puerto.escribir_linea(
                "ENROLL_REARM,{},{}".format(captura_id, solicitud[1])
            )
            self.lectura_capturada_pendiente = None
            self.captura_estado_api = "ESCANEANDO"
            self.proxima_consulta_captura = 0.0
            self.proximo_reintento_captura = 0.0
            print("La tarjeta ya estaba registrada; la captura sigue disponible.")
            return
        if not vista_lista:
            self.proximo_reintento_captura = (
                time.monotonic() + INTERVALO_REINTENTO_CAPTURA
            )
            print("La API no confirmó el resultado de la vista previa; se reintentará.")
            return

        self.lectura_capturada_pendiente = None
        self.captura_estado_api = "VISTA_PREVIA"
        self.captura_id_armada = None
        self.captura_id_escanendo = None
        self.proxima_consulta_captura = 0.0
        if puerto is not None:
            self._cancelar_lector(captura_id, puerto)
        print("La vista previa RFID 1 está lista para revisión.")

    def _procesar_lectura(self, linea, puerto):
        """confirma que recibió la lectura, la envía al servicio y comunica el resultado sin autorizar la entrada"""
        try:
            secuencia, uid = analizar_trama_rfid(linea)
        except ErrorProtocolo:
            print("Se ignoró una trama RFID sin secuencia válida.")
            return

        puerto.escribir_linea("ACK,{}".format(secuencia))
        huella = hashlib.sha256(uid.encode("ascii")).digest() if uid else None
        previo = self.pendientes.get(secuencia)
        resultado = "ERROR"
        if uid is not None and (previo is None or previo[0] == huella):
            clave = self.claves.obtener(secuencia, uid)
            try:
                self.cliente.enviar_lectura(int(secuencia, 16), uid, clave)
                resultado = "DENY"
            except Exception:
                resultado = "ERROR"
        elif uid is None:
            resultado = "ERROR"

        if previo is None or previo[0] == huella:
            self.pendientes[secuencia] = (huella, resultado)
            self.pendientes.move_to_end(secuencia)
            if len(self.pendientes) > MAXIMO_RESULTADOS_PENDIENTES:
                self.pendientes.popitem(last=False)
        puerto.escribir_linea("RESULT,{},{}".format(secuencia, resultado))
        if resultado == "DENY":
            print("Lectura {} recibida; resultado serial DENY.".format(secuencia))
        else:
            print("Lectura {} no confirmada; resultado serial ERROR.".format(secuencia))

    def _procesar_confirmacion(self, linea):
        """quita el resultado pendiente solo si el número de lectura y la decisión coinciden con la respuesta recibida de la placa ESP32"""
        coincidencia = PATRON_RESULT_ACK.fullmatch(linea)
        if coincidencia is None:
            print("Se ignoró un RESULT_ACK mal formado.")
            return
        secuencia, resultado = coincidencia.groups()
        secuencia = secuencia.upper()
        esperado = self.pendientes.get(secuencia)
        if esperado is None or esperado[1] != resultado:
            print("RESULT_ACK no coincide con el resultado enviado.")
            return
        del self.pendientes[secuencia]
        print("ESP32 confirmó resultado {} de secuencia {}.".format(
            resultado, secuencia
        ))


def ejecutar(puerto_solicitado, cliente, detener=None):
    """usa el puerto indicado o el único disponible y reintenta si falla al abrirlo o al comunicarse con la placa ESP32"""
    sesion = SesionBridge(cliente)
    while detener is None or not detener.is_set():
        try:
            ruta = seleccionar_puerto(puerto_solicitado)
            with PuertoSerie(ruta) as puerto:
                sesion.ultimo_pong = None
                sesion.pendientes.clear()
                sesion.captura_id_armada = None
                sesion.captura_id_escanendo = None
                sesion.captura_id_cancelada = None
                sesion.estado_lector_rfid1 = None
                sesion.proximo_armado_captura = 0.0
                sesion.proxima_consulta_captura = 0.0
                print("Puerto USB serie abierto en modo exclusivo.")
                sesion.ejecutar(puerto, detener)
        except (OSError, TimeoutError, ErrorProtocolo):
            sesion.estado_dispositivo.actualizar(False)
            if detener is not None and detener.is_set():
                break
            print("USB no disponible; se intentará reconectar en 2 segundos.")
            time.sleep(INTERVALO_RECONEXION)
    sesion.estado_dispositivo.cerrar()
    sesion.capacidad_manual.cerrar()


def _crear_argumentos():
    analizador = argparse.ArgumentParser(
        description="Bridge seguro USB serie para RFID 1."
    )
    analizador.add_argument(
        "--port",
        dest="puerto",
        help="TTY USB explícito; sin esta opción se acepta un único puerto.",
    )
    return analizador


def main():
    argumentos = _crear_argumentos().parse_args()
    url = os.environ.get(
        "SMARTPARKING_RFID1_API_URL", "http://127.0.0.1:8080"
    )
    token = os.environ.get("SMARTPARKING_RFID1_TOKEN")
    try:
        cliente = ClienteCapturas(url, token)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    detener = threading.Event()

    def solicitar_detencion(_senal, _marco):
        detener.set()

    senales = (signal.SIGINT, signal.SIGTERM)
    manejadores_anteriores = {
        senal: signal.signal(senal, solicitar_detencion)
        for senal in senales
    }
    try:
        ejecutar(argumentos.puerto, cliente, detener)
    except KeyboardInterrupt:
        detener.set()
    finally:
        for senal, manejador in manejadores_anteriores.items():
            signal.signal(senal, manejador)
    print("Bridge detenido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
