"""Conecta un bridge real a la API candidata mediante un pseudo-terminal."""

from __future__ import annotations

import errno
import os
import pty
import select
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path
from http_aceptacion import ClienteHttp


def exigir(condicion: bool, nombre: str) -> None:
    if not condicion:
        raise RuntimeError(f"FAIL: {nombre}")
    print(f"PASS: {nombre}")


def escribir(fd: int, linea: str) -> None:
    os.write(fd, (linea + "\n").encode("ascii"))


def leer_linea(fd: int, buffer: bytearray, plazo: float) -> str | None:
    while time.monotonic() < plazo:
        separador = buffer.find(b"\n")
        if separador >= 0:
            trama = bytes(buffer[:separador]).rstrip(b"\r")
            del buffer[:separador + 1]
            return trama.decode("ascii")
        listo, _, _ = select.select([fd], [], [], min(0.25, plazo - time.monotonic()))
        if not listo:
            continue
        try:
            bloque = os.read(fd, 1024)
        except OSError as excepcion:
            if excepcion.errno == errno.EIO:
                time.sleep(0.05)
                continue
            raise
        if bloque:
            buffer.extend(bloque)
    return None


def leer_hasta(
    fd: int,
    buffer: bytearray,
    plazo: float,
    predicado,
    observadas=None,
) -> str | None:
    while time.monotonic() < plazo:
        linea = leer_linea(fd, buffer, plazo)
        if linea is None:
            continue
        if observadas is not None:
            observadas.append(linea)
        if linea == "PING":
            escribir(fd, "PONG")
        if predicado(linea):
            return linea
    return None


def probar_serial(
    base_url: str,
    token: str,
    cliente_dueno,
    token_csrf: str,
    codigo_empleado: str,
    crear_captura,
    exigir_api,
) -> tuple[list[str], str]:
    respuesta = crear_captura(cliente_dueno, token_csrf, "EMPLEADO", codigo_empleado)
    exigir_api(respuesta.estado == 201, "captura sintética para integración serial")
    captura_id = respuesta.json()["capturaId"]
    uid = secrets.token_hex(4).upper()
    request_id = secrets.token_hex(2).upper()
    serial_fd, dispositivo_fd = pty.openpty()
    ruta_pty = os.ttyname(dispositivo_fd)
    os.close(dispositivo_fd)

    raiz = Path(__file__).resolve().parents[4]
    entorno = os.environ.copy()
    entorno["SMARTPARKING_RFID1_API_URL"] = base_url
    entorno["SMARTPARKING_RFID1_TOKEN"] = token
    bridge = subprocess.Popen(
        [sys.executable, str(raiz / "infra/rfid1-bridge/bridge.py"), "--port", ruta_pty],
        cwd=raiz,
        env=entorno,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    buffer = bytearray()
    salida = ""
    try:
        armado = leer_hasta(
            serial_fd,
            buffer,
            time.monotonic() + 12,
            lambda linea: linea.startswith("ENROLL_ARM,"),
        )
        exigir(armado == f"ENROLL_ARM,{captura_id}", "bridge arma la captura confirmada por API")

        escribir(serial_fd, f"ENROLL_STATE,{captura_id},SCANNING")
        escribir(serial_fd, f"ENROLL_READ,{captura_id},{request_id},{uid}")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            estado = cliente_dueno.solicitar("GET", f"/api/v1/rfid-1/capturas/{captura_id}")
            if estado.estado == 200 and estado.json().get("estado") in ("COMPLETADA", "RECHAZADA"):
                break
            linea = leer_linea(serial_fd, buffer, min(deadline, time.monotonic() + 0.5))
            if linea == "PING":
                escribir(serial_fd, "PONG")
        exigir(estado.estado == 200 and estado.json().get("estado") == "COMPLETADA",
               "ENROLL_STATE y ENROLL_READ completan la asociación por HTTP")

        secuencia = "00AA"
        uid_ordinario = secrets.token_hex(4).upper()
        escribir(serial_fd, f"RFID,{secuencia},{uid_ordinario}")
        resultados = set()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and f"RESULT,{secuencia},DENY" not in resultados:
            linea = leer_linea(serial_fd, buffer, deadline)
            if linea is None:
                continue
            if linea == "PING":
                escribir(serial_fd, "PONG")
            if linea.startswith("RESULT,"):
                resultados.add(linea)
        exigir(f"RESULT,{secuencia},DENY" in resultados, "lectura ordinaria termina en DENY")
        exigir(not any(linea.endswith(",ALLOW") for linea in resultados), "bridge nunca emite ALLOW")
        escribir(serial_fd, f"RESULT_ACK,{secuencia},DENY")
    finally:
        bridge.terminate()
        try:
            salida, _ = bridge.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            bridge.kill()
            salida, _ = bridge.communicate(timeout=5)
        os.close(serial_fd)

    exigir(uid not in salida and token not in salida, "diagnósticos bridge omiten UID y token")
    return [uid, uid_ordinario], salida


def probar_reinicio_serial(
    base_url: str,
    token: str,
    cliente_dueno,
    token_csrf: str,
    codigo_empleado: str,
    crear_captura,
    exigir_api,
) -> tuple[list[str], str]:
    respuesta = crear_captura(cliente_dueno, token_csrf, "EMPLEADO", codigo_empleado)
    exigir_api(respuesta.estado == 201, "captura sintética para reconciliación tras reinicio")
    captura_id = respuesta.json()["capturaId"]
    serial_fd, dispositivo_fd = pty.openpty()
    ruta_pty = os.ttyname(dispositivo_fd)
    os.close(dispositivo_fd)
    raiz = Path(__file__).resolve().parents[4]
    entorno = os.environ.copy()
    entorno["SMARTPARKING_RFID1_API_URL"] = base_url
    entorno["SMARTPARKING_RFID1_TOKEN"] = token
    buffer = bytearray()
    salidas = []
    proceso_actual = None

    def iniciar():
        return subprocess.Popen(
            [sys.executable, str(raiz / "infra/rfid1-bridge/bridge.py"), "--port", ruta_pty],
            cwd=raiz,
            env=entorno,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def detener(proceso):
        proceso.terminate()
        try:
            salida, _ = proceso.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proceso.kill()
            salida, _ = proceso.communicate(timeout=5)
        salidas.append(salida)

    try:
        proceso_actual = iniciar()
        armado = leer_hasta(
            serial_fd, buffer, time.monotonic() + 12,
            lambda linea: linea.startswith("ENROLL_ARM,"),
        )
        exigir_api(armado == f"ENROLL_ARM,{captura_id}", "primer bridge arma captura pendiente")
        detener(proceso_actual)
        proceso_actual = None

        proceso_actual = iniciar()
        tramas_reinicio = []
        rearmado = leer_hasta(
            serial_fd, buffer, time.monotonic() + 12,
            lambda linea: linea.startswith("ENROLL_ARM,"),
            tramas_reinicio,
        )
        if rearmado != f"ENROLL_ARM,{captura_id}":
            estado_api = ClienteHttp(base_url, bearer=token).solicitar(
                "GET", "/api/v1/dispositivos/rfid-1/capturas/activa"
            )
            detener(proceso_actual)
            proceso_actual = None
            consulta_error = "No se pudo consultar la captura" in salidas[-1]
            puerto_abierto = "Puerto USB serie abierto en modo exclusivo." in salidas[-1]
            error_usb = "USB no disponible" in salidas[-1]
            prefijos = ",".join(sorted({linea.split(",", 1)[0] for linea in tramas_reinicio}))
            raise RuntimeError(
                "FAIL: bridge reiniciado no rearmó captura; "
                f"http_activa={estado_api.estado}; arm_observado="
                f"{any(linea.startswith('ENROLL_ARM,') for linea in tramas_reinicio)}; "
                f"consulta_error={consulta_error}; puerto_abierto={puerto_abierto}; "
                f"error_usb={error_usb}; tramas={prefijos or 'ninguna'}"
            )
        exigir_api(True, "bridge reiniciado reconcilia la captura desde el servidor")
        request_id = secrets.token_hex(2).upper()
        uid = secrets.token_hex(4).upper()
        escribir(serial_fd, f"ENROLL_STATE,{captura_id},SCANNING")
        escribir(serial_fd, f"ENROLL_READ,{captura_id},{request_id},{uid}")
        deadline = time.monotonic() + 10
        estado = None
        while time.monotonic() < deadline:
            estado = cliente_dueno.solicitar("GET", f"/api/v1/rfid-1/capturas/{captura_id}")
            if estado.estado == 200 and estado.json().get("estado") in ("COMPLETADA", "RECHAZADA"):
                break
            linea = leer_linea(serial_fd, buffer, min(deadline, time.monotonic() + 0.5))
            if linea == "PING":
                escribir(serial_fd, "PONG")
        exigir_api(estado is not None and estado.estado == 200
                   and estado.json().get("estado") == "COMPLETADA",
                   "captura reconciliada completa la asociación tras el reinicio")
        detener(proceso_actual)
        proceso_actual = None
    finally:
        if proceso_actual is not None and proceso_actual.poll() is None:
            detener(proceso_actual)
        os.close(serial_fd)

    salida = "".join(salidas)
    exigir_api(uid not in salida and token not in salida, "reinicio bridge no registra UID ni token")
    return [uid], salida


def probar_cancelacion_serial(
    base_url: str,
    token: str,
    cliente_dueno,
    token_csrf: str,
    codigo_empleado: str,
    crear_captura,
    exigir_api,
) -> str:
    respuesta = crear_captura(cliente_dueno, token_csrf, "EMPLEADO", codigo_empleado)
    exigir_api(respuesta.estado == 201, "captura sintética para cancelación serial")
    captura_id = respuesta.json()["capturaId"]
    serial_fd, dispositivo_fd = pty.openpty()
    ruta_pty = os.ttyname(dispositivo_fd)
    os.close(dispositivo_fd)
    raiz = Path(__file__).resolve().parents[4]
    entorno = os.environ.copy()
    entorno["SMARTPARKING_RFID1_API_URL"] = base_url
    entorno["SMARTPARKING_RFID1_TOKEN"] = token
    bridge = subprocess.Popen(
        [sys.executable, str(raiz / "infra/rfid1-bridge/bridge.py"), "--port", ruta_pty],
        cwd=raiz,
        env=entorno,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    buffer = bytearray()
    salida = ""
    try:
        armado = leer_hasta(
            serial_fd, buffer, time.monotonic() + 12,
            lambda linea: linea.startswith("ENROLL_ARM,"),
        )
        exigir_api(armado == f"ENROLL_ARM,{captura_id}", "bridge arma antes de la cancelación DUENO")
        cancelacion = cliente_dueno.solicitar(
            "DELETE",
            f"/api/v1/rfid-1/capturas/{captura_id}",
            encabezados={"X-CSRF-TOKEN": token_csrf},
        )
        exigir_api(cancelacion.estado == 204, "DUENO cancela captura armada")
        cancelada = leer_hasta(
            serial_fd, buffer, time.monotonic() + 8,
            lambda linea: linea.startswith("ENROLL_CANCEL,"),
        )
        exigir_api(cancelada == f"ENROLL_CANCEL,{captura_id}",
                   "bridge cancela el lector según el estado autoritativo")
    finally:
        bridge.terminate()
        try:
            salida, _ = bridge.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            bridge.kill()
            salida, _ = bridge.communicate(timeout=5)
        os.close(serial_fd)
    exigir_api(token not in salida, "cancelación bridge no registra token")
    return salida
