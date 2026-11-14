"""Transporte UART1 con framing ASCII acotado."""

from config import MAXIMO_LINEA_SERIAL, UART_ID, UART_RX, UART_TX, VELOCIDAD_USB


class PuertoSerial:
    """Posee UART1 y entrega líneas sin bloquear el ciclo del dispositivo."""

    def __init__(self, uart=None):
        if uart is None:
            from machine import UART
            uart = UART(
                UART_ID, baudrate=VELOCIDAD_USB, bits=8, parity=None, stop=1,
                tx=UART_TX, rx=UART_RX, timeout=0,
            )
        self.uart = uart
        self._linea = bytearray()

    def leer_lineas(self):
        datos = self.uart.read()
        if not datos:
            return ()
        lineas = []
        for byte in datos:
            if byte == 10:
                try:
                    texto = self._linea.decode().strip()
                except UnicodeError:
                    texto = ""
                self._linea = bytearray()
                if texto:
                    lineas.append(texto)
            elif byte != 13 and len(self._linea) < MAXIMO_LINEA_SERIAL:
                self._linea.append(byte)
            elif len(self._linea) >= MAXIMO_LINEA_SERIAL:
                self._linea = bytearray()
        return lineas

    def enviar_linea(self, texto):
        self.uart.write(texto + "\n")

    def cerrar(self):
        self.uart.deinit()
