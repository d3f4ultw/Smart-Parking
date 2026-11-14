"""Permite intercambiar mensajes entre la placa y el equipo conectado."""

from config import MAXIMO_LINEA_SERIAL, UART_ID, UART_RX, UART_TX, VELOCIDAD_USB

MAXIMO_TRAMAS_PENDIENTES = 16
MAXIMO_INTENTOS_SIN_AVANCE = 4


class PuertoSerial:
    """Administra la conexión y entrega mensajes sin detener las demás tareas."""

    def __init__(self, uart=None):
        if uart is None:
            from machine import UART
            uart = UART(
                UART_ID, baudrate=VELOCIDAD_USB, bits=8, parity=None, stop=1,
                tx=UART_TX, rx=UART_RX, timeout=0,
            )
        self.uart = uart
        self._linea = bytearray()
        self._descartando = False
        self._retorno_carro = False
        self._salida = []
        self._sincronizacion = None

    def leer_lineas(self):
        """Recibe mensajes completos y descarta los largos o con caracteres no admitidos."""
        datos = self.uart.read()
        if not datos:
            return ()
        lineas = []
        for byte in datos:
            if byte == 10:
                texto = ""
                if not self._descartando:
                    try:
                        texto = self._linea.decode("ascii")
                    except UnicodeError:
                        pass
                self._linea = bytearray()
                self._descartando = False
                self._retorno_carro = False
                if texto:
                    lineas.append(texto)
            elif self._descartando:
                continue
            elif self._retorno_carro:
                self._linea = bytearray()
                self._descartando = True
            elif byte == 13:
                self._retorno_carro = True
            elif len(self._linea) < MAXIMO_LINEA_SERIAL:
                self._linea.append(byte)
            else:
                self._linea = bytearray()
                self._descartando = True
        return lineas

    def enviar_linea(self, texto):
        """Intenta enviar el mensaje si su tamaño y caracteres están permitidos."""
        if (not isinstance(texto, str) or len(texto) > MAXIMO_LINEA_SERIAL
                or "\n" in texto or "\r" in texto
                or len(self._salida) >= MAXIMO_TRAMAS_PENDIENTES):
            return False
        try:
            texto.encode("ascii")
        except UnicodeError:
            return False
        self._salida.append({"texto": texto, "trama": texto + "\n", "offset": 0, "esperas": 0})
        self.atender_salida()
        return True

    def cancelar_linea(self, texto):
        """Retira el mensaje y prepara un aviso si quedó una parte enviada sin completar."""
        if self._salida and self._salida[0]["texto"] == texto and self._salida[0]["offset"]:
            self._sincronizacion = "!\n"
        self._salida = [trama for trama in self._salida if trama["texto"] != texto]

    def atender_salida(self):
        """Envía lo que falta de un mensaje sin mezclarlo con otros ni detener la placa."""
        if self._sincronizacion is not None:
            try:
                escritos = self.uart.write(self._sincronizacion)
            except OSError:
                escritos = None
            if isinstance(escritos, int) and 0 < escritos <= len(self._sincronizacion):
                self._sincronizacion = self._sincronizacion[escritos:] or None
            elif escritos is None:
                # Si se envió parte del aviso, repetirlo no causa problemas.
                self._sincronizacion = "!\n"
            return
        if not self._salida:
            return
        actual = self._salida[0]
        restante = actual["trama"][actual["offset"]:]
        try:
            escritos = self.uart.write(restante)
        except OSError:
            escritos = None
        if isinstance(escritos, int) and 0 < escritos <= len(restante):
            actual["offset"] += escritos
            actual["esperas"] = 0
            if actual["offset"] == len(actual["trama"]):
                self._salida.pop(0)
        elif escritos == 0:
            actual["esperas"] += 1
            if actual["esperas"] >= MAXIMO_INTENTOS_SIN_AVANCE:
                self._salida.pop(0)
                if actual["offset"]:
                    self._sincronizacion = "!\n"
        else:
            # Si no se sabe qué parte llegó, se marca el mensaje como incompleto.
            self._salida.pop(0)
            self._sincronizacion = "!\n"

    def cerrar(self):
        """Cierra la conexión cuando termina el programa de la placa."""
        self.uart.deinit()
