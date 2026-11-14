"""Doble SPI RC522 para simular tarjetas PICC de 4, 7 y 10 bytes."""


class PinPICC:
    OUT = 1
    instancias = []

    def __init__(self, numero, modo=None, value=None):
        self.numero = numero
        self.modo = modo
        self.nivel = value
        PinPICC.instancias.append(self)

    def value(self, nuevo=None):
        if nuevo is not None:
            self.nivel = nuevo
        return self.nivel


class SPIPICC:
    """Emula registros, CRC y transacciones PICC de WUPA/select."""

    MSB = 0
    tarjetas = {}
    demora_irq = 0
    instancias = []

    def __init__(self, *args, **kwargs):
        pines_cs = [pin for pin in PinPICC.instancias if pin.numero in (5, 26, 33)]
        if any(pin.value() != 1 for pin in pines_cs):
            raise AssertionError("Los CS deben estar inactivos antes de iniciar SPI.")
        self.registros = {0x37: 0x92, 0x14: 0}
        self.fifo_tx = []
        self.fifo_rx = []
        self.irq = 0
        self.espera_irq = 0
        self.operaciones = []
        self.tramas_transmitidas = []
        SPIPICC.instancias.append(self)

    def _leer_cs(self):
        activos = [
            pin for pin in PinPICC.instancias
            if pin.numero in (5, 26, 33) and pin.value() == 0
        ]
        if len(activos) != 1:
            raise AssertionError("SPI PICC requiere un CS activo exactamente.")
        return activos[0].numero

    def write(self, datos):
        cs = self._leer_cs()
        registro = (datos[0] >> 1) & 0x3F
        valor = datos[1]
        self.operaciones.append(("W", cs, registro, valor))
        if registro == 0x0A and valor & 0x80:
            self.fifo_tx = []
            self.fifo_rx = []
        elif registro == 0x09:
            self.fifo_tx.append(valor)
        else:
            self.registros[registro] = valor
        if registro == 0x01 and valor == 0x03:
            self.registros[0x05] = 0x04
        if registro == 0x01 and valor == 0x0C:
            self._preparar_respuesta(cs)

    def _preparar_respuesta(self, cs):
        solicitud = bytes(self.fifo_tx)
        self.tramas_transmitidas.append((cs, solicitud))
        uid = self.tarjetas.get(cs)
        if not uid:
            self.fifo_rx = []
            self.irq = 0x01
            return
        if solicitud[:1] == b"\x52":
            respuesta = bytes((0x04, 0x00))
        elif solicitud[:1] in (b"\x93", b"\x95", b"\x97") and solicitud[1:2] == b"\x20":
            respuesta = self._bloque(uid, solicitud[0])
        elif solicitud[:1] in (b"\x93", b"\x95", b"\x97") and solicitud[1:2] == b"\x70":
            respuesta = bytes((self._sak(uid, solicitud[0]),))
        else:
            respuesta = b""
        self.fifo_rx = list(respuesta)
        self.irq = 0x30 if respuesta else 0x01
        self.espera_irq = self.demora_irq

    @staticmethod
    def _bcc(datos):
        resultado = 0
        for valor in datos:
            resultado ^= valor
        return resultado

    @classmethod
    def _bloque(cls, uid, selector):
        nivel = {0x93: 1, 0x95: 2, 0x97: 3}[selector]
        if len(uid) == 4:
            contenido = uid if nivel == 1 else bytes((0, 0, 0, 0))
        elif nivel < 3 and (nivel == 1 or len(uid) == 10):
            inicio = (nivel - 1) * 3
            contenido = bytes((0x88,)) + uid[inicio:inicio + 3]
        else:
            inicio = 3 if nivel == 2 else 6
            contenido = uid[inicio:inicio + 4]
        return contenido + bytes((cls._bcc(contenido),))

    @staticmethod
    def _sak(uid, selector):
        if len(uid) == 4:
            return 0
        if selector == 0x93:
            return 0x04
        if selector == 0x95 and len(uid) == 10:
            return 0x04
        return 0

    def write_readinto(self, tx, rx):
        cs = self._leer_cs()
        registro = ((tx[0] & 0x7E) >> 1) & 0x3F
        self.operaciones.append(("R", cs, registro))
        if registro == 0x04:
            if self.espera_irq:
                self.espera_irq -= 1
                rx[1] = 0
            else:
                rx[1] = self.irq
        elif registro == 0x05:
            rx[1] = self.registros.get(0x05, 0)
        elif registro == 0x21:
            rx[1] = 0x12
        elif registro == 0x22:
            rx[1] = 0x34
        elif registro == 0x0A:
            rx[1] = len(self.fifo_rx)
        elif registro == 0x09:
            rx[1] = self.fifo_rx.pop(0) if self.fifo_rx else 0
        else:
            rx[1] = self.registros.get(registro, 0)


class MachinePICC:
    Pin = PinPICC
    SPI = SPIPICC
