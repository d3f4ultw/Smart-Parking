"""Firmware de prueba persistente para RFID y USB serie en un ESP32."""

import time


PIN_RFID_CS = 5
PIN_RFID_RST = 22
PIN_RFID_SCK = 18
PIN_RFID_MOSI = 23
PIN_RFID_MISO = 19
PIN_ZUMBADOR = 25
VELOCIDAD_SPI = 1000000
VELOCIDAD_USB = 115200
TIEMPO_UID_ESTABLE_MS = 80
TIEMPO_RETIRO_TARJETA_MS = 1000
MAXIMO_INTENTOS_PRESENCIA = 100
MAXIMO_INTENTOS_TRANSCEIVE = 2000

PCD_IDLE = 0x00
PCD_CALC_CRC = 0x03
PCD_TRANSCEIVE = 0x0C
PCD_SOFT_RESET = 0x0F

REG_COMMAND = 0x01
REG_COM_IRQ = 0x04
REG_ERROR = 0x06
REG_FIFO_DATA = 0x09
REG_FIFO_LEVEL = 0x0A
REG_CONTROL = 0x0C
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


def patron_sonoro(decision):
    """Devuelve pares de duración activa y pausa en milisegundos."""
    if decision == "ALLOW":
        return ((80, 0),)
    if decision == "DENY":
        return ((80, 100), (80, 0))
    if decision == "ERROR":
        return ((60, 60), (60, 60), (60, 0))
    raise ValueError("Decisión sonora desconocida.")


class ControladorZumbador:
    """Simula los patrones hasta conocer las especificaciones del módulo."""

    def __init__(self, uart, pin_numero=PIN_ZUMBADOR):
        self.uart = uart
        self.pin_numero = pin_numero

    def indicar(self, decision):
        patron = patron_sonoro(decision)
        mensaje = "SOUND_SIM,{},{},{}\n".format(
            decision, len(patron), self.pin_numero
        )
        self.uart.write(mensaje)


class LectorRC522:
    """Lee UID de 4, 7 o 10 bytes mediante SPI y el protocolo anticollision."""

    def __init__(self):
        from machine import Pin, SPI

        self.cs = Pin(PIN_RFID_CS, Pin.OUT, value=1)
        self.rst = Pin(PIN_RFID_RST, Pin.OUT, value=1)
        self.spi = SPI(
            2,
            baudrate=VELOCIDAD_SPI,
            polarity=0,
            phase=0,
            bits=8,
            firstbit=SPI.MSB,
            sck=Pin(PIN_RFID_SCK),
            mosi=Pin(PIN_RFID_MOSI),
            miso=Pin(PIN_RFID_MISO),
        )

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
        self.cs.value(0)
        try:
            self.spi.write_readinto(tx, rx)
        finally:
            self.cs.value(1)
        return rx[1]

    def _escribir_reg(self, registro, valor):
        direccion = (registro << 1) & 0x7E
        self.cs.value(0)
        try:
            self.spi.write(bytes((direccion, valor & 0xFF)))
        finally:
            self.cs.value(1)

    def _activar_antena(self):
        if (self._leer_reg(REG_TX_CONTROL) & 0x03) != 0x03:
            self._escribir_reg(
                REG_TX_CONTROL, self._leer_reg(REG_TX_CONTROL) | 0x03
            )

    def _calcular_crc(self, datos):
        self._escribir_reg(REG_COMMAND, PCD_IDLE)
        self._escribir_reg(REG_DIV_IRQ, 0x04)
        self._escribir_reg(REG_FIFO_LEVEL, 0x80)
        for valor in datos:
            self._escribir_reg(REG_FIFO_DATA, valor)
        self._escribir_reg(REG_COMMAND, PCD_CALC_CRC)

        for _ in range(255):
            if self._leer_reg(REG_DIV_IRQ) & 0x04:
                return bytes((
                    self._leer_reg(REG_CRC_RESULT_L),
                    self._leer_reg(REG_CRC_RESULT_H),
                ))
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
        limite = (
            MAXIMO_INTENTOS_PRESENCIA
            if informar_presencia else MAXIMO_INTENTOS_TRANSCEIVE
        )
        for _ in range(limite):
            interrupcion = self._leer_reg(REG_COM_IRQ)
            if interrupcion & 0x30:
                recibido = True
                break
            if interrupcion & 0x01:
                break
            time.sleep_ms(1)

        self._escribir_reg(REG_BIT_FRAMING, bits_finales & 0x07)
        errores = self._leer_reg(REG_ERROR) & 0x1B
        if not recibido or errores:
            if informar_presencia:
                # Una colisión o error de lectura no demuestra que el campo
                # esté vacío; solo un timeout limpio confirma ausencia.
                return None, bool(recibido or errores)
            return None

        cantidad = self._leer_reg(REG_FIFO_LEVEL)
        respuesta = bytearray(cantidad)
        for indice in range(cantidad):
            respuesta[indice] = self._leer_reg(REG_FIFO_DATA)
        if informar_presencia:
            return bytes(respuesta), True
        return bytes(respuesta)

    def _anticollision(self, selector):
        respuesta = self._transmitir((selector, 0x20))
        if respuesta is None or len(respuesta) != 5:
            return None

        verificacion = (
            respuesta[0] ^ respuesta[1] ^ respuesta[2] ^ respuesta[3]
        )
        if verificacion != respuesta[4]:
            return None
        return respuesta

    def _seleccionar(self, selector, datos_uid):
        trama = bytes((selector, 0x70)) + datos_uid
        crc = self._calcular_crc(trama)
        if crc is None:
            return None
        respuesta = self._transmitir(trama + crc)
        if respuesta is None or len(respuesta) < 1:
            return None
        return respuesta[0]

    def _detener_tarjeta(self):
        """Pone la PICC seleccionada en HALT antes del siguiente sondeo."""
        trama = bytes((PICC_HLTA, PICC_HLTA_ACK))
        crc = self._calcular_crc(trama)
        if crc is not None:
            # HLTA termina correctamente sin respuesta de la tarjeta.
            self._transmitir(trama + crc)

    def leer_uid(self):
        """Devuelve el UID como bytes o None si no hay tarjeta legible."""
        uid, _ = self.leer_uid_estado()
        return uid

    def leer_uid_estado(self):
        """Devuelve (UID, presencia); errores de anticollision siguen presentes."""
        respuesta, presente = self._transmitir(
            (PICC_WUPA,), 7, informar_presencia=True
        )
        if not presente:
            return None, False
        if respuesta is None or len(respuesta) != 2:
            return None, True

        uid = bytearray()
        selectores = (PICC_SEL_CL1, PICC_SEL_CL2, PICC_SEL_CL3)
        for selector in selectores:
            bloque = self._anticollision(selector)
            if bloque is None:
                return None, True

            sak = self._seleccionar(selector, bloque)
            if sak is None:
                return None, True

            if bloque[0] == BYTE_CASCADE_TAG:
                uid.extend(bloque[1:4])
            else:
                uid.extend(bloque[0:4])

            if not (sak & BIT_CASCADE):
                # SELECT deja la PICC en ACTIVE. La siguiente muestra usa WUPA,
                # por lo que la debemos dejar en HALT primero para poder
                # reactivarla de forma fiable mientras siga en el campo.
                self._detener_tarjeta()
                if len(uid) not in (4, 7, 10):
                    return None, True
                return bytes(uid), True

        return None, True


def _formatear_uid(uid):
    return "".join("%02X" % valor for valor in uid)


def _permitir_lectura_uid(uid, ultimo_uid, enrollment):
    """Permite recapturar la misma tarjeta al iniciar una asociación."""
    return uid != ultimo_uid or (
        enrollment is not None and enrollment.get("state") == "SCANNING"
    )


def _procesar_trama(uart, texto, estado):
    partes = texto.split(",")
    tipo = partes[0]

    if tipo == "PING" and len(partes) == 1:
        uart.write("PONG\n")
        estado["ultimo_ping"] = time.ticks_ms()
        version = estado.get("reader_version")
        if version is not None:
            uart.write("RFID_READER,READY,%02X\n" % version)
        elif estado.get("reader_error") is not None:
            uart.write("RFID_READER,ERROR,{}\n".format(
                estado["reader_error"]
            ))
        return True

    if tipo == "STOP" and len(partes) == 1:
        estado["detener"] = True
        return False

    if tipo == "ENROLL_ARM" and len(partes) == 2:
        identificador = partes[1]
        if (
            len(identificador) == 32
            and all(caracter in "0123456789abcdef" for caracter in identificador)
        ):
            estado["enrollment"] = {
                "session_id": identificador,
                "state": "SCANNING",
            }
            uart.write("ENROLL_STATE,{},SCANNING\n".format(
                identificador
            ))
        return True

    if tipo == "ENROLL_CANCEL" and len(partes) == 2:
        enrollment = estado.get("enrollment")
        if (
            enrollment is not None
            and partes[1] == enrollment["session_id"]
        ):
            uart.write("ENROLL_STATE,{},CANCELLED\n".format(partes[1]))
            estado["enrollment"] = None
        return True

    pendiente = estado["pendiente"]
    if tipo == "ACK" and len(partes) == 2 and pendiente is not None:
        if partes[1] == pendiente["id"]:
            pendiente["ack"] = True
            pendiente["ultimo_envio"] = time.ticks_ms()
        return True

    if tipo == "RESULT" and len(partes) == 3 and pendiente is not None:
        if partes[1] != pendiente["id"]:
            return True
        decision = partes[2]
        if decision in ("ALLOW", "DENY"):
            estado["sonido"].indicar(decision)
            decision_confirmada = decision
        elif decision == "ERROR":
            estado["sonido"].indicar("ERROR")
            decision_confirmada = "ERROR"
        else:
            estado["sonido"].indicar("ERROR")
            decision_confirmada = "ERROR"
        uart.write("RESULT_ACK,{},{}\n".format(
            pendiente["id"], decision_confirmada
        ))
        estado["pendiente"] = None
        return True

    return True


def main():
    """Ejecuta RFID↔USB; main.py lo llama automáticamente en cada arranque."""
    from machine import UART

    uart = None
    estado = {"detener": False}
    lector = None
    try:
        uart = UART(
            1,
            baudrate=VELOCIDAD_USB,
            bits=8,
            parity=None,
            stop=1,
            tx=1,
            rx=3,
            timeout=0,
        )
        estado.update({
            "pendiente": None,
            "ultimo_ping": time.ticks_ms(),
            "sonido": ControladorZumbador(uart),
            "enrollment": None,
            "reader_version": None,
            "reader_error": None,
        })
        uart.write("READY,1\n")
        try:
            lector = LectorRC522()
            estado["reader_version"] = lector.version
            uart.write("RFID_READER,READY,%02X\n" % lector.version)
        except Exception as error:
            estado["reader_error"] = type(error).__name__
            uart.write(
                "RFID_READER,ERROR,{}\n".format(type(error).__name__)
            )

        ultimo_uid = None
        ultimo_uid_visto = 0
        secuencia = 0
        uid_candidato = None
        uid_candidato_desde = 0
        datos_linea = bytearray()

        while not estado["detener"]:
            datos = uart.read()
            if datos:
                for byte in datos:
                    if byte == 10:
                        try:
                            texto = datos_linea.decode().strip()
                        except UnicodeError:
                            texto = ""
                        datos_linea = bytearray()
                        if texto:
                            _procesar_trama(uart, texto, estado)
                    elif byte != 13 and len(datos_linea) < 96:
                        datos_linea.append(byte)
                    elif len(datos_linea) >= 96:
                        datos_linea = bytearray()

            ahora = time.ticks_ms()

            pendiente = estado["pendiente"]
            if pendiente is not None:
                transcurrido = time.ticks_diff(
                    ahora, pendiente["ultimo_envio"]
                )
                limite = 5000 if pendiente["ack"] else 1500
                if transcurrido >= limite:
                    if pendiente["intentos"] < 3:
                        uart.write("RFID,{},{}\n".format(
                            pendiente["id"], pendiente["uid"]
                        ))
                        pendiente["intentos"] += 1
                        pendiente["ultimo_envio"] = ahora
                    else:
                        estado["sonido"].indicar("ERROR")
                        estado["pendiente"] = None

            elif lector is not None:
                try:
                    uid, tarjeta_presente = lector.leer_uid_estado()
                except Exception:
                    uid = None
                    tarjeta_presente = None

                if tarjeta_presente is False:
                    uid_candidato = None
                    if (
                        ultimo_uid is not None
                        and time.ticks_diff(
                            ahora, ultimo_uid_visto
                        ) >= TIEMPO_RETIRO_TARJETA_MS
                    ):
                        ultimo_uid = None
                elif tarjeta_presente is True:
                    ultimo_uid_visto = ahora
                    enrollment = estado.get("enrollment")
                    if uid is None:
                        uid_candidato = None
                    elif not _permitir_lectura_uid(
                        uid, ultimo_uid, enrollment
                    ):
                        uid_candidato = None
                    elif uid_candidato != uid:
                        uid_candidato = uid
                        uid_candidato_desde = ahora
                    elif time.ticks_diff(
                        ahora, uid_candidato_desde
                    ) >= TIEMPO_UID_ESTABLE_MS:
                        ultimo_uid = uid_candidato
                        uid = uid_candidato
                        uid_candidato = None
                        secuencia = (secuencia + 1) & 0xFFFF
                        identificador = "%04X" % secuencia
                        uid_texto = _formatear_uid(uid)
                        uart.write("RFID,{},{}\n".format(
                            identificador, uid_texto
                        ))
                        estado["pendiente"] = {
                            "id": identificador,
                            "uid": uid_texto,
                            "ack": False,
                            "intentos": 1,
                            "ultimo_envio": ahora,
                        }
                        enrollment = estado.get("enrollment")
                        if (
                            enrollment is not None
                            and enrollment["state"] == "SCANNING"
                        ):
                            enrollment["state"] = "CAPTURED"
                            uart.write("ENROLL_READ,{},{},{}\n".format(
                                enrollment["session_id"],
                                identificador,
                                uid_texto,
                            ))
                else:
                    # Un error de lectura nunca confirma que la tarjeta salió.
                    uid_candidato = None
                    enrollment = estado.get("enrollment")
                    if enrollment is not None:
                        enrollment["absence_since"] = None

            time.sleep_ms(20)
    finally:
        if uart is not None and estado["detener"]:
            try:
                archivo = open("maintenance.flag", "w")
                archivo.write("1\n")
                archivo.close()
                uart.write("STOPPING,REBOOT\n")
                try:
                    uart.flush()
                except AttributeError:
                    time.sleep_ms(50)
                time.sleep_ms(50)
                import machine
                machine.reset()
            except Exception as error:
                uart.write("STOP_ERROR,{}\n".format(type(error).__name__))
        if uart is not None:
            uart.deinit()


