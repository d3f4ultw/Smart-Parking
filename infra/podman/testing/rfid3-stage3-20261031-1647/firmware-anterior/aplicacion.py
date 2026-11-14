"""Compone el transporte y los lectores RFID del SPI compartido."""

import time

from captura import GestorCaptura
from buzzer import ControladorZumbador
from entrada_rfid2 import GestorEntradaRfid2
from comunicacion.protocolo import Protocolo
from comunicacion.serial import PuertoSerial
from config import (
    PIN_RFID2_RST, PIN_RFID3_RST, PIN_ZUMBADOR_SALIDA, TIEMPO_BUCLE_MS, TIEMPO_UID_ESTABLE_MS,
)
from rfid.bus_spi import BusSPICompartido
from rfid.lector import DetectorLecturaRfid, LectorRFID


def main(registrar_evento=None):
    """Ejecuta los lectores; el callback opcional recibe diagnósticos sin UID."""
    puerto = None
    zumbador = None
    zumbador_salida = None
    protocolo = None
    try:
        puerto = PuertoSerial()
        zumbador = ControladorZumbador()
        zumbador_salida = ControladorZumbador(pin_numero=PIN_ZUMBADOR_SALIDA)
        captura = GestorCaptura(puerto, time.ticks_ms)
        entrada_rfid2 = GestorEntradaRfid2(
            puerto, time.ticks_ms, time.ticks_diff, zumbador=zumbador,
        )
        protocolo = Protocolo(puerto, captura, time.ticks_ms, entrada_rfid2)
        puerto.enviar_linea("READY,1")
        bus_spi = None
        error_bus = None
        try:
            bus_spi = BusSPICompartido()
        except Exception as error:
            error_bus = type(error).__name__

        lector = None
        try:
            if bus_spi is None:
                raise OSError(error_bus or "SPI no disponible")
            lector = LectorRFID(
                protocolo.atender, identificador="RFID1", bus_spi=bus_spi, indice_cs=0,
            )
            protocolo.version_lector = lector.version
            puerto.enviar_linea("RFID_READER,READY,%02X" % lector.version)
            _emitir_evento(registrar_evento, ("RFID1", "ESTADO", "READY"))
            _emitir_evento(registrar_evento, ("RFID1", "VERSION", "%02X" % lector.version))
        except Exception as error:
            protocolo.error_lector = type(error).__name__
            puerto.enviar_linea("RFID_READER,ERROR,{}".format(type(error).__name__))
            _emitir_evento(registrar_evento, ("RFID1", "ESTADO", "ERROR"))

        lector_rfid2 = None
        estado_rfid2 = "ERROR"
        try:
            if bus_spi is None:
                raise OSError(error_bus or "SPI no disponible")
            lector_rfid2 = LectorRFID(
                protocolo.atender, machine_module=None, identificador="RFID2",
                bus_spi=bus_spi, indice_cs=1, pin_rst=PIN_RFID2_RST,
            )
            estado_rfid2 = "READY"
            _emitir_evento(registrar_evento, ("RFID2", "ESTADO", "READY"))
            _emitir_evento(registrar_evento, ("RFID2", "VERSION", "%02X" % lector_rfid2.version))
        except Exception as error:
            lector_rfid2 = None
            _emitir_evento(registrar_evento, ("RFID2", "ESTADO", "ERROR"))

        lector_rfid3 = None
        estado_rfid3 = "ERROR"
        detector_rfid3 = DetectorLecturaRfid("RFID3", time.ticks_diff)
        try:
            if bus_spi is None:
                raise OSError(error_bus or "SPI no disponible")
            lector_rfid3 = LectorRFID(
                protocolo.atender, identificador="RFID3", bus_spi=bus_spi,
                indice_cs=2, pin_rst=PIN_RFID3_RST,
            )
            estado_rfid3 = "READY"
            puerto.enviar_linea("RFID_DIAG,RFID3,READY,%02X" % lector_rfid3.version)
            _emitir_evento(registrar_evento, ("RFID3", "ESTADO", "READY"))
            _emitir_evento(registrar_evento, ("RFID3", "VERSION", "%02X" % lector_rfid3.version))
        except Exception:
            lector_rfid3 = None
            puerto.enviar_linea("RFID_DIAG,RFID3,ERROR")
            _emitir_evento(registrar_evento, ("RFID3", "ESTADO", "ERROR"))

        while not protocolo.detener:
            protocolo.atender()
            ahora = time.ticks_ms()
            captura.actualizar(ahora)
            entrada_rfid2.actualizar(ahora)
            zumbador.actualizar()
            zumbador_salida.actualizar()
            if not protocolo.detener and lector is not None and captura.pendiente is None:
                secuencia_previa = captura.secuencia
                try:
                    uid, presente = lector.leer_uid_estado()
                except Exception:
                    uid, presente = None, None
                captura.procesar_tarjeta(uid, presente, ahora, TIEMPO_UID_ESTABLE_MS)
                if captura.secuencia != secuencia_previa:
                    _emitir_evento(
                        registrar_evento,
                        ("RFID1", "DETECCION", "TARJETA_DETECTADA"),
                    )
            if not protocolo.detener and lector_rfid2 is not None:
                try:
                    _, uid, presente = lector_rfid2.leer_evento()
                    detectada = entrada_rfid2.procesar_tarjeta(
                        uid, presente, ahora, TIEMPO_UID_ESTABLE_MS,
                    )
                    if detectada:
                        _emitir_evento(
                            registrar_evento,
                            ("RFID2", "DETECCION", "TARJETA_DETECTADA"),
                        )
                except Exception as error:
                    entrada_rfid2.procesar_tarjeta(
                        None, None, ahora, TIEMPO_UID_ESTABLE_MS,
                    )
                    if estado_rfid2 != "ERROR":
                        estado_rfid2 = "ERROR"
                        _emitir_evento(
                            registrar_evento, ("RFID2", "ESTADO", "ERROR")
                        )
                else:
                    if estado_rfid2 == "ERROR":
                        estado_rfid2 = "READY"
                        _emitir_evento(
                            registrar_evento, ("RFID2", "ESTADO", "READY")
                        )
            if not protocolo.detener and lector_rfid3 is not None:
                try:
                    _, uid, presente = lector_rfid3.leer_evento()
                    evento = detector_rfid3.actualizar(
                        uid, presente, time.ticks_ms(), TIEMPO_UID_ESTABLE_MS,
                    )
                    if evento is not None and not protocolo.detener:
                        zumbador_salida.programar(1)
                        puerto.enviar_linea("RFID_DIAG,RFID3,DETECCION")
                        _emitir_evento(registrar_evento, evento)
                except Exception:
                    detector_rfid3.actualizar(None, None, time.ticks_ms(), TIEMPO_UID_ESTABLE_MS)
                    if estado_rfid3 != "ERROR":
                        estado_rfid3 = "ERROR"
                        puerto.enviar_linea("RFID_DIAG,RFID3,ERROR")
                        _emitir_evento(registrar_evento, ("RFID3", "ESTADO", "ERROR"))
                else:
                    if estado_rfid3 == "ERROR":
                        estado_rfid3 = "READY"
                        puerto.enviar_linea("RFID_DIAG,RFID3,READY,%02X" % lector_rfid3.version)
                        _emitir_evento(registrar_evento, ("RFID3", "ESTADO", "READY"))
            time.sleep_ms(TIEMPO_BUCLE_MS)
    finally:
        if zumbador_salida is not None:
            zumbador_salida.finalizar()
        if zumbador is not None:
            zumbador.finalizar()
        if puerto is not None:
            if protocolo is not None and protocolo.detener:
                _entrar_mantenimiento(puerto)
            puerto.cerrar()


def _emitir_evento(registrar_evento, evento):
    if registrar_evento is not None:
        try:
            registrar_evento(evento)
        except Exception:
            pass


def _entrar_mantenimiento(puerto):
    try:
        archivo = open("maintenance.flag", "w")
        archivo.write("1\n")
        archivo.close()
        puerto.enviar_linea("STOPPING,REBOOT")
        try:
            puerto.uart.flush()
        except AttributeError:
            time.sleep_ms(50)
        time.sleep_ms(50)
        import machine
        machine.reset()
    except Exception as error:
        puerto.enviar_linea("STOP_ERROR,{}".format(type(error).__name__))
