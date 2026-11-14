"""Adaptador de alto nivel para el lector MFRC522."""

import time

from config import PIN_RFID_RST, TIEMPO_RETIRO_TARJETA_MS
from rfid.bus_spi import BusSPICompartido
from rfid.rc522 import LectorRC522


class LectorRFID:
    """Expone lecturas de UID y presencia sin poseer UART ni captura."""

    def __init__(
        self, atender_serial=None, machine_module=None, identificador="RFID1",
        bus_spi=None, indice_cs=0, pin_rst=None,
    ):
        self.identificador = identificador
        self.controlador = LectorRC522(
            atender_serial, machine_module, bus_spi, indice_cs,
            pin_rst=PIN_RFID_RST if pin_rst is None else pin_rst,
        )
        self.version = self.controlador.version

    def leer_uid_estado(self):
        return self.controlador.leer_uid_estado()

    def leer_evento(self):
        """Devuelve la identidad del lector junto con el resultado local de lectura."""
        uid, presente = self.leer_uid_estado()
        return self.identificador, uid, presente

    def leer_uid(self):
        return self.controlador.leer_uid()


class DetectorLecturaRfid:
    """Suprime duplicados de un lector y genera eventos internos sin publicarlos."""

    def __init__(self, identificador, diferencia_tiempo=None):
        self.identificador = identificador
        self.diferencia_tiempo = diferencia_tiempo or getattr(time, "ticks_diff", None)
        self.ultimo_uid = None
        self.ultimo_uid_visto = 0
        self.uid_candidato = None
        self.uid_candidato_desde = 0

    def actualizar(self, uid, presente, ahora, estable_ms, retiro_ms=TIEMPO_RETIRO_TARJETA_MS):
        if presente is False:
            self.uid_candidato = None
            retiro_confirmado = (
                self.ultimo_uid is not None
                and self._transcurrido(ahora, self.ultimo_uid_visto) >= retiro_ms
            )
            if retiro_confirmado:
                self.ultimo_uid = None
            return None
        if presente is not True:
            self.uid_candidato = None
            return None
        self.ultimo_uid_visto = ahora
        if uid is None or uid == self.ultimo_uid:
            self.uid_candidato = None
            return None
        if uid != self.uid_candidato:
            self.uid_candidato = uid
            self.uid_candidato_desde = ahora
            return None
        if self._transcurrido(ahora, self.uid_candidato_desde) < estable_ms:
            return None
        self.ultimo_uid = uid
        self.uid_candidato = None
        return self.identificador, "DETECCION", "TARJETA_DETECTADA"

    def _transcurrido(self, ahora, antes):
        if self.diferencia_tiempo is not None:
            return self.diferencia_tiempo(ahora, antes)
        return ahora - antes
