"""Pruebas de host para el protocolo RFID y la captura modular."""

import unittest

from soporte_firmware_pruebas import (
    FIRMWARE_ORIGINAL,
    GestorCaptura,
    Protocolo,
    PuertoSerial,
    RelojFalso,
    UARTFalso,
)


class PruebasPuertoYProtocolo(unittest.TestCase):
    def test_protocolo_modular_equivale_a_tramas_del_firmware_recuperado(self):
        session_id = "c" * 32
        comandos = (
            "PING",
            "ENROLL_ARM," + session_id,
            "ENROLL_CANCEL," + session_id,
            "ACK,0007",
            "RESULT,0007,DENY",
        )

        for comando in comandos:
            with self.subTest(comando=comando):
                uart_original = UARTFalso()
                uart_modular = UARTFalso()
                puerto = PuertoSerial(uart_modular)
                reloj = RelojFalso(1234)
                captura = GestorCaptura(puerto, reloj.ticks_ms)
                protocolo = Protocolo(puerto, captura, reloj.ticks_ms)
                protocolo.version_lector = 0x92
                estado_original = {
                    "pendiente": None,
                    "ultimo_ping": 0,
                    "sonido": FIRMWARE_ORIGINAL.ControladorZumbador(uart_original),
                    "enrollment": None,
                    "reader_version": 0x92,
                    "reader_error": None,
                }

                if comando.startswith(("ACK,", "RESULT,")):
                    pendiente_original = {
                        "id": "0007", "uid": "01020304", "ack": False,
                        "intentos": 1, "ultimo_envio": 1000,
                    }
                    estado_original["pendiente"] = pendiente_original
                    captura.pendiente = dict(pendiente_original)

                FIRMWARE_ORIGINAL._procesar_trama(uart_original, comando, estado_original)
                protocolo.procesar_linea(comando)

                self.assertEqual(uart_modular.escritos, uart_original.escritos)
                self.assertEqual(captura.enrolamiento, estado_original["enrollment"])
                if comando.startswith("ACK,"):
                    self.assertEqual(captura.pendiente["ack"], estado_original["pendiente"]["ack"])
                elif comando.startswith("RESULT,"):
                    self.assertEqual(captura.pendiente, estado_original["pendiente"])
                elif comando == "PING":
                    self.assertEqual(protocolo.ultimo_ping, estado_original["ultimo_ping"])

    def test_framing_fragmentado_y_ping_no_expone_datos(self):
        uart = UARTFalso((b"PI", b"NG\r\n", b"ENROLL_ARM,", b"parcial"))
        puerto = PuertoSerial(uart)
        reloj = RelojFalso()
        captura = GestorCaptura(puerto, reloj.ticks_ms)
        protocolo = Protocolo(puerto, captura, reloj.ticks_ms)
        protocolo.version_lector = 0x92

        protocolo.atender()
        protocolo.atender()
        protocolo.atender()

        self.assertEqual(uart.escritos[:2], ["PONG\n", "RFID_READER,READY,92\n"])
        self.assertEqual(protocolo.ultimo_ping, 0)
        self.assertIsNone(captura.enrolamiento)
        self.assertFalse(any("UID" in linea or "TOKEN" in linea for linea in uart.escritos))

    def test_linea_larga_se_descarta_y_siguiente_ping_se_atiende(self):
        uart = UARTFalso((b"X" * 97 + b"\nPING\n",))
        puerto = PuertoSerial(uart)
        self.assertEqual(puerto.leer_lineas(), ["PING"])

    def test_comandos_captura_enrolamiento_ack_y_resultado(self):
        uart = UARTFalso()
        puerto = PuertoSerial(uart)
        reloj = RelojFalso(100)
        captura = GestorCaptura(puerto, reloj.ticks_ms)
        protocolo = Protocolo(puerto, captura, reloj.ticks_ms)
        session_id = "a" * 32

        protocolo.procesar_linea("ENROLL_ARM," + session_id)
        self.assertEqual(captura.enrolamiento["state"], "SCANNING")
        captura.procesar_tarjeta(bytes((1, 2, 3, 4)), True, 100, 80)
        captura.procesar_tarjeta(bytes((1, 2, 3, 4)), True, 180, 80)
        self.assertEqual(captura.pendiente["id"], "0001")
        self.assertIn("RFID,0001,01020304\n", uart.escritos)
        self.assertIn("ENROLL_READ,{},{},01020304\n".format(session_id, "0001"), uart.escritos)

        reloj.avanzar(1580)
        captura.actualizar(reloj.ticks_ms())
        self.assertEqual(uart.escritos.count("RFID,0001,01020304\n"), 2)
        protocolo.procesar_linea("ACK,0001")
        self.assertTrue(captura.pendiente["ack"])
        protocolo.procesar_linea("RESULT,0001,DENY")
        self.assertIsNone(captura.pendiente)
        self.assertIn("RESULT_ACK,0001,DENY\n", uart.escritos)
        protocolo.procesar_linea("ENROLL_CANCEL," + session_id)
        self.assertIsNone(captura.enrolamiento)
        self.assertIn("ENROLL_STATE,{},CANCELLED\n".format(session_id), uart.escritos)

    def test_duplicado_se_suprime_hasta_retiro_y_timeout_limita_reintentos(self):
        uart = UARTFalso()
        puerto = PuertoSerial(uart)
        reloj = RelojFalso()
        captura = GestorCaptura(puerto, reloj.ticks_ms)
        uid = bytes((0xA1, 0xB2, 0xC3, 0xD4))
        captura.procesar_tarjeta(uid, True, 0, 80)
        captura.procesar_tarjeta(uid, True, 80, 80)
        captura.procesar_tarjeta(uid, True, 100, 80)
        self.assertEqual(uart.escritos.count("RFID,0001,A1B2C3D4\n"), 1)
        captura.procesar_tarjeta(uid, True, 200, 80)
        self.assertEqual(uart.escritos.count("RFID,0001,A1B2C3D4\n"), 1)

        for ahora in (1580, 3080, 4580):
            captura.actualizar(ahora)
        self.assertIsNone(captura.pendiente)
        self.assertIn("SOUND_SIM,ERROR,3,25\n", uart.escritos)
        captura.procesar_tarjeta(uid, False, 2000, 80)
        captura.procesar_tarjeta(uid, True, 2100, 80)
        captura.procesar_tarjeta(uid, True, 2180, 80)
        self.assertIn("RFID,0002,A1B2C3D4\n", uart.escritos)




if __name__ == "__main__":
    unittest.main()
