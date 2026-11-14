"""Pruebas de host para lectores RC522 y sondeo SPI."""

import time
import unittest

from soporte_firmware_pruebas import (
    DetectorLecturaRfid,
    GestorCaptura,
    GestorEntradaRfid2,
    LectorRC522,
    MachineFalsa,
    Protocolo,
    PuertoSerial,
    RelojFalso,
    SPIFalso,
    UARTFalso,
)


class PruebasLectorSPI(unittest.TestCase):
    def setUp(self):
        SPIFalso.instancia = None

    def test_detecta_rc522_por_version_spi(self):
        lector = LectorRC522(machine_module=MachineFalsa)
        self.assertEqual(lector.version, 0x92)
        self.assertEqual(SPIFalso.instancia.registros[0x14] & 0x03, 0x03)

    def test_detecta_rc522_ausente(self):
        clase_spi = SPIFalso
        original = clase_spi.__init__

        def sin_lector(self, *args, **kwargs):
            original(self, *args, **kwargs)
            self.registros[0x37] = 0xFF

        clase_spi.__init__ = sin_lector
        try:
            with self.assertRaises(OSError):
                LectorRC522(machine_module=MachineFalsa)
        finally:
            clase_spi.__init__ = original

    def test_ping_se_atiende_durante_espera_spi_sin_respuesta(self):
        uart = UARTFalso((b"PING\n",))
        puerto = PuertoSerial(uart)
        reloj = RelojFalso()
        captura = GestorCaptura(puerto, reloj.ticks_ms)
        protocolo = Protocolo(puerto, captura, reloj.ticks_ms)
        captura.iniciar_enrolamiento("b" * 32)
        lector = LectorRC522(protocolo.atender, MachineFalsa)
        lector.spi.espera_sin_respuesta = True

        respuesta = lector._transmitir((0x52,), 7, informar_presencia=True)

        self.assertEqual(respuesta, (None, None))
        self.assertEqual(lector.leer_uid_estado(), (None, None))
        self.assertIn("PONG\n", uart.escritos)
        self.assertEqual(captura.enrolamiento["state"], "SCANNING")
        self.assertGreaterEqual(len(uart.escritos), 1)

    def test_timer_irq_sigue_indicando_ausencia(self):
        lector = LectorRC522(machine_module=MachineFalsa)
        leer_original = lector._leer_reg
        lector._leer_reg = lambda registro: 1 if registro == 0x04 else leer_original(registro)

        self.assertEqual(lector._transmitir((0x52,), 7, informar_presencia=True), (None, False))
        self.assertEqual(lector.leer_uid_estado(), (None, False))

    def test_sondeo_incierto_no_rearma_ninguno_de_los_tres_lectores(self):
        lector = LectorRC522(machine_module=MachineFalsa)
        lector.spi.espera_sin_respuesta = True
        reloj = RelojFalso()
        uart1, uart2 = UARTFalso(), UARTFalso()
        captura = GestorCaptura(PuertoSerial(uart1), reloj.ticks_ms)
        entrada = GestorEntradaRfid2(PuertoSerial(uart2), reloj.ticks_ms, time.ticks_diff)
        detector = DetectorLecturaRfid("RFID3", time.ticks_diff)
        uid = bytes((1, 2, 3, 4))
        captura.iniciar_enrolamiento("b" * 32)

        for ahora in (0, 80):
            captura.procesar_tarjeta(uid, True, ahora, 80)
            entrada.procesar_tarjeta(uid, True, ahora, 80)
            evento = detector.actualizar(uid, True, ahora, 80)
        self.assertEqual(captura.secuencia, 1)
        self.assertEqual(captura.enrolamiento["state"], "CAPTURED")
        self.assertIsNotNone(entrada.pendiente)
        self.assertEqual(evento, ("RFID3", "DETECCION", "TARJETA_DETECTADA"))
        captura.resultado("0001", "DENY")
        self.assertTrue(entrada.recibir_resultado(entrada.pendiente["lectura_id"], "DENEGADA"))

        for ahora in (300, 600, 900, 1200, 1500, 1800):
            lectura, presente = lector.leer_uid_estado()
            self.assertEqual((lectura, presente), (None, None))
            captura.procesar_tarjeta(lectura, presente, ahora, 80)
            entrada.procesar_tarjeta(lectura, presente, ahora, 80)
            self.assertIsNone(detector.actualizar(lectura, presente, ahora, 80))

        for ahora in (1900, 1980):
            captura.procesar_tarjeta(uid, True, ahora, 80)
            self.assertFalse(entrada.procesar_tarjeta(uid, True, ahora, 80))
            self.assertIsNone(detector.actualizar(uid, True, ahora, 80))
        self.assertEqual(captura.secuencia, 1)
        self.assertIsNone(entrada.pendiente)
        self.assertEqual(sum(linea.startswith("RFID2,") for linea in uart2.escritos), 1)
        self.assertEqual(detector.ultimo_uid, uid)


if __name__ == "__main__":
    unittest.main()
