"""consulta al servicio las solicitudes de salida RFID 3 y devuelve una decisión a la placa ESP32; si la respuesta tarda demasiado, deniega la salida"""

import hashlib
import queue
import re
import threading
import time
import uuid

from cliente_smartparking import ErrorApi, PATRON_UID


PATRON_TRAMA = re.compile(
    r"RFID3,([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}),(.*)\Z"
)
RETENCION_TERMINAL = 15.0
LIMITE_DECISION = 3.5
MAXIMO_DECISIONES = 64


class GestorSalidaRfid3:
    """guarda por poco tiempo las respuestas y consulta una salida a la vez"""

    def __init__(self, cliente, capacidad=MAXIMO_DECISIONES, reloj=time.monotonic):
        self.cliente = cliente
        self.capacidad = capacidad
        self.reloj = reloj
        self.decisiones = {}
        self.en_curso = None
        self.completados = queue.Queue(maxsize=1)
        self.rechazar_hasta = 0.0

    def recibir(self, linea, puerto):
        """si la placa ESP32 repite una solicitud, reutiliza la consulta en curso o la decisión guardada"""
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
            # Si no cabe otra respuesta, se rechazan solicitudes nuevas durante este plazo para no consultar dos veces una repetida.
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
        """envía la decisión a la placa ESP32 y niega la salida si el servicio no responde en tres segundos y medio"""
        ahora = self.reloj()
        for lectura_id, entrada in tuple(self.decisiones.items()):
            if entrada["resultado"] is None and ahora - entrada["inicio"] >= LIMITE_DECISION:
                self._terminar(lectura_id, "DENEGADA", puerto, ahora)
        try:
            lectura_id, resultado, origen, duracion_ms = self.completados.get_nowait()
        except queue.Empty:
            self._retirar_vencidas(ahora)
            return
        self.en_curso = None
        entrada = self.decisiones.get(lectura_id)
        if entrada is not None and entrada["resultado"] is None:
            self._terminar(lectura_id, resultado, puerto, ahora)
            if origen == "API":
                print("RFID3: API confirmó {} en {} ms.".format(resultado, duracion_ms))
            elif origen == "COMUNICACION":
                print("RFID3: sin respuesta API (timeout/comunicación); cierre seguro en {} ms."
                      .format(duracion_ms))
            elif origen.startswith("HTTP_"):
                print("RFID3: {} sin decisión confirmada; cierre seguro en {} ms."
                      .format(origen.replace("_", " ", 1), duracion_ms))
            else:
                print("RFID3: sin decisión API confirmada ({}); cierre seguro en {} ms."
                      .format(origen.lower(), duracion_ms))
        elif origen == "API":
            print("RFID3: respuesta API tardía descartada; se conserva el cierre seguro.")
        self._retirar_vencidas(ahora)

    def _solicitar(self, lectura_id, uid):
        """pide al servicio la decisión de salida y deja el resultado listo para enviarlo a la placa ESP32"""
        inicio = time.monotonic()
        origen = "API"
        try:
            resultado = self.cliente.registrar_salida_rfid3(uid, lectura_id)
            if resultado not in ("AUTORIZADA", "DENEGADA"):
                resultado = "DENEGADA"
                origen = "RESPUESTA_INVALIDA"
        except ErrorApi as error:
            # Si se pierde la comunicación, no se sabe si el servicio alcanzó a guardar la salida.
            resultado = "DENEGADA"
            origen = error.origen or (
                "HTTP_{}".format(error.estado_http)
                if error.estado_http is not None else "RESPUESTA_INVALIDA"
            )
        except Exception:
            resultado = "DENEGADA"
            origen = "ERROR_INTERNO"
        duracion_ms = round((time.monotonic() - inicio) * 1000)
        self.completados.put((lectura_id, resultado, origen, duracion_ms))

    def _terminar(self, lectura_id, resultado, puerto, ahora):
        """guarda la decisión durante unos segundos para atender una repetición y la envía a la placa ESP32"""
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
