"""Gestiona una lectura de salida, sin accionar elementos físicos."""

import os

from captura import formatear_uid
from config import TIEMPO_RETIRO_TARJETA_MS
from entrada_rfid2 import generar_uuid_v4
from rfid.lector import DetectorLecturaRfid


MAXIMO_ENVIOS = 3
INTERVALO_REINTENTO_MS = 1500
VENTANA_LECTURA_MS = MAXIMO_ENVIOS * INTERVALO_REINTENTO_MS


class GestorSalidaRfid3:
    """Mantiene un UUID por presentación y solo acepta decisiones correlacionadas."""

    def __init__(self, puerto, reloj, diferencia_tiempo, uuid_aleatorio=None):
        self.puerto = puerto
        self.reloj = reloj
        self.diferencia_tiempo = diferencia_tiempo
        self.uuid_aleatorio = uuid_aleatorio or getattr(os, "urandom", None)
        self.detector = DetectorLecturaRfid("RFID3", diferencia_tiempo)
        self.pendiente = None
        self.ultimo_resultado = None
        self.presentacion_bloqueada = False
        self.ausencia_bloqueo_desde = None
        self.ultima_ausencia_bloqueo = None

    def procesar_tarjeta(self, uid, presente, ahora, estable_ms):
        """Detecta una presentación y descarta las observadas durante otra lectura."""
        anterior = self.detector.ultimo_uid
        if (self.pendiente is not None and presente is True and uid is not None
                and (uid != self.pendiente["uid_original"] or anterior is None)):
            self.presentacion_bloqueada = True
        evento = self.detector.actualizar(uid, presente, ahora, estable_ms)
        self._observar_retiro_bloqueado(presente, ahora)
        if evento is not None and self.pendiente is None and not self.presentacion_bloqueada:
            self._iniciar(uid, ahora)
        return evento

    def _observar_retiro_bloqueado(self, presente, ahora):
        if not self.presentacion_bloqueada:
            return
        if presente is not False:
            self.ausencia_bloqueo_desde = None
            self.ultima_ausencia_bloqueo = None
            return
        if (self.ausencia_bloqueo_desde is None or
                self.diferencia_tiempo(ahora, self.ultima_ausencia_bloqueo) >= TIEMPO_RETIRO_TARJETA_MS):
            self.ausencia_bloqueo_desde = ahora
        self.ultima_ausencia_bloqueo = ahora
        if self.diferencia_tiempo(ahora, self.ausencia_bloqueo_desde) >= TIEMPO_RETIRO_TARJETA_MS:
            self.presentacion_bloqueada = False
            self.ausencia_bloqueo_desde = None
            self.ultima_ausencia_bloqueo = None

    def recibir_resultado(self, lectura_id, resultado):
        """Acepta solo una decisión vigente para esta lectura y este lector."""
        self.actualizar(self.reloj())
        pendiente = self.pendiente
        if (pendiente is None or lectura_id != pendiente["lectura_id"]
                or resultado not in ("AUTORIZADA", "DENEGADA")):
            return False
        self._terminar(resultado)
        return True

    def actualizar(self, ahora):
        pendiente = self.pendiente
        if pendiente is None:
            return
        if self.diferencia_tiempo(ahora, pendiente["inicio"]) >= VENTANA_LECTURA_MS:
            self._terminar("DENEGADA")
            return
        if (pendiente["intentos"] < MAXIMO_ENVIOS and
                self.diferencia_tiempo(ahora, pendiente["ultimo_envio"]) >= INTERVALO_REINTENTO_MS):
            pendiente["intentos"] += 1
            pendiente["ultimo_envio"] = ahora
            self.puerto.enviar_linea(pendiente["trama"])

    def _iniciar(self, uid, ahora):
        try:
            lectura_id = generar_uuid_v4(self.uuid_aleatorio)
            trama = "RFID3,{},{}".format(lectura_id, formatear_uid(uid))
        except Exception:
            self.ultimo_resultado = "DENEGADA"
            return
        self.ultimo_resultado = None
        self.pendiente = {
            "lectura_id": lectura_id, "uid_original": uid, "trama": trama,
            "inicio": ahora, "ultimo_envio": ahora, "intentos": 1,
        }
        self.puerto.enviar_linea(trama)

    def _terminar(self, resultado):
        pendiente = self.pendiente
        cancelar = getattr(self.puerto, "cancelar_linea", None)
        if cancelar is not None:
            cancelar(pendiente["trama"])
        self.pendiente = None
        self.ultimo_resultado = resultado
