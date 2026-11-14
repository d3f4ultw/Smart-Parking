"""Controla la barrera y ordena su cierre después del tiempo previsto."""

from machine import Pin, PWM


FRECUENCIA_SERVO_HZ = 50
PERIODO_SERVO_US = 1000000 // FRECUENCIA_SERVO_HZ
PULSO_MINIMO_SERVO_US = 1000
PULSO_MAXIMO_SERVO_US = 2000
PULSO_MINIMO_CALIBRADO_US = 800
ANGULO_MAXIMO_SERVO = 180
MAXIMO_CICLO_PWM_U16 = 65535


class ControladorServo:
    """Ordena abrir o cerrar la barrera mientras las demás tareas continúan."""

    def __init__(self, pin_numero, angulo_cerrado, angulo_abierto,
                 duracion_abierta_ms, reloj, diferencia_tiempo,
                 pulso_abierto_us=None):
        if not 0 <= angulo_cerrado <= ANGULO_MAXIMO_SERVO:
            raise ValueError("El ángulo cerrado debe estar entre 0 y 180 grados.")
        if not 0 <= angulo_abierto <= ANGULO_MAXIMO_SERVO:
            raise ValueError("El ángulo abierto debe estar entre 0 y 180 grados.")
        if duracion_abierta_ms <= 0:
            raise ValueError("La duración abierta debe ser positiva.")
        if pulso_abierto_us is not None and not (
            PULSO_MINIMO_CALIBRADO_US <= pulso_abierto_us <= PULSO_MAXIMO_SERVO_US
        ):
            raise ValueError("El pulso calibrado de apertura está fuera de rango.")

        self.angulo_cerrado = angulo_cerrado
        self.angulo_abierto = angulo_abierto
        self.pulso_abierto_us = pulso_abierto_us
        self.duracion_abierta_ms = duracion_abierta_ms
        self.reloj = reloj
        self.diferencia_tiempo = diferencia_tiempo
        self.pwm = PWM(
            Pin(pin_numero), freq=FRECUENCIA_SERVO_HZ,
            duty_u16=self._ciclo_pwm(self.angulo_cerrado),
        )
        self.abierto = False
        self.inicio_apertura = None

    def abrir(self):
        """Ordena abrir la barrera y comienza de nuevo el tiempo de apertura."""
        if self.pulso_abierto_us is None:
            ciclo = self._ciclo_pwm(self.angulo_abierto)
        else:
            ciclo = self._ciclo_pulso(self.pulso_abierto_us)
        self.pwm.duty_u16(ciclo)
        self.inicio_apertura = self.reloj()
        self.abierto = True

    def cerrar(self):
        """Ordena cerrar la barrera y cancela el tiempo de apertura."""
        if self.pwm is not None:
            self.pwm.duty_u16(self._ciclo_pwm(self.angulo_cerrado))
        self.abierto = False
        self.inicio_apertura = None

    def actualizar(self, ahora):
        """Ordena el cierre cuando termina el tiempo de apertura."""
        if not self.abierto:
            return False
        if self.diferencia_tiempo(ahora, self.inicio_apertura) < self.duracion_abierta_ms:
            return True
        self.cerrar()
        return False

    def finalizar(self):
        """Ordena cerrar la barrera e intenta liberar el control del motor."""
        if self.pwm is not None:
            self.cerrar()
            self.pwm.deinit()
            self.pwm = None

    def _ciclo_pwm(self, angulo):
        """Calcula la señal para colocar la barrera en el ángulo indicado."""
        ancho_pulso_us = PULSO_MINIMO_SERVO_US + (
            (PULSO_MAXIMO_SERVO_US - PULSO_MINIMO_SERVO_US) * angulo
            // ANGULO_MAXIMO_SERVO
        )
        return self._ciclo_pulso(ancho_pulso_us)

    def _ciclo_pulso(self, ancho_pulso_us):
        """Convierte la duración de la señal para que la placa pueda enviarla al motor."""
        return (
            ancho_pulso_us * MAXIMO_CICLO_PWM_U16 + PERIODO_SERVO_US // 2
        ) // PERIODO_SERVO_US
