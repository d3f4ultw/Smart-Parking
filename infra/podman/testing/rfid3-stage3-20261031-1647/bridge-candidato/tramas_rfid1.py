"""Valida las tramas RFID ordinarias y sus claves de retransmisión."""

import collections
import hashlib
import re
import uuid

from puerto_serie import ErrorProtocolo


MAXIMO_CACHE_IDEMPOTENCIA = 128
PATRON_SECUENCIA = re.compile(r"[0-9A-Fa-f]{1,4}\Z")
PATRON_UID = re.compile(r"(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{14}|[0-9A-Fa-f]{20})\Z")


class CacheClavesLectura:
    """Conserva claves idempotentes para retransmisiones seriales."""

    def __init__(self, tamano=MAXIMO_CACHE_IDEMPOTENCIA):
        self.tamano = tamano
        self.claves = collections.OrderedDict()

    def obtener(self, secuencia, uid):
        huella = hashlib.sha256(uid.encode("ascii")).digest()
        identidad = (secuencia, huella)
        clave = self.claves.get(identidad)
        if clave is not None:
            self.claves.move_to_end(identidad)
            return clave
        clave = str(uuid.uuid4())
        self.claves[identidad] = clave
        if len(self.claves) > self.tamano:
            self.claves.popitem(last=False)
        return clave


def analizar_trama_rfid(linea):
    """Devuelve secuencia normalizada y UID; UID None indica formato inválido."""
    partes = linea.split(",")
    if len(partes) < 2 or partes[0] != "RFID":
        raise ErrorProtocolo("La trama RFID no contiene una secuencia.")
    secuencia = partes[1]
    if PATRON_SECUENCIA.fullmatch(secuencia) is None:
        raise ErrorProtocolo("La secuencia RFID no es válida.")
    secuencia = secuencia.upper()
    if len(partes) != 3 or PATRON_UID.fullmatch(partes[2]) is None:
        return secuencia, None
    return secuencia, partes[2].upper()
