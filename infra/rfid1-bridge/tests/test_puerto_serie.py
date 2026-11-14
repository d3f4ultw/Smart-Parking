"""Pruebas POSIX del framing CRLF y el límite de tramas seriales."""

import errno
import fcntl
import os
import pty
import struct
import termios
import unittest
from unittest.mock import patch

from puerto_serie import ErrorProtocolo, PuertoSerie


class PuertoSerieTest(unittest.TestCase):
    def setUp(self):
        self.maestro, esclavo = pty.openpty()
        self.ruta = os.ttyname(esclavo)
        os.close(esclavo)
        self.puerto = PuertoSerie(self.ruta)

    def tearDown(self):
        self.puerto.cerrar()
        os.close(self.maestro)

    def test_conserva_fragmentos_y_separa_tramas_lf(self):
        os.write(self.maestro, b"PO")
        self.assertIsNone(self.puerto.leer_linea(0.01))
        os.write(self.maestro, b"NG\r\nRFID,000A,04A1")
        self.assertEqual(self.puerto.leer_linea(0.2), "PONG")
        self.assertIsNone(self.puerto.leer_linea(0.01))
        os.write(self.maestro, b"B2C3\n")
        self.assertEqual(
            self.puerto.leer_linea(0.2), "RFID,000A,04A1B2C3"
        )

    def test_rechaza_bytes_no_ascii_sin_devolverlos(self):
        os.write(self.maestro, b"\xff\n")
        with self.assertRaises(ErrorProtocolo):
            self.puerto.leer_linea(0.2)

    def test_rechaza_trama_larga_y_descarta_hasta_lf(self):
        os.write(self.maestro, b"A" * 513 + b"\nPONG\n")
        with self.assertRaises(ErrorProtocolo):
            self.puerto.leer_linea(0.2)
        self.assertEqual(self.puerto.leer_linea(0.2), "PONG")

    def test_escritura_crlf_completa(self):
        self.puerto.escribir_linea("PING")
        self.assertEqual(os.read(self.maestro, 6), b"PING\r\n")

    def test_tty_no_admite_un_segundo_propietario(self):
        with self.assertRaises(OSError):
            PuertoSerie(self.ruta)

    def test_desconexion_y_reapertura_de_pty(self):
        maestro_anterior = None
        puerto_anterior = None
        maestro_nuevo = None
        puerto_nuevo = None
        try:
            maestro_anterior, esclavo_anterior = pty.openpty()
            ruta_anterior = os.ttyname(esclavo_anterior)
            os.close(esclavo_anterior)
            puerto_anterior = PuertoSerie(ruta_anterior)
            os.close(maestro_anterior)
            maestro_anterior = None
            with self.assertRaises(OSError):
                puerto_anterior.leer_linea(0.2)
            puerto_anterior.cerrar()

            maestro_nuevo, esclavo_nuevo = pty.openpty()
            ruta_nueva = os.ttyname(esclavo_nuevo)
            os.close(esclavo_nuevo)
            puerto_nuevo = PuertoSerie(ruta_nueva)
            os.write(maestro_nuevo, b"PONG\n")
            self.assertEqual(puerto_nuevo.leer_linea(0.2), "PONG")
            puerto_nuevo.escribir_linea("PING")
            self.assertEqual(os.read(maestro_nuevo, 6), b"PING\r\n")
        finally:
            if puerto_anterior is not None:
                puerto_anterior.cerrar()
            if maestro_anterior is not None:
                os.close(maestro_anterior)
            if puerto_nuevo is not None:
                puerto_nuevo.cerrar()
            if maestro_nuevo is not None:
                os.close(maestro_nuevo)


class LineasControlTest(unittest.TestCase):
    def setUp(self):
        self.maestro, esclavo = pty.openpty()
        self.ruta = os.ttyname(esclavo)
        os.close(esclavo)

    def tearDown(self):
        os.close(self.maestro)

    def test_desactiva_dtr_y_despues_rts(self):
        ioctl_real = fcntl.ioctl
        lineas = []

        def ioctl(fd, operacion, argumento=0):
            if operacion == termios.TIOCMBIC:
                lineas.append(struct.unpack("I", argumento)[0])
                return 0
            return ioctl_real(fd, operacion, argumento)

        with patch("puerto_serie.fcntl.ioctl", side_effect=ioctl):
            with PuertoSerie(self.ruta):
                self.assertEqual(lineas, [termios.TIOCM_DTR, termios.TIOCM_RTS])

    def test_tolera_enotty_y_einval_en_cada_linea(self):
        for codigo in (errno.ENOTTY, errno.EINVAL):
            for linea in (termios.TIOCM_DTR, termios.TIOCM_RTS):
                with self.subTest(codigo=codigo, linea=linea):
                    ioctl_real = fcntl.ioctl
                    lineas = []

                    def ioctl(fd, operacion, argumento=0):
                        if operacion == termios.TIOCMBIC:
                            actual = struct.unpack("I", argumento)[0]
                            lineas.append(actual)
                            if actual == linea:
                                raise OSError(codigo, "Control no disponible")
                            return 0
                        return ioctl_real(fd, operacion, argumento)

                    with patch("puerto_serie.fcntl.ioctl", side_effect=ioctl):
                        with PuertoSerie(self.ruta):
                            esperadas = [termios.TIOCM_DTR]
                            if linea == termios.TIOCM_RTS:
                                esperadas.append(termios.TIOCM_RTS)
                            self.assertEqual(lineas, esperadas)

    def test_otro_error_libera_descriptor_y_exclusividad(self):
        for linea in (termios.TIOCM_DTR, termios.TIOCM_RTS):
            with self.subTest(linea=linea):
                ioctl_real = fcntl.ioctl
                descriptores = []
                liberados = []

                def ioctl(fd, operacion, argumento=0):
                    if operacion == termios.TIOCMBIC:
                        descriptores.append(fd)
                        if struct.unpack("I", argumento)[0] == linea:
                            raise OSError(errno.EIO, "Fallo del dispositivo")
                        return 0
                    if operacion == termios.TIOCNXCL:
                        liberados.append(fd)
                    return ioctl_real(fd, operacion, argumento)

                with patch("puerto_serie.fcntl.ioctl", side_effect=ioctl):
                    with self.assertRaises(OSError) as error:
                        PuertoSerie(self.ruta)
                    self.assertEqual(error.exception.errno, errno.EIO)
                    self.assertEqual(liberados, [descriptores[-1]])
                    with self.assertRaises(OSError) as cerrado:
                        os.fstat(descriptores[-1])
                    self.assertEqual(cerrado.exception.errno, errno.EBADF)
                descriptor = os.open(self.ruta, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                os.close(descriptor)


if __name__ == "__main__":
    unittest.main()
