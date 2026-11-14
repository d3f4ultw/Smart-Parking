"""Pruebas aisladas de tres lectores RC522 en un único bus SPI."""

import sys
import time
import types
import unittest
from pathlib import Path

RAIZ_FIRMWARE = Path(__file__).resolve().parents[1]
if str(RAIZ_FIRMWARE) not in sys.path:
    sys.path.insert(0, str(RAIZ_FIRMWARE))

def _importar_aplicacion():
    maquina_original = sys.modules.get("machine")
    maquina_simulada = types.ModuleType("machine")
    maquina_simulada.Pin = object
    maquina_simulada.PWM = object
    sys.modules["machine"] = maquina_simulada
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
        if maquina_original is None:
            del sys.modules["machine"]
        else:
            sys.modules["machine"] = maquina_original
    return aplicacion


aplicacion = _importar_aplicacion()

import config
from captura import GestorCaptura
from comunicacion.protocolo import Protocolo
from comunicacion.serial import PuertoSerial
from rfid.bus_spi import BusSPICompartido
from rfid.lector import DetectorLecturaRfid, LectorRFID
from simulador_picc import MachinePICC, PinPICC, SPIPICC
from test_dual_rc522 import RelojFalso, UARTFalso


class PruebasTresLectores(unittest.TestCase):
    def setUp(self):
        PinPICC.instancias = []
        SPIPICC.instancias = []
        SPIPICC.demora_irq = 0
        SPIPICC.tarjetas = {}

    def crear_lectores(self, atender_serial=None):
        bus = BusSPICompartido(MachinePICC)
        lectores = []
        for indice, rst in enumerate((22, 27, 32)):
            lectores.append(LectorRFID(
                atender_serial=atender_serial, machine_module=MachinePICC,
                identificador="RFID{}".format(indice + 1),
                bus_spi=bus, indice_cs=indice, pin_rst=rst,
            ))
        return bus, lectores

    def assert_cs_inactivos(self, bus):
        self.assertEqual([cs.value() for cs in bus.cs], [1, 1, 1])

    def test_bus_unico_y_tres_lectores_con_resets_independientes(self):
        bus, lectores = self.crear_lectores()

        self.assertEqual(config.PIN_RFID3_CS, 33)
        self.assertEqual(config.PIN_RFID3_RST, 32)
        self.assertEqual(config.PIN_ZUMBADOR, 25)
        self.assertEqual(config.PIN_RESERVADO, 16)
        self.assertEqual([cs.numero for cs in bus.cs], [5, 26, 33])
        self.assert_cs_inactivos(bus)
        self.assertEqual(len(SPIPICC.instancias), 1)
        self.assertTrue(all(lector.controlador.spi is bus.spi for lector in lectores))
        self.assertEqual([lector.version for lector in lectores], [0x92, 0x92, 0x92])
        self.assertEqual([lector.controlador.rst.numero for lector in lectores], [22, 27, 32])
        for pin in (4, 16, 21):
            self.assertNotIn(pin, [instancia.numero for instancia in PinPICC.instancias])
        self.assertEqual({op[1] for op in bus.spi.operaciones}, {5, 26, 33})

    def test_seleccion_exclusiva_y_liberacion_ante_error_de_spi(self):
        bus, lectores = self.crear_lectores()
        bus.seleccionar(bus.cs[2])
        self.assertEqual([cs.value() for cs in bus.cs], [1, 1, 0])
        with self.assertRaises(OSError):
            bus.seleccionar(bus.cs[1])
        bus.liberar()
        self.assert_cs_inactivos(bus)

        escribir_original = bus.spi.write
        try:
            def fallar(_datos):
                raise OSError("error SPI simulado")

            bus.spi.write = fallar
            with self.assertRaises(OSError):
                lectores[2].controlador._escribir_reg(1, 2)
            self.assert_cs_inactivos(bus)
        finally:
            bus.spi.write = escribir_original
        self.assertEqual(lectores[0].controlador._leer_reg(0x37), 0x92)
        self.assert_cs_inactivos(bus)

    def test_version_ausente_rfid3_no_invalida_los_otros(self):
        bus = BusSPICompartido(MachinePICC)
        lectores = [
            LectorRFID(machine_module=MachinePICC, identificador="RFID1", bus_spi=bus, indice_cs=0, pin_rst=22),
            LectorRFID(machine_module=MachinePICC, identificador="RFID2", bus_spi=bus, indice_cs=1, pin_rst=27),
        ]
        leer_original = bus.spi.write_readinto

        def version_ausente(tx, rx):
            cs = bus.spi._leer_cs()
            registro = ((tx[0] & 0x7E) >> 1) & 0x3F
            if cs == 33 and registro == 0x37:
                rx[1] = 0xFF
            else:
                leer_original(tx, rx)

        bus.spi.write_readinto = version_ausente
        try:
            with self.assertRaises(OSError):
                LectorRFID(machine_module=MachinePICC, identificador="RFID3", bus_spi=bus, indice_cs=2, pin_rst=32)
        finally:
            bus.spi.write_readinto = leer_original
        self.assert_cs_inactivos(bus)
        self.assertEqual([lector.controlador._leer_reg(0x37) for lector in lectores], [0x92, 0x92])

    def test_aislamiento_y_alternancia_de_lecturas_picc(self):
        bus, lectores = self.crear_lectores()
        uid = bytes((1, 2, 3, 4))
        secuencia = (0, 1, 2, 2, 1, 0, 2)
        for indice_activo in secuencia:
            cs_activo = (5, 26, 33)[indice_activo]
            SPIPICC.tarjetas = {cs_activo: uid}
            for indice, lector in enumerate(lectores):
                lectura = lector.leer_evento()
                esperado = (uid, True) if indice == indice_activo else (None, False)
                self.assertEqual(lectura, ("RFID{}".format(indice + 1), *esperado))
                self.assert_cs_inactivos(bus)
        self.assertEqual({op[1] for op in bus.spi.operaciones}, {5, 26, 33})

    def test_supresion_de_duplicados_y_retiro_independiente(self):
        detectores = [DetectorLecturaRfid("RFID{}".format(i)) for i in (1, 2, 3)]
        uid = bytes((9, 8, 7, 6))
        for indice, detector in enumerate(detectores, start=1):
            esperado = ("RFID{}".format(indice), "DETECCION", "TARJETA_DETECTADA")
            self.assertIsNone(detector.actualizar(uid, True, 0, 80, 1000))
            self.assertEqual(detector.actualizar(uid, True, 80, 80, 1000), esperado)
            self.assertIsNone(detector.actualizar(uid, True, 3000, 80, 1000))
            self.assertIsNone(detector.actualizar(None, False, 4000, 80, 1000))
            self.assertIsNone(detector.actualizar(None, False, 4500, 80, 1000))
            self.assertIsNone(detector.actualizar(None, False, 5000, 80, 1000))
            self.assertIsNone(detector.actualizar(uid, True, 5050, 80, 1000))
            self.assertEqual(detector.actualizar(uid, True, 5130, 80, 1000), esperado)

    def test_ping_se_atiende_durante_sondeo_del_tercer_lector(self):
        uid = bytes((5, 6, 7, 8))
        SPIPICC.tarjetas = {33: uid}
        SPIPICC.demora_irq = 21
        uart = UARTFalso((b"PING\n",))
        puerto = PuertoSerial(uart)
        reloj = RelojFalso(1234)
        captura = GestorCaptura(puerto, reloj.ticks_ms)
        protocolo = Protocolo(puerto, captura, reloj.ticks_ms)
        bus, lectores = self.crear_lectores(protocolo.atender)

        self.assertEqual(lectores[2].leer_evento(), ("RFID3", uid, True))
        self.assertIn("PONG\n", uart.escritos)
        self.assertEqual(protocolo.ultimo_ping, 1234)
        self.assert_cs_inactivos(bus)


class PruebasRetiroObservado(unittest.TestCase):
    UID = bytes((1, 2, 3, 4))
    EVENTO = ("RFID3", "DETECCION", "TARJETA_DETECTADA")

    def crear_detectado(self, diferencia=None, tiempos=(0, 80)):
        diferencia = diferencia or (lambda nuevo, anterior: nuevo - anterior)
        detector = DetectorLecturaRfid("RFID3", diferencia)
        self.assertIsNone(detector.actualizar(self.UID, True, tiempos[0], 80, 1000))
        self.assertEqual(detector.actualizar(self.UID, True, tiempos[1], 80, 1000), self.EVENTO)
        return detector

    def comprobar_sigue_bloqueado(self, detector, inicio):
        self.assertIsNone(detector.actualizar(self.UID, True, inicio, 80, 1000))
        self.assertIsNone(detector.actualizar(self.UID, True, inicio + 80, 80, 1000))

    def test_una_ausencia_despues_de_pausa_no_rearma(self):
        detector = self.crear_detectado()
        self.assertIsNone(detector.actualizar(None, False, 1800, 80, 1000))
        self.comprobar_sigue_bloqueado(detector, 1820)

    def test_desconocido_y_presencia_interrumpen_la_ausencia(self):
        for uid, estado in ((None, None), (None, True), (self.UID, True)):
            with self.subTest(estado=estado, uid_disponible=uid is not None):
                detector = self.crear_detectado()
                for instante in (100, 900):
                    self.assertIsNone(detector.actualizar(None, False, instante, 80, 1000))
                self.assertIsNone(detector.actualizar(uid, estado, 950, 80, 1000))
                for instante in (1100, 1300):
                    self.assertIsNone(detector.actualizar(None, False, instante, 80, 1000))
                self.comprobar_sigue_bloqueado(detector, 1320)

    def test_desconocido_y_una_ausencia_tardia_no_producen_duplicado(self):
        detector = self.crear_detectado()
        self.assertIsNone(detector.actualizar(None, None, 500, 80, 1000))
        self.assertIsNone(detector.actualizar(None, False, 1080, 80, 1000))
        self.comprobar_sigue_bloqueado(detector, 1100)

    def test_intervalo_de_ausencia_inferior_al_limite_no_rearma(self):
        detector = self.crear_detectado()
        for instante in (100, 1099):
            self.assertIsNone(detector.actualizar(None, False, instante, 80, 1000))
        self.comprobar_sigue_bloqueado(detector, 1100)

    def test_ausencia_observada_hasta_el_limite_permite_relectura(self):
        detector = self.crear_detectado()
        for instante in (100, 1099, 1100):
            self.assertIsNone(detector.actualizar(None, False, instante, 80, 1000))
        self.assertIsNone(detector.actualizar(self.UID, True, 1120, 80, 1000))
        self.assertEqual(detector.actualizar(self.UID, True, 1200, 80, 1000), self.EVENTO)

    def test_hueco_igual_o_mayor_al_limite_reinicia_ausencia(self):
        for hueco in (1000, 1001, 3000):
            with self.subTest(hueco_ms=hueco):
                detector = self.crear_detectado()
                self.assertIsNone(detector.actualizar(None, False, 100, 80, 1000))
                self.assertIsNone(detector.actualizar(None, False, 100 + hueco, 80, 1000))
                self.comprobar_sigue_bloqueado(detector, 120 + hueco)

    def test_wrap_de_ticks_con_primera_ausencia_en_cero(self):
        periodo = 2**30
        diferencia = lambda nuevo, anterior: ((nuevo - anterior + periodo // 2) % periodo) - periodo // 2
        detector = self.crear_detectado(diferencia, (periodo - 100, periodo - 20))
        for instante in (0, 500, 1000):
            self.assertIsNone(detector.actualizar(None, False, instante, 80, 1000))
        self.assertIsNone(detector.actualizar(self.UID, True, 1020, 80, 1000))
        self.assertEqual(detector.actualizar(self.UID, True, 1100, 80, 1000), self.EVENTO)


if __name__ == "__main__":
    unittest.main()
