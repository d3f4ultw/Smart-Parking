"""Hace sonar los avisos sin detener las demás tareas de la placa."""

from machine import Pin, PWM
from time import ticks_add, ticks_diff, ticks_ms
from config import PIN_ZUMBADOR


MODO_ZUMBADOR = "activo"
DURACION_PITIDO_MS = 150
PAUSA_PITIDOS_MS = 100
PAUSA_PATRONES_MS = 300
MAXIMO_PATRONES_ESPERA = 8
FRECUENCIA_ZUMBADOR_HZ = 2000
CICLO_ZUMBADOR_U16 = 32768


class ControladorZumbador:
    """Prepara los sonidos y deja que las demás tareas continúen mientras suenan."""

    def __init__(self, modo=MODO_ZUMBADOR, pin_numero=PIN_ZUMBADOR,
                 duracion_pitido_ms=DURACION_PITIDO_MS):
        if modo not in ("activo", "pasivo"):
            raise ValueError("El modo debe ser activo o pasivo")
        if duracion_pitido_ms <= 0:
            raise ValueError("La duración del pitido debe ser positiva")

        self.modo = modo
        self.duracion_pitido_ms = duracion_pitido_ms
        self.pin = Pin(pin_numero, Pin.OUT, value=0)
        self.pwm = None
        if modo == "pasivo":
            self.pwm = PWM(self.pin, freq=FRECUENCIA_ZUMBADOR_HZ, duty_u16=0)

        self.pitidos_restantes = 0
        self.patrones_pendientes = []
        self.fase = "inactivo"
        self.limite_ms = 0
        self.desactivar()

    def programar(self, cantidad):
        """Inicia el sonido o lo deja pendiente si ya hay otro; rechaza si no hay espacio."""
        if cantidad not in (1, 2):
            return False
        if self.fase != "inactivo":
            if len(self.patrones_pendientes) >= MAXIMO_PATRONES_ESPERA:
                return False
            self.patrones_pendientes.append(cantidad)
        else:
            self.pitidos_restantes = cantidad
            self._iniciar_pitido(ticks_ms())
        return True

    def actualizar(self):
        """Continúa el aviso e indica si sigue en curso, incluidas las pausas."""
        if self.fase == "inactivo":
            return False

        ahora_ms = ticks_ms()
        if ticks_diff(ahora_ms, self.limite_ms) < 0:
            return True

        if self.fase == "sonando":
            self.desactivar()
            self.pitidos_restantes -= 1
            if self.pitidos_restantes:
                self.fase = "pausa"
                self.limite_ms = ticks_add(ahora_ms, PAUSA_PITIDOS_MS)
            else:
                # Separa los patrones para no confundir dos detecciones con una denegación.
                self.fase = "separacion"
                self.limite_ms = ticks_add(ahora_ms, PAUSA_PATRONES_MS)
            return True

        if self.fase == "separacion":
            if not self.patrones_pendientes:
                self.fase = "inactivo"
                return False
            self.pitidos_restantes = self.patrones_pendientes.pop(0)
        self._iniciar_pitido(ahora_ms)
        return True

    def desactivar(self):
        """Apaga el sonido sin borrar los avisos pendientes."""
        if self.pwm is None:
            self.pin.value(0)
        else:
            self.pwm.duty_u16(0)

    def finalizar(self):
        """Apaga el sonido, descarta los avisos pendientes y libera el control utilizado."""
        self.desactivar()
        self.fase = "inactivo"
        self.pitidos_restantes = 0
        self.patrones_pendientes = []
        if self.pwm is not None:
            self.pwm.deinit()
            self.pwm = None

    def _iniciar_pitido(self, ahora_ms):
        if self.pwm is None:
            self.pin.value(1)
        else:
            self.pwm.duty_u16(CICLO_ZUMBADOR_U16)
        self.fase = "sonando"
        self.limite_ms = ticks_add(ahora_ms, self.duracion_pitido_ms)
