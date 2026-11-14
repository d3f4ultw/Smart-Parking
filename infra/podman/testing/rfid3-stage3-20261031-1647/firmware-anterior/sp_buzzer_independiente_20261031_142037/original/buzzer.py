"""Controla un buzzer activo o pasivo sin bloquear el loop del ESP32."""

from machine import Pin, PWM
from time import ticks_add, ticks_diff, ticks_ms
from config import PIN_ZUMBADOR


MODO_ZUMBADOR = "activo"
DURACION_PITIDO_MS = 150
PAUSA_PITIDOS_MS = 100
FRECUENCIA_ZUMBADOR_HZ = 2000
CICLO_ZUMBADOR_U16 = 32768


class ControladorZumbador:
    """Programa patrones cortos; el loop llama a actualizar() con frecuencia."""

    def __init__(self, modo=MODO_ZUMBADOR):
        if modo not in ("activo", "pasivo"):
            raise ValueError("El modo debe ser activo o pasivo")

        self.modo = modo
        self.pin = Pin(PIN_ZUMBADOR, Pin.OUT, value=0)
        self.pwm = None
        if modo == "pasivo":
            self.pwm = PWM(self.pin, freq=FRECUENCIA_ZUMBADOR_HZ, duty_u16=0)

        self.pitidos_restantes = 0
        self.fase = "inactivo"
        self.limite_ms = 0
        self.desactivar()

    def programar(self, cantidad):
        """Inicia un patrón de uno o dos pitidos si el buzzer está libre."""
        if cantidad not in (1, 2) or self.fase != "inactivo":
            return False

        self.pitidos_restantes = cantidad
        self._iniciar_pitido(ticks_ms())
        return True

    def actualizar(self):
        """Avanza el patrón sin esperas; retorna True mientras esté ocupado."""
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
                self.fase = "inactivo"
            return self.fase != "inactivo"

        self._iniciar_pitido(ahora_ms)
        return True

    def desactivar(self):
        """Deja la salida inactiva, incluso al cancelar un patrón."""
        if self.pwm is None:
            self.pin.value(0)
        else:
            self.pwm.duty_u16(0)

    def finalizar(self):
        """Apaga la salida y libera PWM cuando el firmware lo permite."""
        self.desactivar()
        self.fase = "inactivo"
        self.pitidos_restantes = 0
        if self.pwm is not None:
            self.pwm.deinit()
            self.pwm = None

    def _iniciar_pitido(self, ahora_ms):
        if self.pwm is None:
            self.pin.value(1)
        else:
            self.pwm.duty_u16(CICLO_ZUMBADOR_U16)
        self.fase = "sonando"
        self.limite_ms = ticks_add(ahora_ms, DURACION_PITIDO_MS)
