"""Organiza una salida manual y confirma el resultado de la orden de la barrera."""

import os
try:
    from hashlib import sha256
except ImportError:
    try:
        from uhashlib import sha256
    except ImportError:
        sha256 = None


VENTANA_TICKET_MS = 5000
MAXIMO_OPERACIONES = 16
ALFABETO = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
ARCHIVO_CLAVE = "/salida_manual.key"


def _base64url(datos):
    """Convierte los datos en texto que puede usarse en direcciones."""
    resultado = ""
    valor = 0
    bits = 0
    for byte in datos:
        valor = (valor << 8) | byte
        bits += 8
        while bits >= 6:
            bits -= 6
            resultado += ALFABETO[(valor >> bits) & 63]
            valor &= (1 << bits) - 1
    if bits:
        resultado += ALFABETO[(valor << (6 - bits)) & 63]
    return resultado


def _token(aleatorio):
    datos = aleatorio(16)
    if len(datos) != 16:
        raise ValueError("Aleatoriedad insuficiente.")
    return _base64url(datos)


def _token_valido(token):
    return (isinstance(token, str) and len(token) == 22 and token[-1] in "AQgw"
            and all(caracter in ALFABETO for caracter in token))


def _firma(clave, accion, operacion, boot_id, ticket, resultado=None):
    """Crea una firma con la clave para comprobar una orden o su respuesta."""
    texto = "smartparking.manual.v1|{}|{}|{}|{}".format(
        accion, operacion, boot_id, ticket
    )
    if resultado is not None:
        texto += "|" + resultado
    return _hmac(clave, texto)


def _hmac(clave, texto):
    interior = bytes((clave[i] if i < len(clave) else 0) ^ 0x36 for i in range(64))
    exterior = bytes((clave[i] if i < len(clave) else 0) ^ 0x5c for i in range(64))
    return _base64url(sha256(exterior + sha256(interior + texto.encode("ascii")).digest()).digest()[:12])


def _firma_igual(esperada, recibida):
    if not isinstance(recibida, str) or len(recibida) != len(esperada):
        return False
    diferencia = 0
    for posicion in range(len(esperada)):
        diferencia |= ord(esperada[posicion]) ^ ord(recibida[posicion])
    return diferencia == 0


def _leer_clave():
    try:
        with open(ARCHIVO_CLAVE, "rb") as archivo:
            clave = archivo.read(33)
    except OSError:
        return None
    return clave if len(clave) == 32 else None


class GestorSalidaManual:
    """Atiende cada permiso una sola vez y recuerda los resultados recientes."""

    def __init__(self, puerto, servo, salida_rfid3, reloj, diferencia_tiempo,
                 aleatorio=None, clave=None):
        self.puerto = puerto
        self.servo = servo
        self.salida_rfid3 = salida_rfid3
        self.reloj = reloj
        self.diferencia_tiempo = diferencia_tiempo
        self.aleatorio = aleatorio or getattr(os, "urandom", None)
        self.clave = clave if isinstance(clave, bytes) and len(clave) == 32 else _leer_clave()
        if sha256 is None:
            self.clave = None
        try:
            self.boot_id = _token(self.aleatorio)
        except Exception:
            # Sin identificar este encendido no se puede autorizar una salida con seguridad.
            self.boot_id = None
        self.operaciones = {}
        self.orden = []
        self.activa = None
        self.fallo_pwm = False

    def bloqueada(self):
        """Indica si hay una salida manual en curso o un fallo que impide usar el lector."""
        self.actualizar(self.reloj())
        return self.activa is not None or self.fallo_pwm

    def sondear(self, desafio):
        """Responde a una consulta de seguridad sin reservar ni mover la barrera."""
        if (self.clave is None or self.boot_id is None or not _token_valido(desafio)
                or self.servo is None or self.fallo_pwm or getattr(self.servo, "pwm", True) is None):
            return
        try:
            firma = _hmac(self.clave, "smartparking.manual.v1|PROBE|{}|{}".format(
                self.boot_id, desafio
            ))
        except Exception:
            return
        self.puerto.enviar_linea("SM_PROBE_OK,{},{},{}".format(desafio, self.boot_id, firma))

    def preparar(self, operacion):
        """Reserva la barrera sin abrirla ni alargar el plazo si repiten la solicitud."""
        if not _token_valido(operacion) or self.boot_id is None or self.clave is None:
            return
        self.actualizar(self.reloj())
        anterior = self.operaciones.get(operacion)
        if anterior is not None:
            if anterior["estado"] == "PREPARADA":
                self._lista(operacion, anterior)
            elif anterior["estado"] in ("EJECUTADA", "NO_EJECUTADA"):
                self._resultado(operacion, anterior["estado"])
            return
        if (self.activa is not None or self.fallo_pwm or self.servo is None
                or self.servo.abierto or self.salida_rfid3.pendiente is not None):
            self.puerto.enviar_linea("SM_OCUPADA,{},{}".format(operacion, self.boot_id))
            return
        if len(self.orden) >= MAXIMO_OPERACIONES:
            descartable = None
            for anterior_id in self.orden:
                if self.operaciones[anterior_id]["estado"] in ("EJECUTADA", "NO_EJECUTADA"):
                    descartable = anterior_id
                    break
            if descartable is None:
                return
            self.orden.remove(descartable)
            del self.operaciones[descartable]
        try:
            ticket = _token(self.aleatorio)
        except Exception:
            return
        entrada = {"estado": "PREPARADA", "ticket": ticket, "inicio": self.reloj()}
        self.operaciones[operacion] = entrada
        self.orden.append(operacion)
        self.activa = operacion
        self._lista(operacion, entrada)

    def ejecutar(self, operacion, boot_id, ticket, firma):
        """Comprueba el permiso y lo usa una sola vez antes de ordenar la apertura."""
        if (self.clave is None or boot_id != self.boot_id
                or not _token_valido(operacion) or not _token_valido(ticket)):
            return
        try:
            esperada = _firma(self.clave, "EXEC", operacion, boot_id, ticket)
        except Exception:
            return
        if not _firma_igual(esperada, firma):
            return
        self.actualizar(self.reloj())
        entrada = self.operaciones.get(operacion)
        if entrada is None or ticket != entrada["ticket"]:
            return
        if entrada["estado"] in ("EJECUTADA", "NO_EJECUTADA"):
            self._resultado(operacion, entrada["estado"])
            return
        if entrada["estado"] != "PREPARADA" or self.activa != operacion:
            return
        entrada["estado"] = "EJECUTANDO"
        try:
            self.servo.abrir()
            if self.servo.abierto is not True:
                raise OSError("No se confirmó el inicio del ciclo PWM.")
        except Exception:
            # Puede ocurrir un fallo después de enviar la orden de movimiento.
            entrada["estado"] = "INCIERTA"
            self.fallo_pwm = True
            self.activa = None

    def consultar(self, operacion, boot_id):
        """Envía el resultado final, si se conoce y corresponde al último encendido."""
        if self.clave is None or boot_id != self.boot_id or not _token_valido(operacion):
            return
        self.actualizar(self.reloj())
        entrada = self.operaciones.get(operacion)
        if entrada is not None and entrada["estado"] in ("EJECUTADA", "NO_EJECUTADA"):
            self._resultado(operacion, entrada["estado"])

    def actualizar(self, ahora):
        """Cancela reservas vencidas y registra cuando el control deja de mantener abierta la barrera.

        No comprueba físicamente la posición de la barrera.
        """
        if self.activa is None:
            return
        operacion = self.activa
        entrada = self.operaciones[operacion]
        if (entrada["estado"] == "PREPARADA"
                and self.diferencia_tiempo(ahora, entrada["inicio"]) >= VENTANA_TICKET_MS):
            entrada["estado"] = "NO_EJECUTADA"
            self.activa = None
            self._resultado(operacion, entrada["estado"])
        elif entrada["estado"] == "EJECUTANDO" and not self.servo.abierto:
            # Ya se envió la orden de cierre y el control no informó un fallo.
            entrada["estado"] = "EJECUTADA"
            self.activa = None
            self._resultado(operacion, entrada["estado"])

    def _lista(self, operacion, entrada):
        self.puerto.enviar_linea("SM_LISTA,{},{},{}".format(
            operacion, self.boot_id, entrada["ticket"]
        ))

    def _resultado(self, operacion, resultado):
        ticket = self.operaciones[operacion]["ticket"]
        codigo = "E" if resultado == "EJECUTADA" else "N"
        try:
            firma = _firma(self.clave, "RESULT", operacion, self.boot_id, ticket, codigo)
        except Exception:
            return
        self.puerto.enviar_linea("SM_RES,{},{},{},{},{}".format(
            operacion, self.boot_id, ticket, codigo, firma
        ))
