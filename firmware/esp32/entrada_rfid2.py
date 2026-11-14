"""Consulta si una tarjeta puede entrar y espera la respuesta del servidor."""

import os

from captura import formatear_uid
from config import TIEMPO_RETIRO_RFID2_RFID3_MS


MAXIMO_ENVIOS = 3
INTERVALO_REINTENTO_MS = 1500


def generar_uuid_v4(aleatorio):
    """Crea un código aleatorio para distinguir cada lectura de tarjeta."""
    datos = bytearray(aleatorio(16))
    if len(datos) != 16:
        raise ValueError("No se obtuvo aleatoriedad suficiente.")
    datos[6] = (datos[6] & 0x0F) | 0x40
    datos[8] = (datos[8] & 0x3F) | 0x80
    hexadecimal = "".join("%02x" % byte for byte in datos)
    return "{}-{}-{}-{}-{}".format(
        hexadecimal[:8], hexadecimal[8:12], hexadecimal[12:16],
        hexadecimal[16:20], hexadecimal[20:],
    )


class GestorEntradaRfid2:
    """Envía una lectura a la vez y conserva su código para reconocer la respuesta."""

    def __init__(self, puerto, reloj, diferencia_tiempo, uuid_aleatorio=None,
                 zumbador=None, servo=None):
        self.puerto = puerto
        self.reloj = reloj
        self.diferencia_tiempo = diferencia_tiempo
        self.uuid_aleatorio = uuid_aleatorio or getattr(os, "urandom", None)
        self.zumbador = zumbador
        self.servo = servo
        self.pendiente = None
        self.ultimo_uid = None
        self.ultimo_uid_visto = 0
        self.uid_candidato = None
        self.uid_candidato_desde = 0

    def procesar_tarjeta(self, uid, presente, ahora, estable_ms):
        """Espera una lectura constante y la envía cuando no hay otra pendiente."""
        if presente is False:
            self.uid_candidato = None
            if (self.ultimo_uid is not None and
                    self._transcurrido(ahora, self.ultimo_uid_visto)
                    >= TIEMPO_RETIRO_RFID2_RFID3_MS):
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
        """Acepta la respuesta de esta lectura y avisa el resultado una sola vez.

        Ordena abrir la barrera únicamente cuando se autoriza la entrada.
        """
        self.actualizar(self.reloj())
        pendiente = self.pendiente
        if pendiente is None or lectura_id != pendiente["lectura_id"]:
            return False
        if resultado not in ("AUTORIZADA", "DENEGADA"):
            return False
        self.pendiente = None
        self._programar_sonido(1 if resultado == "AUTORIZADA" else 2)
        if resultado == "AUTORIZADA" and self.servo is not None:
            self.servo.abrir()
        return True

    def actualizar(self, ahora):
        """Envía la lectura hasta tres veces y avisa si no llega una respuesta."""
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
        """Envía el número de tarjeta con el código que identifica la lectura."""
        pendiente = self.pendiente
        self.puerto.enviar_linea("RFID2,{},{}".format(
            pendiente["lectura_id"], pendiente["uid"]
        ))

    def _nuevo_uuid(self):
        """Pide al sistema un código aleatorio para distinguir esta lectura."""
        return generar_uuid_v4(self.uuid_aleatorio)

    def _transcurrido(self, ahora, antes):
        return self.diferencia_tiempo(ahora, antes)
