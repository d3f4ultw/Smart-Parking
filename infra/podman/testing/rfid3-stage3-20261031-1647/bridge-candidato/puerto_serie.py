"""Transporte USB serie POSIX para el lector RFID 1."""

import errno
import fcntl
import glob
import os
import select
import struct
import termios
import time


VELOCIDAD_SERIE = 115200
TAMANO_MAXIMO_TRAMA = 512


class ErrorProtocolo(Exception):
    """Indica una trama serial incompatible o demasiado larga."""


def detectar_puertos():
    """Devuelve los puertos USB serie comunes sin cambiar permisos."""
    puertos = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    return sorted(set(puertos))


def seleccionar_puerto(solicitado=None):
    """Selecciona el puerto indicado o el único puerto accesible."""
    if solicitado:
        if not os.path.exists(solicitado):
            raise FileNotFoundError("No existe el puerto serie indicado.")
        if not os.access(solicitado, os.R_OK | os.W_OK):
            raise PermissionError("No hay permisos para abrir el puerto serie.")
        return solicitado

    disponibles = detectar_puertos()
    accesibles = [
        puerto for puerto in disponibles
        if os.access(puerto, os.R_OK | os.W_OK)
    ]
    if len(accesibles) == 1:
        return accesibles[0]
    if not accesibles:
        if disponibles:
            raise PermissionError("No hay permisos para abrir puertos USB serie.")
        raise FileNotFoundError("No se detectaron puertos USB serie.")
    raise ErrorProtocolo("Hay varios puertos accesibles; indique --port.")


class PuertoSerie:
    """Abre un TTY con exclusividad, LF framing y lectura no bloqueante."""

    def __init__(self, ruta, velocidad=VELOCIDAD_SERIE):
        self.ruta = ruta
        self.buffer = bytearray()
        self.descartando_trama = False
        self.fd = os.open(
            ruta, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK
        )
        self.exclusivo = False
        try:
            fcntl.ioctl(self.fd, termios.TIOCEXCL)
            self.exclusivo = True
            atributos = termios.tcgetattr(self.fd)
            atributos[0] = 0
            atributos[1] = 0
            atributos[2] = termios.CS8 | termios.CLOCAL | termios.CREAD
            atributos[3] = 0
            codigo_velocidad = getattr(
                termios, "B{}".format(velocidad), None
            )
            if codigo_velocidad is None:
                raise ValueError("La velocidad serie no es compatible.")
            atributos[4] = codigo_velocidad
            atributos[5] = codigo_velocidad
            atributos[6][termios.VMIN] = 0
            atributos[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, atributos)
            try:
                # Conservamos la secuencia de apertura probada en la placa.
                fcntl.ioctl(self.fd, termios.TIOCMBIC, struct.pack("I", termios.TIOCM_DTR))
                fcntl.ioctl(self.fd, termios.TIOCMBIC, struct.pack("I", termios.TIOCM_RTS))
            except OSError as error:
                if error.errno not in (errno.ENOTTY, errno.EINVAL):
                    raise
            termios.tcflush(self.fd, termios.TCIOFLUSH)
        except Exception:
            try:
                self.cerrar()
            except OSError:
                pass
            raise

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, traza):
        self.cerrar()

    def cerrar(self):
        """Libera el descriptor y la exclusividad del TTY."""
        descriptor = self.fd
        if descriptor is None:
            return
        self.fd = None
        try:
            if self.exclusivo:
                try:
                    fcntl.ioctl(descriptor, termios.TIOCNXCL)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
        finally:
            self.exclusivo = False
            os.close(descriptor)

    def escribir_linea(self, linea, tiempo_espera=3):
        """Escribe una trama ASCII terminada en CRLF para el ESP32 real."""
        if not isinstance(linea, str) or "\n" in linea or "\r" in linea:
            raise ValueError("La trama serial debe ser una sola línea.")
        self.escribir((linea + "\r\n").encode("ascii"), tiempo_espera)

    def escribir(self, datos, tiempo_espera=3):
        """Completa una escritura aunque el descriptor no bloquee."""
        vista = memoryview(datos)
        limite = time.monotonic() + tiempo_espera
        while vista:
            restante = limite - time.monotonic()
            if restante <= 0:
                raise TimeoutError("Se agotó el tiempo de escritura serial.")
            _, listos, _ = select.select([], [self.fd], [], restante)
            if not listos:
                continue
            try:
                cantidad = os.write(self.fd, vista)
            except BlockingIOError:
                continue
            if cantidad <= 0:
                raise OSError("El puerto serie se desconectó.")
            vista = vista[cantidad:]

    def _leer_mas(self, limite):
        restante = limite - time.monotonic()
        if restante <= 0:
            return False
        listos, _, _ = select.select([self.fd], [], [], restante)
        if not listos:
            return False
        try:
            datos = os.read(self.fd, 4096)
        except BlockingIOError:
            return True
        if not datos:
            raise OSError("El puerto serie se desconectó.")
        self.buffer.extend(datos)
        return True

    def leer_linea(self, tiempo_espera=0.2):
        """Lee una trama LF; los fragmentos permanecen en un buffer acotado."""
        limite = time.monotonic() + tiempo_espera
        while True:
            separador = self.buffer.find(b"\n")
            if self.descartando_trama:
                if separador >= 0:
                    del self.buffer[:separador + 1]
                    self.descartando_trama = False
                    raise ErrorProtocolo("La trama serial excede el límite.")
                self.buffer.clear()
            elif separador >= 0:
                trama = bytes(self.buffer[:separador])
                del self.buffer[:separador + 1]
                if len(trama) > TAMANO_MAXIMO_TRAMA:
                    raise ErrorProtocolo("La trama serial excede el límite.")
                if trama.endswith(b"\r"):
                    trama = trama[:-1]
                try:
                    return trama.decode("ascii")
                except UnicodeDecodeError as error:
                    raise ErrorProtocolo("La trama serial no es ASCII.") from error
            elif len(self.buffer) > TAMANO_MAXIMO_TRAMA:
                self.buffer.clear()
                self.descartando_trama = True

            if not self._leer_mas(limite):
                return None
