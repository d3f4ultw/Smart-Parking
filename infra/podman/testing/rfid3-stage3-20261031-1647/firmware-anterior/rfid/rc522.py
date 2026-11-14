"""Controlador SPI de MFRC522, anticollision y selección de tarjetas."""

import time

from config import (
    INTERVALO_SERVICIO_SPI, MAXIMO_INTENTOS_PRESENCIA,
    MAXIMO_INTENTOS_TRANSCEIVE, PIN_RFID_CS, PIN_RFID_RST,
)
from rfid.bus_spi import BusSPICompartido

PCD_IDLE = 0x00
PCD_CALC_CRC = 0x03
PCD_TRANSCEIVE = 0x0C
PCD_SOFT_RESET = 0x0F
REG_COMMAND = 0x01
REG_COM_IRQ = 0x04
REG_ERROR = 0x06
REG_FIFO_DATA = 0x09
REG_FIFO_LEVEL = 0x0A
REG_BIT_FRAMING = 0x0D
REG_MODE = 0x11
REG_TX_CONTROL = 0x14
REG_TX_ASK = 0x15
REG_DIV_IRQ = 0x05
REG_CRC_RESULT_H = 0x21
REG_CRC_RESULT_L = 0x22
REG_T_MODE = 0x2A
REG_T_PRESCALER = 0x2B
REG_T_RELOAD_H = 0x2C
REG_T_RELOAD_L = 0x2D
PICC_WUPA = 0x52
PICC_HLTA = 0x50
PICC_HLTA_ACK = 0x00
PICC_SEL_CL1 = 0x93
PICC_SEL_CL2 = 0x95
PICC_SEL_CL3 = 0x97
BIT_CASCADE = 0x04
BYTE_CASCADE_TAG = 0x88


class LectorRC522:
    """Lee UID de 4, 7 o 10 bytes y atiende UART durante espera SPI."""

    def __init__(
        self, atender_serial=None, machine_module=None, bus_spi=None,
        indice_cs=0, pin_cs=None, pin_rst=None,
    ):
        if machine_module is None:
            import machine as machine_module
        self.atender_serial = atender_serial
        pin = machine_module.Pin
        if bus_spi is None:
            bus_spi = BusSPICompartido(
                machine_module, (PIN_RFID_CS if pin_cs is None else pin_cs,)
            )
        self.bus_spi = bus_spi
        self.cs = bus_spi.obtener_cs(indice_cs)
        self.spi = bus_spi.spi
        self.rst = pin(PIN_RFID_RST if pin_rst is None else pin_rst, pin.OUT, value=1)
        self.rst.value(0)
        time.sleep_ms(10)
        self.rst.value(1)
        time.sleep_ms(50)
        self._escribir_reg(REG_COMMAND, PCD_SOFT_RESET)
        time.sleep_ms(50)
        self._escribir_reg(REG_T_MODE, 0x8D)
        self._escribir_reg(REG_T_PRESCALER, 0x3E)
        self._escribir_reg(REG_T_RELOAD_L, 30)
        self._escribir_reg(REG_T_RELOAD_H, 0)
        self._escribir_reg(REG_TX_ASK, 0x40)
        self._escribir_reg(REG_MODE, 0x3D)
        self._activar_antena()
        self.version = self._leer_reg(0x37)
        if self.version in (0x00, 0xFF):
            raise OSError("MFRC522 no responde por SPI.")

    def _leer_reg(self, registro):
        direccion = ((registro << 1) & 0x7E) | 0x80
        tx = bytearray((direccion, 0x00))
        rx = bytearray(2)
        self.bus_spi.seleccionar(self.cs)
        try:
            self.spi.write_readinto(tx, rx)
        finally:
            self.bus_spi.liberar()
        return rx[1]

    def _escribir_reg(self, registro, valor):
        direccion = (registro << 1) & 0x7E
        self.bus_spi.seleccionar(self.cs)
        try:
            self.spi.write(bytes((direccion, valor & 0xFF)))
        finally:
            self.bus_spi.liberar()

    def _activar_antena(self):
        if self._leer_reg(REG_TX_CONTROL) & 0x03 != 0x03:
            self._escribir_reg(REG_TX_CONTROL, self._leer_reg(REG_TX_CONTROL) | 0x03)

    def _calcular_crc(self, datos):
        self._escribir_reg(REG_COMMAND, PCD_IDLE)
        self._escribir_reg(REG_DIV_IRQ, 0x04)
        self._escribir_reg(REG_FIFO_LEVEL, 0x80)
        for valor in datos:
            self._escribir_reg(REG_FIFO_DATA, valor)
        self._escribir_reg(REG_COMMAND, PCD_CALC_CRC)
        for intento in range(255):
            if intento % INTERVALO_SERVICIO_SPI == 0:
                self._servir_uart()
            if self._leer_reg(REG_DIV_IRQ) & 0x04:
                return bytes((self._leer_reg(REG_CRC_RESULT_L), self._leer_reg(REG_CRC_RESULT_H)))
            time.sleep_ms(1)
        return None

    def _transmitir(self, datos, bits_finales=0, informar_presencia=False):
        self._escribir_reg(REG_COMMAND, PCD_IDLE)
        self._escribir_reg(REG_COM_IRQ, 0x7F)
        self._escribir_reg(REG_FIFO_LEVEL, 0x80)
        for valor in datos:
            self._escribir_reg(REG_FIFO_DATA, valor)
        self._escribir_reg(REG_BIT_FRAMING, bits_finales & 0x07)
        self._escribir_reg(REG_COMMAND, PCD_TRANSCEIVE)
        self._escribir_reg(REG_BIT_FRAMING, (bits_finales & 0x07) | 0x80)
        recibido = False
        expiracion_rc522 = False
        limite = MAXIMO_INTENTOS_PRESENCIA if informar_presencia else MAXIMO_INTENTOS_TRANSCEIVE
        for intento in range(limite):
            if intento % INTERVALO_SERVICIO_SPI == 0:
                self._servir_uart()
            interrupcion = self._leer_reg(REG_COM_IRQ)
            if interrupcion & 0x30:
                recibido = True
                break
            if interrupcion & 0x01:
                expiracion_rc522 = True
                break
            time.sleep_ms(1)
        self._escribir_reg(REG_BIT_FRAMING, bits_finales & 0x07)
        errores = self._leer_reg(REG_ERROR) & 0x1B
        if not recibido or errores:
            if informar_presencia and not (recibido or errores or expiracion_rc522):
                return None, None
            return (None, bool(recibido or errores)) if informar_presencia else None
        cantidad = self._leer_reg(REG_FIFO_LEVEL)
        respuesta = bytearray(cantidad)
        for indice in range(cantidad):
            respuesta[indice] = self._leer_reg(REG_FIFO_DATA)
        return (bytes(respuesta), True) if informar_presencia else bytes(respuesta)

    def _anticollision(self, selector):
        respuesta = self._transmitir((selector, 0x20))
        if respuesta is None or len(respuesta) != 5:
            return None
        if respuesta[0] ^ respuesta[1] ^ respuesta[2] ^ respuesta[3] != respuesta[4]:
            return None
        return respuesta

    def _seleccionar(self, selector, datos_uid):
        trama = bytes((selector, 0x70)) + datos_uid
        crc = self._calcular_crc(trama)
        if crc is None:
            return None
        respuesta = self._transmitir(trama + crc)
        return respuesta[0] if respuesta and len(respuesta) >= 1 else None

    def _detener_tarjeta(self):
        trama = bytes((PICC_HLTA, PICC_HLTA_ACK))
        crc = self._calcular_crc(trama)
        if crc is not None:
            self._transmitir(trama + crc)

    def leer_uid(self):
        uid, _ = self.leer_uid_estado()
        return uid

    def leer_uid_estado(self):
        respuesta, presente = self._transmitir((PICC_WUPA,), 7, True)
        if presente is not True:
            return None, presente
        if respuesta is None or len(respuesta) != 2:
            return None, True
        uid = bytearray()
        for selector in (PICC_SEL_CL1, PICC_SEL_CL2, PICC_SEL_CL3):
            bloque = self._anticollision(selector)
            if bloque is None:
                return None, True
            sak = self._seleccionar(selector, bloque)
            if sak is None:
                return None, True
            uid.extend(bloque[1:4] if bloque[0] == BYTE_CASCADE_TAG else bloque[0:4])
            if not sak & BIT_CASCADE:
                self._detener_tarjeta()
                return (bytes(uid), True) if len(uid) in (4, 7, 10) else (None, True)
        return None, True

    def _servir_uart(self):
        if self.atender_serial is not None:
            self.atender_serial()
