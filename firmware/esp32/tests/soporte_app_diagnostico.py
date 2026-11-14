"""Pruebas de callbacks de diagnóstico sanitizados del firmware."""

import sys
import time
import types
import unittest
from pathlib import Path

RAIZ_FIRMWARE = Path(__file__).resolve().parents[1]
if str(RAIZ_FIRMWARE) not in sys.path:
    sys.path.insert(0, str(RAIZ_FIRMWARE))


class PinFalso:
    """Pin de host usado al importar e iniciar la aplicación."""

    OUT = 1

    def __init__(self, numero, modo=None, value=None):
        self.numero = numero
        self.modo = modo
        self.nivel = value

    def value(self, nuevo=None):
        if nuevo is not None:
            self.nivel = nuevo
        return self.nivel


class PWMFalso:
    """PWM de host sin acceso a GPIO físico."""

    def __init__(self, pin, freq, duty_u16):
        self.pin = pin
        self.frecuencia = freq
        self.ciclo = duty_u16

    def duty_u16(self, ciclo):
        self.ciclo = ciclo

    def deinit(self):
        pass


def _importar_aplicacion_con_machine_falso():
    modulo_machine = types.ModuleType("machine")
    modulo_machine.Pin = PinFalso
    modulo_machine.PWM = PWMFalso
    machine_original = sys.modules.get("machine")
    sys.modules["machine"] = modulo_machine
    funciones_reloj = {
        nombre: getattr(time, nombre, None)
        for nombre in ("ticks_add", "ticks_diff", "ticks_ms")
    }
    time.ticks_add = lambda valor, delta: valor + delta
    time.ticks_diff = lambda nuevo, anterior: nuevo - anterior
    time.ticks_ms = lambda: int(time.monotonic() * 1000)
    try:
        import aplicacion
    finally:
        for nombre, funcion in funciones_reloj.items():
            if funcion is None:
                delattr(time, nombre)
            else:
                setattr(time, nombre, funcion)
        if machine_original is None:
            del sys.modules["machine"]
        else:
            sys.modules["machine"] = machine_original
    return aplicacion


aplicacion = _importar_aplicacion_con_machine_falso()

if not hasattr(time, "sleep_ms"):
    time.sleep_ms = lambda milisegundos: None
if not hasattr(time, "ticks_diff"):
    time.ticks_diff = lambda nuevo, anterior: nuevo - anterior


class SoporteAplicacionDiagnostico(unittest.TestCase):
    class SalidaControlada(Exception):
        pass

    class PuertoPrueba:
        instancia = None
        entradas_por_iteracion = []

        def __init__(self):
            self.lineas = []
            self.cerrado = False
            self.llamadas_lectura = 0
            self.PuertoPrueba_instancia()

        def PuertoPrueba_instancia(self):
            SoporteAplicacionDiagnostico.PuertoPrueba.instancia = self

        def leer_lineas(self):
            self.llamadas_lectura += 1
            if self.entradas_por_iteracion:
                return self.entradas_por_iteracion.pop(0)
            return ()

        def enviar_linea(self, texto):
            self.lineas.append(texto)

        def cerrar(self):
            self.cerrado = True

    class LectorPrueba:
        def __init__(self, identificador, activos=None, lecturas_rfid1=None):
            self.identificador = identificador
            self.version = 0x92
            self.activo = activos is None or identificador in activos
            self.lecturas_rfid1 = list(lecturas_rfid1 or [])
            self.usa_lecturas_rfid1 = lecturas_rfid1 is not None

        def leer_uid_estado(self):
            if self.identificador == "RFID1" and self.usa_lecturas_rfid1:
                if self.lecturas_rfid1:
                    return self.lecturas_rfid1.pop(0)
                return None, False
            if not self.activo:
                return None, False
            return bytes((0xA1, 0xB2, 0xC3, 0xD4)), True

        def leer_evento(self):
            if not self.activo:
                return self.identificador, None, False
            uid = bytes((0xCA, 0xFE, 0x01, 0x02)) if self.identificador == "RFID3" else bytes((5, 6, 7, 8))
            return self.identificador, uid, True

    def ejecutar_main(
        self, registrar_evento, falla_rfid2=False, falla_rfid3=False, activos=None,
        iteraciones=2, entradas_por_iteracion=None, intervalo_ms=100,
        lecturas_rfid1=None,
    ):
        reloj = {"ahora": 0, "esperas": 0}
        self.PuertoPrueba.instancia = None
        self.PuertoPrueba.entradas_por_iteracion = list(entradas_por_iteracion or [])
        puerto_original = aplicacion.PuertoSerial
        bus_original = aplicacion.BusSPICompartido
        lector_original = aplicacion.LectorRFID
        ticks_original = getattr(time, "ticks_ms", None)
        sleep_original = time.sleep_ms

        def crear_lector(*args, **opciones):
            identificador = opciones["identificador"]
            if falla_rfid2 and identificador == "RFID2":
                raise OSError("detalle privado de hardware")
            if falla_rfid3 and identificador == "RFID3":
                raise OSError("detalle privado de hardware")
            lecturas = lecturas_rfid1 if identificador == "RFID1" else None
            return self.LectorPrueba(identificador, activos, lecturas)

        def dormir(milisegundos):
            reloj["ahora"] += intervalo_ms
            reloj["esperas"] += 1
            if reloj["esperas"] == iteraciones:
                raise self.SalidaControlada()

        aplicacion.PuertoSerial = self.PuertoPrueba
        aplicacion.BusSPICompartido = lambda: object()
        aplicacion.LectorRFID = crear_lector
        time.ticks_ms = lambda: reloj["ahora"]
        time.sleep_ms = dormir
        try:
            with self.assertRaises(self.SalidaControlada):
                aplicacion.main(registrar_evento)
        finally:
            self.PuertoPrueba.entradas_por_iteracion = []
            aplicacion.PuertoSerial = puerto_original
            aplicacion.BusSPICompartido = bus_original
            aplicacion.LectorRFID = lector_original
            time.sleep_ms = sleep_original
            if ticks_original is None:
                del time.ticks_ms
            else:
                time.ticks_ms = ticks_original
        return self.PuertoPrueba.instancia

    def ejecutar_main_con_buzzer_falso(
        self, entradas, iteraciones=4, intervalo_ms=500, lecturas_rfid1=None,
    ):
        class BuzzerFalso:
            def __init__(self, pin_numero, duracion_pitido_ms):
                self.pin_numero = pin_numero
                self.duracion_pitido_ms = duracion_pitido_ms
                self.programaciones = []

            def programar(self, cantidad):
                self.programaciones.append(cantidad)

            def actualizar(self):
                pass

            def finalizar(self):
                pass

        zumbadores = []
        eventos = []
        original = aplicacion.ControladorZumbador

        def crear_zumbador(*, pin_numero, duracion_pitido_ms=150):
            zumbador = BuzzerFalso(pin_numero, duracion_pitido_ms)
            zumbadores.append(zumbador)
            return zumbador

        aplicacion.ControladorZumbador = crear_zumbador
        try:
            puerto = self.ejecutar_main(
                eventos.append, activos={"RFID1"}, iteraciones=iteraciones,
                entradas_por_iteracion=entradas, intervalo_ms=intervalo_ms,
                lecturas_rfid1=lecturas_rfid1,
            )
        finally:
            aplicacion.ControladorZumbador = original
        return puerto, zumbadores, eventos

