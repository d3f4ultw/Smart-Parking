"""Recibe lecturas de tarjetas y ayuda a registrar una tarjeta nueva."""

from config import TIEMPO_RETIRO_TARJETA_MS


def formatear_uid(uid):
    return "".join("%02X" % valor for valor in uid)


def permitir_lectura_uid(uid, ultimo_uid, enrolamiento):
    if enrolamiento is not None and enrolamiento.get("state") == "CAPTURED":
        return False
    return uid != ultimo_uid or (
        enrolamiento is not None and enrolamiento.get("state") == "SCANNING"
    )


class ControladorZumbador:
    """Envía un aviso escrito que indica el sonido correspondiente a cada resultado."""

    def __init__(self, puerto, pin_numero=25):
        self.puerto = puerto
        self.pin_numero = pin_numero

    def indicar(self, decision):
        patrones = {"ALLOW": 1, "DENY": 2, "ERROR": 3}
        if decision not in patrones:
            raise ValueError("Decisión sonora desconocida.")
        self.puerto.enviar_linea(
            "SOUND_SIM,{},{},{}".format(decision, patrones[decision], self.pin_numero)
        )


class GestorCaptura:
    """Mantiene una lectura pendiente y organiza el registro de una tarjeta nueva."""

    def __init__(self, puerto, reloj, sonido=None):
        self.puerto = puerto
        self.reloj = reloj
        self.sonido = sonido or ControladorZumbador(puerto)
        self.pendiente = None
        self.enrolamiento = None
        self.ultimo_uid = None
        self.ultimo_uid_visto = 0
        self.secuencia = 0
        self.uid_candidato = None
        self.uid_candidato_desde = 0
        self.bloqueo_captura_exitosa = False

    def iniciar_enrolamiento(self, identificador):
        """Prepara el lector para registrar una tarjeta y avisa que está listo."""
        if len(identificador) != 32 or any(
            caracter not in "0123456789abcdef" for caracter in identificador
        ):
            return
        if self.enrolamiento and self.enrolamiento["session_id"] == identificador:
            return
        self.enrolamiento = {"session_id": identificador, "state": "SCANNING"}
        self.bloqueo_captura_exitosa = False
        self.puerto.enviar_linea("ENROLL_STATE,{},SCANNING".format(identificador))

    def cancelar_enrolamiento(self, identificador):
        if self.enrolamiento and self.enrolamiento["session_id"] == identificador:
            self.puerto.enviar_linea("ENROLL_STATE,{},CANCELLED".format(identificador))
            self.enrolamiento = None

    def rearmar_rechazo(self, identificador, request_id):
        """Permite leer otra tarjeta si el rechazo corresponde a la lectura actual."""
        enrolamiento = self.enrolamiento
        if (
            enrolamiento is None
            or enrolamiento["session_id"] != identificador
            or enrolamiento.get("state") != "CAPTURED"
            or enrolamiento.get("request_id") != request_id.upper()
            or self.pendiente is not None
        ):
            return
        enrolamiento["state"] = "REJECTED"
        self.bloqueo_captura_exitosa = False
        self.uid_candidato = None

    def confirmar(self, identificador):
        """Anota que recibieron la lectura para ajustar el tiempo de espera."""
        pendiente = self.pendiente
        if pendiente is not None and identificador == pendiente["id"]:
            pendiente["ack"] = True
            pendiente["ultimo_envio"] = self.reloj()

    def resultado(self, identificador, decision):
        """Termina la lectura pendiente, avisa su resultado y confirma que llegó."""
        pendiente = self.pendiente
        if pendiente is None or identificador != pendiente["id"]:
            return
        confirmada = decision if decision in ("ALLOW", "DENY", "ERROR") else "ERROR"
        self.sonido.indicar(confirmada)
        self.puerto.enviar_linea(
            "RESULT_ACK,{},{}".format(pendiente["id"], confirmada)
        )
        self.pendiente = None

    def actualizar(self, ahora):
        """Vuelve a enviar la lectura si hace falta y avisa cuando se agotan los intentos."""
        if self.pendiente is None:
            return
        pendiente = self.pendiente
        limite = 5000 if pendiente["ack"] else 1500
        if self._transcurrido(ahora, pendiente["ultimo_envio"]) < limite:
            return
        if pendiente["intentos"] < 3:
            self._enviar_pendiente(pendiente, ahora)
        else:
            self.sonido.indicar("ERROR")
            self.pendiente = None

    def procesar_tarjeta(self, uid, presente, ahora, estable_ms):
        """Espera una lectura constante y evita otra captura mientras se confirma el registro."""
        if self.bloqueo_captura_exitosa:
            self.uid_candidato = None
            return
        if presente is False:
            self.uid_candidato = None
            if (self.ultimo_uid is not None and
                    self._transcurrido(ahora, self.ultimo_uid_visto) >= TIEMPO_RETIRO_TARJETA_MS):
                self.ultimo_uid = None
            return
        if presente is not True:
            self.uid_candidato = None
            return
        self.ultimo_uid_visto = ahora
        if uid is None or not permitir_lectura_uid(uid, self.ultimo_uid, self.enrolamiento):
            self.uid_candidato = None
            return
        if uid != self.uid_candidato:
            self.uid_candidato = uid
            self.uid_candidato_desde = ahora
            return
        if self._transcurrido(ahora, self.uid_candidato_desde) < estable_ms:
            return
        self._registrar(uid, ahora)

    def _registrar(self, uid, ahora):
        """Envía la lectura con su código y la usa para el registro cuando corresponde."""
        self.ultimo_uid = uid
        self.uid_candidato = None
        self.secuencia = (self.secuencia + 1) & 0xFFFF
        identificador = "%04X" % self.secuencia
        uid_texto = formatear_uid(uid)
        self.pendiente = {
            "id": identificador, "uid": uid_texto, "ack": False,
            "intentos": 1, "ultimo_envio": ahora,
        }
        self._enviar_pendiente(self.pendiente, ahora, inicial=True)
        if self.enrolamiento and self.enrolamiento["state"] in ("SCANNING", "REJECTED"):
            self.enrolamiento["state"] = "CAPTURED"
            self.enrolamiento["request_id"] = identificador
            self.bloqueo_captura_exitosa = True
            self.puerto.enviar_linea("ENROLL_READ,{},{},{}".format(
                self.enrolamiento["session_id"], identificador, uid_texto
            ))

    def _enviar_pendiente(self, pendiente, ahora, inicial=False):
        if not inicial:
            pendiente["intentos"] += 1
            pendiente["ultimo_envio"] = ahora
        self.puerto.enviar_linea("RFID,{},{}".format(
            pendiente["id"], pendiente["uid"]
        ))

    def _transcurrido(self, ahora, antes):
        from time import ticks_diff
        return ticks_diff(ahora, antes)
