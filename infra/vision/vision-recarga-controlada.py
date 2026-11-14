"""Supervisa una única ejecución Vision y recarga cambios de código con cierre limpio."""

from __future__ import annotations

import hashlib
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


DIRECTORIO_CODIGO = Path("/app")
INTERVALO_SEGUNDOS = 1.0
DEMORA_ESTABILIDAD_SEGUNDOS = 0.6
ESPERA_CIERRE_SEGUNDOS = 18


def calcular_huella(directorio: Path) -> str:
    """Crea una huella ordenada solo de las fuentes Python supervisadas."""
    resumen = hashlib.sha256()
    archivos = sorted(ruta for ruta in directorio.rglob("*.py") if "__pycache__" not in ruta.parts)
    for ruta in archivos:
        resumen.update(ruta.relative_to(directorio).as_posix().encode("utf-8"))
        resumen.update(b"\0")
        try:
            with ruta.open("rb") as archivo:
                for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
                    resumen.update(bloque)
        except FileNotFoundError:
            # Un archivo puede desaparecer durante un cambio; el siguiente ciclo
            # observará la lista estable después de que termine la edición.
            continue
        resumen.update(b"\0")
    return resumen.hexdigest()


class RecargaControlada:
    """Detiene y espera al detector antes de lanzar una nueva instancia."""

    def __init__(self, comando: list[str]) -> None:
        self.comando = comando
        self.proceso: subprocess.Popen[str] | None = None
        self.hilo_salida: threading.Thread | None = None
        self.captura_liberada = False
        self.cerrar = False

    def copiar_salida(self, proceso: subprocess.Popen[str]) -> None:
        """Conserva los logs del detector y confirma su liberación de captura."""
        assert proceso.stdout is not None
        for linea in proceso.stdout:
            texto = linea.rstrip("\n")
            print(texto, flush=True)
            if texto == "Captura liberada.":
                self.captura_liberada = True

    def enviar_sigterm(self, proceso: subprocess.Popen[str]) -> None:
        try:
            if proceso.poll() is None:
                proceso.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass

    def solicitar_cierre(self, numero: int, _marco: object) -> None:
        self.cerrar = True
        proceso = self.proceso
        if proceso is not None and proceso.poll() is None:
            print(f"[recarga-vision] Señal {numero}; esperando el cierre limpio del detector.", flush=True)
            self.enviar_sigterm(proceso)

    def detener_detector(self) -> int:
        proceso = self.proceso
        if proceso is None:
            return 0
        try:
            estado = proceso.wait(timeout=ESPERA_CIERRE_SEGUNDOS)
        except subprocess.TimeoutExpired:
            print("[recarga-vision] El detector excedió el límite de cierre; se detiene el runtime.",
                  file=sys.stderr, flush=True)
            proceso.kill()
            proceso.wait()
            return 1
        finally:
            if self.hilo_salida is not None:
                self.hilo_salida.join(timeout=2)
                self.hilo_salida = None
            self.proceso = None
        return estado

    def ejecutar(self) -> int:
        huella_anterior = calcular_huella(DIRECTORIO_CODIGO)
        while not self.cerrar:
            self.captura_liberada = False
            self.proceso = subprocess.Popen(
                self.comando,
                cwd=DIRECTORIO_CODIGO,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            self.hilo_salida = threading.Thread(
                target=self.copiar_salida, args=(self.proceso,), daemon=True,
            )
            self.hilo_salida.start()
            print(f"[recarga-vision] Detector único iniciado (pid={self.proceso.pid}).", flush=True)
            if self.cerrar:
                self.enviar_sigterm(self.proceso)

            while not self.cerrar:
                proceso = self.proceso
                if proceso is None:
                    return 1
                estado = proceso.poll()
                if estado is not None:
                    estado = self.detener_detector()
                    if self.cerrar and (estado != 0 or not self.captura_liberada):
                        return estado or 1
                    return estado

                time.sleep(INTERVALO_SEGUNDOS)
                huella_actual = calcular_huella(DIRECTORIO_CODIGO)
                if huella_actual == huella_anterior:
                    continue

                time.sleep(DEMORA_ESTABILIDAD_SEGUNDOS)
                huella_estable = calcular_huella(DIRECTORIO_CODIGO)
                if huella_estable != huella_actual:
                    continue

                print("[recarga-vision] Cambio estable en Python; solicitando SIGTERM al detector.",
                      flush=True)
                self.enviar_sigterm(proceso)
                estado = self.detener_detector()
                if estado != 0 or not self.captura_liberada:
                    print(f"[recarga-vision] El detector terminó con estado {estado}; no habrá solapamiento.",
                          file=sys.stderr, flush=True)
                    return estado or 1
                print("[recarga-vision] Detector terminado; captura liberada y modelo descargado.", flush=True)
                huella_anterior = calcular_huella(DIRECTORIO_CODIGO)
                break

            if self.cerrar and self.proceso is not None:
                estado = self.detener_detector()
                if estado != 0 or not self.captura_liberada:
                    return estado or 1
                print("[recarga-vision] Cierre del detector confirmado.", flush=True)
                return 0

        return 0


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] != "--":
        print("Uso interno: vision-recarga-controlada.py -- COMANDO [ARGUMENTOS...]", file=sys.stderr)
        return 2

    supervisor = RecargaControlada(sys.argv[2:])
    signal.signal(signal.SIGTERM, supervisor.solicitar_cierre)
    signal.signal(signal.SIGINT, supervisor.solicitar_cierre)
    return supervisor.ejecutar()


if __name__ == "__main__":
    raise SystemExit(main())
