"""Pruebas de propiedad del bus SPI compartido."""

import unittest

from soporte_dual_rc522 import BusSPICompartido, LectorRFID, MachineFalsa, PinFalso, SPIFalso


class PruebasBusCompartido(unittest.TestCase):
    def setUp(self):
        PinFalso.instancias = []
        SPIFalso.instancias = []

    def test_inicializa_dos_lectores_con_un_spi_y_cs_inactivos(self):
        bus = BusSPICompartido(MachineFalsa)
        cs_rfid1 = bus.obtener_cs(0)
        cs_rfid2 = bus.obtener_cs(1)

        lector1 = LectorRFID(machine_module=MachineFalsa, identificador="RFID1", bus_spi=bus, indice_cs=0)
        lector2 = LectorRFID(
            machine_module=MachineFalsa, identificador="RFID2", bus_spi=bus,
            indice_cs=1, pin_rst=27,
        )

        self.assertEqual(len(SPIFalso.instancias), 1)
        self.assertIs(lector1.controlador.spi, lector2.controlador.spi)
        self.assertEqual((lector1.version, lector2.version), (0x92, 0x92))
        self.assertEqual((cs_rfid1.numero, cs_rfid2.numero), (5, 26))
        self.assertEqual((cs_rfid1.value(), cs_rfid2.value()), (1, 1))
        self.assertEqual(lector1.controlador.rst.numero, 22)
        self.assertEqual(lector2.controlador.rst.numero, 27)
        selecciones_lectura = {
            cs for tipo, cs, _ in SPIFalso.instancias[0].operaciones if tipo == "read"
        }
        self.assertEqual(selecciones_lectura, {5, 26})

    def test_bus_rechaza_seleccion_simultanea_y_restaura_cs(self):
        bus = BusSPICompartido(MachineFalsa)
        primero = bus.obtener_cs(0)
        segundo = bus.obtener_cs(1)
        bus.seleccionar(primero)
        self.assertEqual((primero.value(), segundo.value()), (0, 1))
        with self.assertRaises(OSError):
            bus.seleccionar(segundo)
        bus.liberar()
        self.assertEqual((primero.value(), segundo.value()), (1, 1))

    def test_fallo_de_version_de_un_lector_no_invalida_el_otro(self):
        bus = BusSPICompartido(MachineFalsa)
        lector1 = LectorRFID(machine_module=MachineFalsa, bus_spi=bus, indice_cs=0)
        spi = bus.spi
        original = spi.write_readinto

        def version_ausente_en_rfid2(tx, rx):
            cs = spi._lector_seleccionado()
            registro = ((tx[0] & 0x7E) >> 1) & 0x3F
            rx[1] = 0xFF if cs == 26 and registro == 0x37 else (0x92 if registro == 0x37 else 0)

        spi.write_readinto = version_ausente_en_rfid2
        try:
            with self.assertRaises(OSError):
                LectorRFID(machine_module=MachineFalsa, identificador="RFID2", bus_spi=bus, indice_cs=1, pin_rst=27)
        finally:
            spi.write_readinto = original

        self.assertEqual(lector1.version, 0x92)
        self.assertEqual(lector1.controlador._leer_reg(0x37), 0x92)




if __name__ == "__main__":
    unittest.main()
