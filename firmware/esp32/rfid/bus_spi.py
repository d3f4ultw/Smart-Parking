"""Organiza la conexión que comparten los lectores de tarjetas."""

from config import PIN_RFID_CS, PIN_RFID2_CS, PIN_RFID3_CS, PIN_RFID_MISO, PIN_RFID_MOSI
from config import PIN_RFID_SCK, VELOCIDAD_SPI


class BusSPICompartido:
    """Permite que varios lectores compartan la conexión sin usarla al mismo tiempo."""

    def __init__(self, machine_module=None, pines_cs=(PIN_RFID_CS, PIN_RFID2_CS, PIN_RFID3_CS)):
        if machine_module is None:
            import machine as machine_module
        pin = machine_module.Pin
        self.cs = [pin(numero, pin.OUT, value=1) for numero in pines_cs]
        spi_clase = machine_module.SPI
        self.spi = spi_clase(
            2, baudrate=VELOCIDAD_SPI, polarity=0, phase=0, bits=8,
            firstbit=spi_clase.MSB, sck=pin(PIN_RFID_SCK),
            mosi=pin(PIN_RFID_MOSI), miso=pin(PIN_RFID_MISO),
        )
        self.seleccionado = None

    def obtener_cs(self, indice):
        return self.cs[indice]

    def seleccionar(self, chip_select):
        """Elige qué lector usará la conexión y evita que otro la use al mismo tiempo."""
        if self.seleccionado is not None:
            raise OSError("Ya hay un lector seleccionado en SPI.")
        if not any(chip_select is cs for cs in self.cs):
            raise ValueError("El CS no pertenece al bus SPI compartido.")
        for cs in self.cs:
            cs.value(1)
        chip_select.value(0)
        self.seleccionado = chip_select

    def liberar(self):
        """Deja libre la conexión para que otro lector pueda usarla."""
        for cs in self.cs:
            cs.value(1)
        self.seleccionado = None
