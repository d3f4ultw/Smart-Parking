"""Retiene una lectura RFID2 hasta recibir la decisión del servidor."""

import os

from captura import formatear_uid
from config import TIEMPO_RETIRO_TARJETA_MS


MAXIMO_ENVIOS = 3
INTERVALO_REINTENTO_MS = 1500


class GestorEntradaRfid2:
    """Envía una sola lectura pendiente y conserva su UUID durante reintentos."""

    def __init__(self, puerto, reloj, diferencia_tiempo, uuid_aleatorio=None,
                 zumbador=None):
        self.puerto = puerto
        self.reloj = reloj
        self.diferencia_tiempo = diferencia_tiempo
        self.uuid_aleatorio = uuid_aleatorio or os.urandom
        self.zumbador = zumbador
        self.pendiente = None
        self.ultimo_uid = None
        self.ultimo_uid_visto = 0
        self.uid_candidato = None
        self.uid_candidato_desde = 0

    def procesar_tarjeta(self, uid, presente, ahora, estable_ms):
        """Estabiliza detecciones y envía una lectura cuando no hay otra pendiente."""
        if presente is False:
            self.uid_candidato = None
            if (self.ultimo_uid is not None and
                    self._transcurrido(ahora, self.ultimo_uid_visto) >= TIEMPO_RETIRO_TARJETA_MS):
                self.ultimo_uid = None
            return False
        if presente is not True:
            self.uid_candidato = None
            return False

        self.ultimo_uid_visto = ahora
        if uid is None or uid == self.ultimo_uid or self.pendiente is not None:
            self.uid_candidato = None
            return False
        if uid != self.uid_candidato:
            self.uid_candidato = uid
            self.uid_candidato_desde = ahora
            return False
        if self._transcurrido(ahora, self.uid_candidato_desde) < estable_ms:
            return False

        self.ultimo_uid = uid
        self.uid_candidato = None
        self.pendiente = {
            "lectura_id": self._nuevo_uuid(),
            "uid": formatear_uid(uid),
            "ultimo_envio": ahora,
            "intentos": 1,
        }
        self._enviar_pendiente()
        return True

    def recibir_resultado(self, lectura_id, resultado):
        """Acepta solo la respuesta correlacionada y programa su patrón una vez."""
        pendiente = self.pendiente
        if pendiente is None or lectura_id != pendiente["lectura_id"]:
            return False
        if resultado not in ("AUTORIZADA", "DENEGADA"):
            return False
        self.pendiente = None
        self._programar_sonido(1 if resultado == "AUTORIZADA" else 2)
        return True

    def actualizar(self, ahora):
        """Reintenta tres veces y señala una sola vez el fallo de comunicación."""
        pendiente = self.pendiente
        if (pendiente is None or self._transcurrido(ahora, pendiente["ultimo_envio"])
                < INTERVALO_REINTENTO_MS):
            return
        if pendiente["intentos"] >= MAXIMO_ENVIOS:
            self.pendiente = None
            self._programar_sonido(2)
            return
        pendiente["ultimo_envio"] = ahora
        pendiente["intentos"] += 1
        self._enviar_pendiente()

    def _programar_sonido(self, cantidad):
        if self.zumbador is not None:
            self.zumbador.programar(cantidad)

    def _enviar_pendiente(self):
        pendiente = self.pendiente
        self.puerto.enviar_linea("RFID2,{},{}".format(
            pendiente["lectura_id"], pendiente["uid"]
        ))

    def _nuevo_uuid(self):
        """Crea UUID v4 con aleatoriedad del sistema disponible en MicroPython."""
        datos = bytearray(self.uuid_aleatorio(16))
        datos[6] = (datos[6] & 0x0F) | 0x40
        datos[8] = (datos[8] & 0x3F) | 0x80
        hexadecimal = "".join("%02x" % byte for byte in datos)
        return "{}-{}-{}-{}-{}".format(
            hexadecimal[:8], hexadecimal[8:12], hexadecimal[12:16],
            hexadecimal[16:20], hexadecimal[20:],
        )

    def _transcurrido(self, ahora, antes):
        return self.diferencia_tiempo(ahora, antes)
