"""comprueba los mensajes RFID y mantiene el mismo identificador cuando se repiten"""

import collections
import hashlib
import re
import uuid

from puerto_serie import ErrorProtocolo


MAXIMO_CACHE_IDEMPOTENCIA = 128
PATRON_SECUENCIA = re.compile(r"[0-9A-Fa-f]{1,4}\Z")
PATRON_UID = re.compile(r"(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{14}|[0-9A-Fa-f]{20})\Z")


class CacheClavesLectura:
    """recuerda un número limitado de lecturas para reconocer las repetidas y conservar su mismo identificador"""

    def __init__(self, tamano=MAXIMO_CACHE_IDEMPOTENCIA):
        self.tamano = tamano
        self.claves = collections.OrderedDict()

    def obtener(self, secuencia, uid):
        """reutiliza la clave de una lectura repetida y, al llenarse, olvida la que lleva más tiempo sin usarse"""
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
    """comprueba el número de lectura y devuelve ese número con el código de la tarjeta en mayúsculas; si el código no es válido, conserva el número y deja sin valor el código de la tarjeta"""
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
