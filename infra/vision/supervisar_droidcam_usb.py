#!/usr/bin/env python3
"""Mantiene el forward USB de Vision sin administrar otros forwards ADB."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import signal
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


RAIZ = Path(__file__).resolve().parents[2]
ADB_PREDETERMINADO = RAIZ / "var/vision/tools/droidcam-adb-37.0.0p1-1/adb"
DISPOSITIVO_PREDETERMINADO = RAIZ / "var/vision/config/adb-device-id.txt"
ESTADO_PREDETERMINADO = RAIZ / "var/vision/cache/droidcam-usb-forward.json"
PUERTO_SERVIDOR_ADB_PREDETERMINADO = 5038
PUERTO_LOCAL_PREDETERMINADO = 14747
PUERTO_ANDROID_PREDETERMINADO = 4747
REINTENTO_INICIAL_SEGUNDOS = 5
REINTENTO_MAXIMO_SEGUNDOS = 30
PATRON_IDENTIFICADOR = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


@dataclass(frozen=True)
class Configuracion:
    ejecutable_adb: Path
    archivo_dispositivo: Path
    archivo_estado: Path
    puerto_servidor_adb: int
    puerto_local: int
    puerto_android: int
    timeout_segundos: float = 5.0


class SupervisorDroidCamUSB:
    """Vigila un teléfono seleccionado y un único forward local reservado."""

    def __init__(self, configuracion: Configuracion) -> None:
        self.configuracion = configuracion
        self.detener = threading.Event()
        self._ultimo_estado: str | None = None

    def ejecutar_una_vez(self) -> bool:
        """Comprueba el dispositivo y restaura el forward si falta."""
        dispositivo = self._resolver_dispositivo()
        if dispositivo is None:
            return False

        forwards = self._listar_forwards()
        if forwards is None:
            self._registrar("ADB no respondió; se reintentará con espera creciente.")
            return False

        local = f"tcp:{self.configuracion.puerto_local}"
        remoto = f"tcp:{self.configuracion.puerto_android}"
        exacto = (dispositivo, local, remoto)
        if exacto in forwards:
            self._guardar_estado(dispositivo, administrado=self._estado_es_propio(dispositivo))
            self._registrar("El forward USB de Vision está disponible.")
            return True

        if any(forward[1] == local for forward in forwards):
            self._registrar("El puerto local reservado por Vision tiene otro propietario; no se modificó.")
            return False

        resultado = self._ejecutar_adb(
            [
                "-P",
                str(self.configuracion.puerto_servidor_adb),
                "-s",
                dispositivo,
                "forward",
                "--no-rebind",
                local,
                remoto,
            ]
        )
        if resultado is None or resultado.returncode != 0:
            self._registrar("No se pudo crear el forward USB de Vision; se reintentará.")
            return False

        forwards = self._listar_forwards()
        if forwards is None or exacto not in forwards:
            self._registrar("ADB no confirmó el forward USB de Vision; se reintentará.")
            return False

        self._guardar_estado(dispositivo, administrado=True)
        self._registrar("Se creó y verificó el forward USB de Vision en loopback.")
        return True

    def ejecutar(self) -> None:
        """Reintenta con backoff y retira únicamente el forward propio al parar."""
        espera = REINTENTO_INICIAL_SEGUNDOS
        while not self.detener.is_set():
            listo = self.ejecutar_una_vez()
            espera = REINTENTO_INICIAL_SEGUNDOS if listo else min(
                espera * 2, REINTENTO_MAXIMO_SEGUNDOS
            )
            self.detener.wait(espera)
        self._retirar_forward_propio()

    def solicitar_detencion(self, _senal: int, _marco: object) -> None:
        self.detener.set()

    def _resolver_dispositivo(self) -> str | None:
        override_presente, dispositivo = self._leer_override()
        if override_presente:
            if dispositivo is None:
                self._registrar("El override privado del dispositivo no es válido; Vision queda esperando.")
                return None
        else:
            dispositivo = self._detectar_dispositivo_unico()
            if dispositivo is None:
                self._registrar("No se detectó exactamente un Android autorizado; Vision queda esperando.")
                return None

        ancla = self._huella_anclada()
        if ancla is not None and ancla != self._huella_dispositivo(dispositivo):
            self._registrar("El Android detectado no coincide con el dispositivo previamente confirmado; Vision queda esperando.")
            return None
        if not self._dispositivo_autorizado(dispositivo):
            self._registrar("El dispositivo Android no está autorizado o conectado; Vision queda esperando.")
            return None
        return dispositivo

    def _leer_override(self) -> tuple[bool, str | None]:
        archivo = self.configuracion.archivo_dispositivo
        try:
            estado = archivo.lstat()
        except FileNotFoundError:
            return False, None
        except OSError:
            return True, None
        if not stat.S_ISREG(estado.st_mode):
            self._registrar("El override privado del dispositivo no es un archivo regular.")
            return True, None
        try:
            permisos = stat.S_IMODE(estado.st_mode)
            if permisos & 0o077:
                self._registrar("El archivo privado del dispositivo requiere permisos 0600 o más restrictivos.")
                return True, None
            lineas = archivo.read_text(encoding="utf-8").splitlines()
        except OSError:
            return True, None
        if len(lineas) != 1:
            return True, None
        dispositivo = lineas[0].strip()
        if not PATRON_IDENTIFICADOR.fullmatch(dispositivo):
            return True, None
        return True, dispositivo

    def _detectar_dispositivo_unico(self) -> str | None:
        resultado = self._ejecutar_adb(
            ["-P", str(self.configuracion.puerto_servidor_adb), "devices"]
        )
        if resultado is None or resultado.returncode != 0:
            return None
        filas = []
        for linea in resultado.stdout.splitlines():
            texto = linea.strip()
            if not texto or texto.startswith("List of devices attached"):
                continue
            partes = texto.split()
            if len(partes) < 2:
                return None
            filas.append(partes)
        if len(filas) != 1 or filas[0][1] != "device":
            return None
        dispositivo = filas[0][0]
        return dispositivo if PATRON_IDENTIFICADOR.fullmatch(dispositivo) else None

    def _dispositivo_autorizado(self, dispositivo: str) -> bool:
        resultado = self._ejecutar_adb(
            ["-P", str(self.configuracion.puerto_servidor_adb), "-s", dispositivo, "get-state"]
        )
        return resultado is not None and resultado.returncode == 0 and resultado.stdout.strip() == "device"

    def _listar_forwards(self) -> set[tuple[str, str, str]] | None:
        resultado = self._ejecutar_adb(
            ["-P", str(self.configuracion.puerto_servidor_adb), "forward", "--list"]
        )
        if resultado is None or resultado.returncode != 0:
            return None
        forwards: set[tuple[str, str, str]] = set()
        for linea in resultado.stdout.splitlines():
            partes = linea.split()
            if len(partes) == 3:
                forwards.add((partes[0], partes[1], partes[2]))
        return forwards

    def _ejecutar_adb(self, argumentos: Sequence[str]) -> subprocess.CompletedProcess[str] | None:
        ejecutable = self.configuracion.ejecutable_adb
        if not ejecutable.is_file() or not os.access(ejecutable, os.X_OK):
            self._registrar("El cliente ADB privado de Vision no está disponible.")
            return None

        # DroidCam distribuye libfmt junto a ADB; solo el subproceso ADB usa esa ruta.
        entorno = os.environ.copy()
        biblioteca = str(ejecutable.parent / "lib")
        entorno["LD_LIBRARY_PATH"] = biblioteca
        try:
            return subprocess.run(
                [str(ejecutable), *argumentos],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.configuracion.timeout_segundos,
                env=entorno,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _guardar_estado(self, dispositivo: str, administrado: bool) -> None:
        archivo = self.configuracion.archivo_estado
        archivo.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        huella_dispositivo = hashlib.sha256(dispositivo.encode("utf-8")).hexdigest()
        estado = {
            "dispositivoSha256": huella_dispositivo,
            "puertoLocal": self.configuracion.puerto_local,
            "puertoAndroid": self.configuracion.puerto_android,
            "administradoPorVision": administrado,
        }
        descriptor, ruta_temporal = tempfile.mkstemp(
            prefix=f".{archivo.name}.", suffix=".tmp", dir=archivo.parent
        )
        temporal = Path(ruta_temporal)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as salida:
                json.dump(estado, salida, ensure_ascii=False, sort_keys=True)
                salida.write("\n")
                salida.flush()
                os.fsync(salida.fileno())
            os.replace(temporal, archivo)
            os.chmod(archivo, 0o600)
            descriptor_directorio = os.open(archivo.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor_directorio)
            finally:
                os.close(descriptor_directorio)
        except Exception:
            temporal.unlink(missing_ok=True)
            raise

    def _retirar_forward_propio(self) -> None:
        dispositivo = self._resolver_dispositivo()
        if dispositivo is None or not self._estado_es_propio(dispositivo):
            return
        if not self._dispositivo_autorizado(dispositivo):
            return
        forwards = self._listar_forwards()
        exacto = (
            dispositivo,
            f"tcp:{self.configuracion.puerto_local}",
            f"tcp:{self.configuracion.puerto_android}",
        )
        if forwards is None or exacto not in forwards:
            self.configuracion.archivo_estado.unlink(missing_ok=True)
            return
        resultado = self._ejecutar_adb(
            [
                "-P",
                str(self.configuracion.puerto_servidor_adb),
                "-s",
                dispositivo,
                "forward",
                "--remove",
                exacto[1],
            ]
        )
        if resultado is not None and resultado.returncode == 0:
            self.configuracion.archivo_estado.unlink(missing_ok=True)
            self._registrar("Se retiró únicamente el forward USB de Vision.")
        else:
            self._registrar("ADB no confirmó la retirada del forward propio; no se tocaron otros recursos.")

    def _estado_es_propio(self, dispositivo: str) -> bool:
        try:
            datos = json.loads(self.configuracion.archivo_estado.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(datos, dict):
            return False
        huella = hashlib.sha256(dispositivo.encode("utf-8")).hexdigest()
        return (
            datos.get("administradoPorVision") is True
            and datos.get("dispositivoSha256") == huella
            and datos.get("puertoLocal") == self.configuracion.puerto_local
            and datos.get("puertoAndroid") == self.configuracion.puerto_android
        )

    def _huella_anclada(self) -> str | None:
        try:
            datos = json.loads(self.configuracion.archivo_estado.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(datos, dict):
            return None
        huella = datos.get("dispositivoSha256")
        if (
            datos.get("puertoLocal") != self.configuracion.puerto_local
            or datos.get("puertoAndroid") != self.configuracion.puerto_android
            or not isinstance(huella, str)
            or not re.fullmatch(r"[0-9a-f]{64}", huella)
        ):
            return None
        return huella

    @staticmethod
    def _huella_dispositivo(dispositivo: str) -> str:
        return hashlib.sha256(dispositivo.encode("utf-8")).hexdigest()

    def _registrar(self, mensaje: str) -> None:
        if mensaje != self._ultimo_estado:
            logging.info(mensaje)
            self._ultimo_estado = mensaje


def crear_argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", type=Path, default=Path(os.environ.get("VISION_ADB_BIN", ADB_PREDETERMINADO)))
    parser.add_argument(
        "--dispositivo",
        type=Path,
        default=Path(os.environ.get("VISION_ADB_DEVICE_FILE", DISPOSITIVO_PREDETERMINADO)),
    )
    parser.add_argument(
        "--estado",
        type=Path,
        default=Path(os.environ.get("VISION_ADB_FORWARD_STATE", ESTADO_PREDETERMINADO)),
    )
    parser.add_argument(
        "--puerto-servidor-adb",
        type=int,
        default=int(os.environ.get("VISION_ADB_SERVER_PORT", PUERTO_SERVIDOR_ADB_PREDETERMINADO)),
    )
    parser.add_argument(
        "--puerto-local",
        type=int,
        default=int(os.environ.get("VISION_ADB_LOCAL_PORT", PUERTO_LOCAL_PREDETERMINADO)),
    )
    parser.add_argument(
        "--puerto-android",
        type=int,
        default=int(os.environ.get("VISION_ADB_REMOTE_PORT", PUERTO_ANDROID_PREDETERMINADO)),
    )
    argumentos = parser.parse_args()
    if not 1024 <= argumentos.puerto_servidor_adb <= 65535:
        parser.error("El puerto del servidor ADB debe estar entre 1024 y 65535.")
    if not 1024 <= argumentos.puerto_local <= 65535:
        parser.error("El puerto local debe estar entre 1024 y 65535.")
    if not 1 <= argumentos.puerto_android <= 65535:
        parser.error("El puerto Android debe estar entre 1 y 65535.")
    return argumentos


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    argumentos = crear_argumentos()
    configuracion = Configuracion(
        ejecutable_adb=argumentos.adb.resolve(),
        archivo_dispositivo=argumentos.dispositivo.resolve(),
        archivo_estado=argumentos.estado.resolve(),
        puerto_servidor_adb=argumentos.puerto_servidor_adb,
        puerto_local=argumentos.puerto_local,
        puerto_android=argumentos.puerto_android,
    )
    supervisor = SupervisorDroidCamUSB(configuracion)
    signal.signal(signal.SIGTERM, supervisor.solicitar_detencion)
    signal.signal(signal.SIGINT, supervisor.solicitar_detencion)
    supervisor.ejecutar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
