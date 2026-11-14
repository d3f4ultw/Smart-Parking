"""Pruebas de eventos y lectura de tarjetas con lectores duales."""

import unittest

from soporte_dual_rc522 import (
    BusSPICompartido,
    DetectorLecturaRfid,
    GestorCaptura,
    LectorRFID,
    MachinePICC,
    PinPICC,
    Protocolo,
    PuertoSerial,
    RelojFalso,
    SPIPICC,
    UARTFalso,
)


class PruebasEventosLectores(unittest.TestCase):
    def test_evento_identifica_lector_y_no_incluye_uid(self):
        lector1 = LectorRFID.__new__(LectorRFID)
        lector1.identificador = "RFID1"
        lector1.leer_uid_estado = lambda: (bytes((1, 2, 3, 4)), True)
        lector2 = LectorRFID.__new__(LectorRFID)
        lector2.identificador = "RFID2"
        lector2.leer_uid_estado = lambda: (bytes((5, 6, 7, 8)), True)

        self.assertEqual(lector1.leer_evento(), ("RFID1", bytes((1, 2, 3, 4)), True))
        self.assertEqual(lector2.leer_evento(), ("RFID2", bytes((5, 6, 7, 8)), True))

    def test_duplicado_es_independiente_por_lector_y_requiere_retiro(self):
        detector1 = DetectorLecturaRfid("RFID1")
        detector2 = DetectorLecturaRfid("RFID2")
        uid = bytes((0xA1, 0xB2, 0xC3, 0xD4))

        self.assertIsNone(detector1.actualizar(uid, True, 0, 80, 1000))
        self.assertIsNone(detector2.actualizar(uid, True, 0, 80, 1000))
        self.assertEqual(detector1.actualizar(uid, True, 80, 80, 1000), ("RFID1", "DETECCION", "TARJETA_DETECTADA"))
        self.assertEqual(detector2.actualizar(uid, True, 80, 80, 1000), ("RFID2", "DETECCION", "TARJETA_DETECTADA"))
        self.assertIsNone(detector2.actualizar(uid, True, 100, 80, 1000))
        detector2.actualizar(None, False, 1200, 80, 1000)
        detector2.actualizar(None, False, 1700, 80, 1000)
        detector2.actualizar(None, False, 2200, 80, 1000)
        self.assertIsNone(detector1.actualizar(uid, True, 2300, 80, 1000))
        self.assertIsNone(detector2.actualizar(uid, True, 2300, 80, 1000))
        self.assertEqual(detector2.actualizar(uid, True, 2380, 80, 1000), ("RFID2", "DETECCION", "TARJETA_DETECTADA"))


class PruebasProtocoloPICC(unittest.TestCase):
    def setUp(self):
        PinPICC.instancias = []
        SPIPICC.instancias = []
        SPIPICC.demora_irq = 0
        SPIPICC.tarjetas = {}

    def crear_lectores(self, uid1, uid2):
        SPIPICC.tarjetas = {5: uid1, 26: uid2}
        bus = BusSPICompartido(MachinePICC)
        lector1 = LectorRFID(machine_module=MachinePICC, identificador="RFID1", bus_spi=bus, indice_cs=0)
        lector2 = LectorRFID(
            machine_module=MachinePICC, identificador="RFID2", bus_spi=bus,
            indice_cs=1, pin_rst=27,
        )
        return bus, lector1, lector2

    def test_lectura_picc_real_recupera_uid_de_cuatro_y_siete_bytes(self):
        uid1 = bytes((0x01, 0x23, 0x45, 0x67))
        uid2 = bytes((0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77))
        _, lector1, lector2 = self.crear_lectores(uid1, uid2)

        self.assertEqual(lector1.leer_uid_estado(), (uid1, True))
        self.assertEqual(lector2.leer_uid_estado(), (uid2, True))
        bytes_fifo = [
            operacion[3] for operacion in SPIPICC.instancias[0].operaciones
            if len(operacion) == 4 and operacion[0] == "W" and operacion[2] == 0x09
        ]
        self.assertIn(0x93, bytes_fifo)
        self.assertIn(0x70, bytes_fifo)
        self.assertTrue(any(op[0] == "R" and op[2] == 0x21 for op in SPIPICC.instancias[0].operaciones))
        tramas_select = [
            trama for _, trama in SPIPICC.instancias[0].tramas_transmitidas
            if len(trama) >= 9 and trama[1] == 0x70
        ]
        self.assertEqual(len(tramas_select), 3)
        self.assertTrue(all(trama[-2:] == bytes((0x34, 0x12)) for trama in tramas_select))
        self.assertTrue(all(lector.controlador.cs.value() == 1 for lector in (lector1, lector2)))

    def test_anticollision_de_uid_de_diez_bytes_recorre_tres_niveles(self):
        uid = bytes((0x10, 0x21, 0x32, 0x43, 0x54, 0x65, 0x76, 0x87, 0x98, 0xA9))
        _, lector1, _ = self.crear_lectores(uid, None)

        self.assertEqual(lector1.leer_uid_estado(), (uid, True))
        tramas = SPIPICC.instancias[0].tramas_transmitidas
        anticollision = [trama[0] for _, trama in tramas if len(trama) == 2 and trama[1] == 0x20]
        self.assertEqual(anticollision, [0x93, 0x95, 0x97])

    def test_lectura_rfid1_alimenta_captura_de_enrolamiento_existente(self):
        uid = bytes((0xA1, 0xB2, 0xC3, 0xD4))
        _, lector1, lector2 = self.crear_lectores(uid, bytes((9, 8, 7, 6)))
        uart = UARTFalso()
        puerto = PuertoSerial(uart)
        reloj = RelojFalso()
        captura = GestorCaptura(puerto, reloj.ticks_ms)
        captura.iniciar_enrolamiento("a" * 32)

        lectura1, presente1 = lector1.leer_uid_estado()
        _, lectura2, presente2 = lector2.leer_evento()
        captura.procesar_tarjeta(lectura1, presente1, 0, 80)
        captura.procesar_tarjeta(lectura1, presente1, 80, 80)

        self.assertEqual((lectura1, presente1), (uid, True))
        self.assertEqual(lectura2, bytes((9, 8, 7, 6)))
        self.assertTrue(presente2)
        self.assertIn("RFID,0001,A1B2C3D4\n", uart.escritos)
        self.assertIn("ENROLL_READ,{},0001,A1B2C3D4\n".format("a" * 32), uart.escritos)
        self.assertFalse(any("09080706" in linea for linea in uart.escritos))

    def test_alternancia_rapida_conserva_uid_y_cs_por_lector(self):
        uid1 = bytes((0x01, 0x02, 0x03, 0x04))
        uid2 = bytes((0x05, 0x06, 0x07, 0x08))
        _, lector1, lector2 = self.crear_lectores(uid1, uid2)

        resultados = []
        for _ in range(4):
            resultados.append(lector1.leer_uid_estado())
            resultados.append(lector2.leer_uid_estado())

        self.assertEqual(resultados, [(uid1, True), (uid2, True)] * 4)
        transacciones = [op for op in SPIPICC.instancias[0].operaciones if op[0] in ("W", "R")]
        self.assertEqual({op[1] for op in transacciones}, {5, 26})
        self.assertTrue(all(pin.value() == 1 for pin in lector1.controlador.bus_spi.cs))

    def test_ping_uart_se_atiende_durante_sondeo_de_spi(self):
        uid = bytes((0x21, 0x22, 0x23, 0x24))
        SPIPICC.tarjetas = {5: uid}
        SPIPICC.demora_irq = 21
        bus = BusSPICompartido(MachinePICC)
        uart = UARTFalso((b"PING\n",))
        puerto = PuertoSerial(uart)
        reloj = RelojFalso(1234)
        captura = GestorCaptura(puerto, reloj.ticks_ms)
        protocolo = Protocolo(puerto, captura, reloj.ticks_ms)
        lector = LectorRFID(
            atender_serial=protocolo.atender, machine_module=MachinePICC,
            identificador="RFID1", bus_spi=bus, indice_cs=0,
        )

        resultado = lector.leer_uid_estado()

        self.assertEqual(resultado, (uid, True))
        self.assertIn("PONG\n", uart.escritos)
        self.assertEqual(protocolo.ultimo_ping, 1234)



if __name__ == "__main__":
    unittest.main()
