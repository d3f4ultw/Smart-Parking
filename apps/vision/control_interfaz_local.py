"""Recibe solicitudes locales para mostrar la ventana de Vision ya en ejecución."""

from __future__ import annotations

import json
import os
import queue
import re
import socket
import stat
import struct
import threading
from pathlib import Path

MAXIMO = 512
TIEMPO = 15.0
_DISPLAY = re.compile(r"^:[0-9]{1,5}(?:\.[0-9]{1,3})?$")


class ControlInterfaz:
    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        self._pedidos = queue.Queue(maxsize=1)
        self._cerrar = threading.Event()
        self._servidor = None
        self._hilo = None

    def iniciar(self):
        carpeta = self.ruta.parent.lstat()
        if (not stat.S_ISDIR(carpeta.st_mode) or carpeta.st_uid != os.getuid()
                or stat.S_IMODE(carpeta.st_mode) != 0o700):
            raise ValueError("El directorio del control Vision debe ser privado y propio.")
        try:
            previo = self.ruta.lstat()
        except FileNotFoundError:
            previo = None
        if previo is not None:
            if not stat.S_ISSOCK(previo.st_mode) or previo.st_uid != os.getuid():
                raise ValueError("La ruta de control Vision no es un socket propio.")
            prueba = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                prueba.settimeout(0.5)
                prueba.connect(str(self.ruta))
            except (ConnectionRefusedError, FileNotFoundError):
                self.ruta.unlink(missing_ok=True)
            else:
                raise ValueError("Ya existe un control Vision activo.")
            finally:
                prueba.close()
        servidor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            servidor.bind(str(self.ruta))
            os.chmod(self.ruta, 0o600)
            servidor.listen(4)
            servidor.settimeout(0.2)
        except BaseException:
            servidor.close()
            raise
        self._servidor = servidor
        self._hilo = threading.Thread(target=self._atender, name="vision-control-ui", daemon=True)
        self._hilo.start()

    def _atender(self):
        while not self._cerrar.is_set():
            try:
                conexion, _ = self._servidor.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conexion:
                conexion.settimeout(TIEMPO)
                try:
                    _, uid, _ = struct.unpack("3i", conexion.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    if uid != os.getuid():
                        continue
                    datos = bytearray()
                    while b"\n" not in datos and len(datos) <= MAXIMO:
                        bloque = conexion.recv(MAXIMO + 1 - len(datos))
                        if not bloque:
                            break
                        datos.extend(bloque)
                    if len(datos) > MAXIMO or not datos.endswith(b"\n"):
                        raise ValueError("Mensaje invalido")
                    solicitud = json.loads(datos)
                    if (not isinstance(solicitud, dict) or set(solicitud) != {"version", "comando", "display"}
                            or solicitud["version"] != 1 or solicitud["comando"] != "mostrar"
                            or not isinstance(solicitud["display"], str)
                            or not _DISPLAY.fullmatch(solicitud["display"])):
                        raise ValueError("Solicitud invalida")
                    pedido = {"display": solicitud["display"], "terminado": threading.Event(),
                              "cancelado": threading.Event(), "resultado": False}
                    self._pedidos.put_nowait(pedido)
                    if not pedido["terminado"].wait(TIEMPO - 1):
                        pedido["cancelado"].set()
                    respuesta = {"version": 1, "aceptado": pedido["resultado"]}
                except (ValueError, json.JSONDecodeError, UnicodeDecodeError, OSError, queue.Full):
                    respuesta = {"version": 1, "aceptado": False}
                try:
                    conexion.sendall(json.dumps(respuesta, separators=(",", ":")).encode() + b"\n")
                except OSError:
                    pass

    def siguiente(self):
        try:
            return self._pedidos.get_nowait()
        except queue.Empty:
            return None

    @staticmethod
    def responder(pedido, aceptado):
        pedido["resultado"] = bool(aceptado)
        pedido["terminado"].set()

    def cerrar(self):
        self._cerrar.set()
        if self._servidor is not None:
            self._servidor.close()
        if self._hilo is not None:
            self._hilo.join(timeout=TIEMPO + 0.5)
        try:
            estado = self.ruta.lstat()
            if stat.S_ISSOCK(estado.st_mode) and estado.st_uid == os.getuid():
                self.ruta.unlink()
        except FileNotFoundError:
            pass


def solicitar_mostrar(ruta: Path, display: str) -> bool:
    if not _DISPLAY.fullmatch(display):
        return False
    mensaje = json.dumps({"version": 1, "comando": "mostrar", "display": display},
                         separators=(",", ":")).encode() + b"\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as cliente:
            cliente.settimeout(TIEMPO + 1)
            cliente.connect(str(ruta))
            cliente.sendall(mensaje)
            respuesta = cliente.recv(MAXIMO + 1)
        return len(respuesta) <= MAXIMO and json.loads(respuesta) == {"version": 1, "aceptado": True}
    except (OSError, ValueError, json.JSONDecodeError):
        return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3 or not solicitar_mostrar(Path(sys.argv[1]), sys.argv[2]):
        raise SystemExit(1)
