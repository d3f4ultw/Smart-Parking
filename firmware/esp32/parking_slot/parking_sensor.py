from machine import Pin


class ParkingSensor:
    """Representa un sensor físico asociado a un cajón."""

    def __init__(self, cajon_id, gpio_pin):
        self.cajon_id = cajon_id
        self._pin = Pin(gpio_pin, Pin.IN)

    def is_occupied(self):
        """Devuelve si el pin activo en bajo detecta ocupación."""
        return self._pin.value() == 0
