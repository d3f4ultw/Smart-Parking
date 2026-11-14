"""Correlaciona salidas RFID 3 sin delegar el puerto serial al trabajo HTTP."""

import hashlib
import queue
import re
import threading
import time
import uuid

from cliente_smartparking import PATRON_UID


PATRON_TRAMA = re.compile(
    r"RFID3,([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}),(.*)\Z"
)
RETENCION_TERMINAL = 15.0
LIMITE_DECISION = 3.5
MAXIMO_DECISIONES = 64


class GestorSalidaRfid3:
    """Mantiene decisiones volátiles y un único trabajo HTTP acotado en vuelo."""

    def __init__(self, cliente, capacidad=MAXIMO_DECISIONES, reloj=time.monotonic):
        self.cliente = cliente
        self.capacidad = capacidad
        self.reloj = reloj
        self.decisiones = {}
        self.en_curso = None
        self.completados = queue.Queue(maxsize=1)
        self.rechazar_hasta = 0.0

    def recibir(self, linea, puerto):
        """Acepta una trama completa; las duplicadas nunca crean otro trabajo."""
        coincidencia = PATRON_TRAMA.fullmatch(linea)
        if coincidencia is None:
            return
        lectura_id = str(uuid.UUID(coincidencia.group(1)))
        uid = coincidencia.group(2)
        valido = PATRON_UID.fullmatch(uid) is not None
        uid = uid.upper()
        huella = hashlib.sha256(uid.encode("ascii")).digest() if valido else None
        ahora = self.reloj()
        self._retirar_vencidas(ahora)
        previo = self.decisiones.get(lectura_id)
        if previo is not None:
            if previo["resultado"] is not None:
                previo["vence"] = ahora + RETENCION_TERMINAL
            if previo["huella"] != huella:
                if previo["resultado"] is None:
                    self._terminar(lectura_id, "DENEGADA", puerto, ahora)
                else:
                    self._responder(puerto, lectura_id, "DENEGADA")
            elif previo["resultado"] is not None:
                self._responder(puerto, lectura_id, previo["resultado"])
            return

        if ahora < self.rechazar_hasta or len(self.decisiones) >= self.capacidad:
            # Sin espacio para recordar un rechazo, bloquear nuevas UUID durante
            # toda la ventana evita reenviar una retransmisión ya denegada.
            self.rechazar_hasta = ahora + RETENCION_TERMINAL
            self._responder(puerto, lectura_id, "DENEGADA")
            return

        self.decisiones[lectura_id] = {
            "huella": huella, "resultado": None,
            "inicio": ahora, "vence": None,
        }
        if not valido or self.en_curso is not None:
            self._terminar(lectura_id, "DENEGADA", puerto, ahora)
            return
        self.en_curso = lectura_id
        threading.Thread(target=self._solicitar, args=(lectura_id, uid), daemon=True).start()

    def atender(self, puerto):
        """Solo el bucle serial emite respuestas y resuelve plazos vencidos."""
        ahora = self.reloj()
        for lectura_id, entrada in tuple(self.decisiones.items()):
            if entrada["resultado"] is None and ahora - entrada["inicio"] >= LIMITE_DECISION:
                self._terminar(lectura_id, "DENEGADA", puerto, ahora)
        try:
            lectura_id, resultado = self.completados.get_nowait()
        except queue.Empty:
            self._retirar_vencidas(ahora)
            return
        self.en_curso = None
        entrada = self.decisiones.get(lectura_id)
        if entrada is not None and entrada["resultado"] is None:
            self._terminar(lectura_id, resultado, puerto, ahora)
        self._retirar_vencidas(ahora)

    def _solicitar(self, lectura_id, uid):
        try:
            resultado = self.cliente.registrar_salida_rfid3(uid, lectura_id)
            if resultado not in ("AUTORIZADA", "DENEGADA"):
                resultado = "DENEGADA"
        except Exception:
            # Un fallo de comunicación no establece si la base confirmó o no.
            resultado = "DENEGADA"
        self.completados.put((lectura_id, resultado))

    def _terminar(self, lectura_id, resultado, puerto, ahora):
        entrada = self.decisiones[lectura_id]
        entrada["resultado"] = resultado
        entrada["vence"] = ahora + RETENCION_TERMINAL
        self._responder(puerto, lectura_id, resultado)

    def _retirar_vencidas(self, ahora):
        for lectura_id, entrada in tuple(self.decisiones.items()):
            if entrada["vence"] is not None and ahora >= entrada["vence"]:
                del self.decisiones[lectura_id]

    @staticmethod
    def _responder(puerto, lectura_id, resultado):
        puerto.escribir_linea("RFID3_RESULT,{},{}".format(lectura_id, resultado))
