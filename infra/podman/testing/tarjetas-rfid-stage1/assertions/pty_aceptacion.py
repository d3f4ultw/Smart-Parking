#!/usr/bin/env python3
"""Aserción serial end-to-end Stage 1 con API de loopback y PTY sintético."""

import http.cookiejar
import http.client
import http.server
import json
import os
import pty
import select
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

UID_HISTORICO = "A1A2A3A4"
UID_NUEVO = uuid.uuid4().hex[:8].upper()
UID_NORMAL = "C1C2C3C4"
LECTURAS = "/api/v1/dispositivos/rfid-1/lecturas"

def exigir(condicion, mensaje):
    if not condicion:
        raise AssertionError(mensaje)

class SesionApi:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.csrf_token = None

    def pedir(self, metodo, ruta, cuerpo=None, encabezados=None):
        datos = None if cuerpo is None else json.dumps(cuerpo, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json"}
        if datos is not None:
            headers["Content-Type"] = "application/json; charset=UTF-8"
        if encabezados:
            headers.update(encabezados)
        solicitud = urllib.request.Request(self.base + ruta, data=datos, headers=headers, method=metodo)
        try:
            with self.http.open(solicitud, timeout=8) as respuesta:
                return respuesta.status, respuesta.headers, respuesta.read()
        except urllib.error.HTTPError as respuesta:
            return respuesta.code, respuesta.headers, respuesta.read()
        except (OSError, TimeoutError):
            raise AssertionError("La API local de aceptación no respondió.") from None

    def json(self, metodo, ruta, cuerpo=None, encabezados=None):
        estado, headers, datos = self.pedir(metodo, ruta, cuerpo, encabezados)
        try:
            documento = json.loads(datos.decode("utf-8")) if datos else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AssertionError("La API local devolvió una respuesta JSON inválida.") from None
        return estado, headers, documento

    def iniciar_dueno(self, correo, contrasena):
        estado, _, csrf = self.json("GET", "/api/v1/csrf")
        exigir(estado == 200 and isinstance(csrf.get("token"), str), "No se pudo iniciar el flujo DUENO.")
        estado, _, sesion = self.json("POST", "/api/v1/sesion",
                {"correo": correo, "contrasena": contrasena}, {"X-CSRF-TOKEN": csrf["token"]})
        exigir(estado == 200 and isinstance(sesion.get("csrfToken"), str), "No se pudo abrir la sesión DUENO.")
        self.csrf_token = sesion["csrfToken"]

    def empleado(self, sufijo):
        estado, _, recibo = self.json("POST", "/api/v1/empleados",
                {"nombres": "Empleado Stage1 " + sufijo, "primerApellido": "Prueba"},
                {"X-CSRF-TOKEN": self.csrf_token, "Idempotency-Key": str(uuid.uuid4())})
        exigir(estado == 201 and isinstance(recibo.get("codigo"), str), "No se creó el empleado sintético.")
        return recibo["codigo"]
    def crear_captura(self, codigo):
        estado, _, respuesta = self.json("POST", "/api/v1/rfid-1/capturas",
                {"tipoEntidad": "EMPLEADO", "codigoPersona": codigo},
                {"X-CSRF-TOKEN": self.csrf_token, "Idempotency-Key": str(uuid.uuid4())})
        exigir(estado == 201 and isinstance(respuesta.get("capturaId"), str), "No se creó la captura sintética.")
        return respuesta["capturaId"]
    def crear_asociacion_historica(self, codigo, uid, token):
        captura = self.crear_captura(codigo)
        dispositivo = SesionApi(self.base)
        headers = {"Authorization": "Bearer " + token}
        estado, _, _ = dispositivo.json("POST", "/api/v1/dispositivos/rfid-1/capturas/" + captura + "/estado",
                {"estado": "ESCANEANDO"}, headers)
        exigir(estado == 204, "No inició la captura histórica sintética.")
        solicitud = {"capturaId": captura, "requestId": "0101", "uid": uid}
        headers["Idempotency-Key"] = str(uuid.uuid5(uuid.UUID(captura), "0101"))
        estado, _, lectura = dispositivo.json("POST", LECTURAS, solicitud, headers)
        exigir(estado == 200 and lectura.get("resultado") == "PREVIEW_READY",
                "No se obtuvo la vista previa histórica.")
        estado, _, previa = self.json("GET", "/api/v1/rfid-1/capturas/" + captura + "/vista-previa")
        exigir(estado == 200 and previa.get("uid") == uid, "La vista DUENO no devolvió la UID sintética esperada.")
        estado, _, _ = self.json("POST", "/api/v1/rfid-1/capturas/" + captura + "/confirmacion", None,
                {"X-CSRF-TOKEN": self.csrf_token, "Idempotency-Key": str(uuid.uuid4())})
        exigir(estado == 200, "No se confirmó la asociación histórica sintética.")
    def confirmar(self, captura):
        return self.json("POST", "/api/v1/rfid-1/capturas/" + captura + "/confirmacion", None,
                {"X-CSRF-TOKEN": self.csrf_token, "Idempotency-Key": str(uuid.uuid4())})
    def obtener_captura(self, captura):
        return self.json("GET", "/api/v1/rfid-1/capturas/" + captura)
    def lista_tarjetas(self):
        estado, _, cuerpo = self.pedir(
                "GET", "/api/v1/tarjetas-rfid?tipoEntidad=EMPLEADO&estado=ACTIVA&pagina=1")
        exigir(estado == 200, "El historial privado de tarjetas no respondió correctamente.")
        return cuerpo


class ProxyLecturas(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, destino, puerto):
        super().__init__(("127.0.0.1", 0), ManejadorProxyLecturas)
        self.destino = destino
        self.puerto_destino = puerto
        self.lecturas = []
        self.bloquear_uid = None
        self.respuesta_perdida = threading.Event()
        self.lock = threading.Lock()

    def handle_error(self, request, client_address):
        return


class ManejadorProxyLecturas(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.reenviar()

    def do_POST(self):
        self.reenviar()

    def log_message(self, formato, *argumentos):
        return

    def reenviar(self):
        cantidad = int(self.headers.get("Content-Length", "0"))
        cuerpo = self.rfile.read(cantidad) if cantidad else b""
        idempotencia = self.headers.get("Idempotency-Key", "")
        uid = None
        documento = {}
        if self.path == LECTURAS and cuerpo:
            try:
                documento = json.loads(cuerpo.decode("utf-8"))
                uid = documento.get("uid") if "capturaId" in documento else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                documento = {}
        if uid is not None:
            with self.server.lock:
                self.server.lecturas.append((cuerpo, idempotencia, uid))

        headers = {nombre: valor for nombre, valor in self.headers.items()
                if nombre.lower() not in {"host", "connection", "content-length", "accept-encoding"}}
        conexion = http.client.HTTPConnection(self.server.destino, self.server.puerto_destino, timeout=10)
        try:
            conexion.request(self.command, self.path, body=cuerpo, headers=headers)
            respuesta = conexion.getresponse()
            estado = respuesta.status
            contenido = respuesta.read()
            tipo = respuesta.getheader("Content-Type", "application/json")
            cache = respuesta.getheader("Cache-Control")
            vary = respuesta.getheader("Vary")
        except (OSError, TimeoutError, http.client.HTTPException):
            self.send_error(502)
            return
        finally:
            conexion.close()

        if uid is not None and uid == self.server.bloquear_uid and not self.server.respuesta_perdida.is_set():
            self.server.respuesta_perdida.set()
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return

        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(contenido)))
        self.send_header("Connection", "close")
        if cache:
            self.send_header("Cache-Control", cache)
        if vary:
            self.send_header("Vary", vary)
        self.end_headers()
        if contenido:
            self.wfile.write(contenido)

class PseudoTerminalBridge:
    def __init__(self, comando, entorno):
        self.maestro, esclavo = pty.openpty()
        self.ruta = os.ttyname(esclavo)
        os.close(esclavo)
        self.buffer = bytearray()
        self.tramas = []
        self.salidas = []
        self.proceso = None
        self.comando = comando
        self.entorno = entorno

    def iniciar(self):
        self.proceso = subprocess.Popen(self.comando + ["--port", self.ruta],
                cwd=self.entorno["RFID1_BRIDGE_DIR"], env=self.entorno,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
        for salida in (self.proceso.stdout, self.proceso.stderr):
            hilo = threading.Thread(target=self._drenar, args=(salida,), daemon=True)
            hilo.start()

    def _drenar(self, canal):
        while True:
            bloque = canal.readline()
            if not bloque:
                return
            self.salidas.append(bloque.decode("utf-8", "replace"))

    def enviar(self, trama):
        os.write(self.maestro, (trama + "\n").encode("ascii"))

    def _leer(self, limite):
        while time.monotonic() < limite:
            separador = self.buffer.find(b"\n")
            if separador >= 0:
                trama = bytes(self.buffer[:separador]).rstrip(b"\r")
                del self.buffer[:separador + 1]
                try:
                    return trama.decode("ascii")
                except UnicodeDecodeError:
                    raise AssertionError("El bridge escribió una trama no ASCII.") from None
            espera = min(0.1, max(0, limite - time.monotonic()))
            listos, _, _ = select.select([self.maestro], [], [], espera)
            if not listos:
                if self.proceso is not None and self.proceso.poll() is not None:
                    raise AssertionError("El bridge terminó durante la aceptación PTY.")
                continue
            try:
                datos = os.read(self.maestro, 4096)
            except OSError:
                time.sleep(0.02)
                continue
            if datos:
                self.buffer.extend(datos)
        return None

    def esperar(self, prefijo, segundos=8):
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            trama = self._leer(limite)
            if trama is None:
                break
            self.tramas.append(trama)
            if trama == "PING":
                self.enviar("PONG")
            elif trama.startswith(prefijo):
                return trama
        raise AssertionError("No llegó la trama serial esperada.")

    def recopilar(self, segundos):
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            trama = self._leer(limite)
            if trama is None:
                break
            self.tramas.append(trama)
            if trama == "PING":
                self.enviar("PONG")
        return list(self.tramas)

    def detener(self):
        if self.proceso is not None and self.proceso.poll() is None:
            self.proceso.send_signal(signal.SIGTERM)
            try:
                self.proceso.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proceso.kill()
                self.proceso.wait(timeout=3)
    def cerrar(self):
        self.detener()
        os.close(self.maestro)


def main():
    base = os.environ.get("RFID1_STAGE1_API_URL", "")
    token = os.environ.get("SMARTPARKING_RFID1_TOKEN", "")
    correo = os.environ.get("RFID1_STAGE1_OWNER_EMAIL", "")
    contrasena = os.environ.get("RFID1_STAGE1_OWNER_PASSWORD", "")
    exigir(all((base, token, correo, contrasena)), "Faltan credenciales sintéticas para la aceptación PTY.")
    exigir(os.environ.get("POSTGRES_HOST") == "127.0.0.1"
            and os.environ.get("POSTGRES_DB") == "sp_rfid1_stage1_fresh",
            "La aceptación PTY requiere la base fresca Stage 1 en loopback.")
    api = urllib.parse.urlsplit(base)
    exigir(api.scheme == "http" and api.hostname == "127.0.0.1" and api.port,
            "La aceptación PTY requiere la API sintética en loopback.")
    raiz = Path(__file__).resolve().parents[5]
    bridge_dir = raiz / "infra" / "rfid1-bridge"
    cliente = SesionApi(base)
    cliente.iniciar_dueno(correo, contrasena)
    codigo_historico = cliente.empleado("historial")
    cliente.crear_asociacion_historica(codigo_historico, UID_HISTORICO, token)
    codigo_objetivo = cliente.empleado("pty")
    captura = cliente.crear_captura(codigo_objetivo)

    proxy = ProxyLecturas(api.hostname, api.port)
    servidor = threading.Thread(target=proxy.serve_forever, daemon=True)
    servidor.start()
    estado, _, activa = SesionApi("http://127.0.0.1:{}".format(proxy.server_address[1])).json(
            "GET", "/api/v1/dispositivos/rfid-1/capturas/activa",
            encabezados={"Authorization": "Bearer " + token})
    exigir((estado, activa.get("capturaId"), activa.get("estado")) == (200, captura, "PENDIENTE"),
            "La API del lector no devolvió la captura pendiente.")
    entorno = {"SMARTPARKING_RFID1_API_URL": "http://127.0.0.1:{}".format(proxy.server_address[1]),
            "SMARTPARKING_RFID1_TOKEN": token, "RFID1_BRIDGE_DIR": str(bridge_dir),
            "PYTHONPATH": str(bridge_dir), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    comando = [sys.executable, str(bridge_dir / "bridge.py")]
    pty_bridge = PseudoTerminalBridge(comando, entorno)
    try:
        pty_bridge.iniciar()
        armado = pty_bridge.esperar("ENROLL_ARM,")
        exigir(armado == "ENROLL_ARM," + captura, "El bridge armó otra captura.")
        pty_bridge.enviar("ENROLL_READ,{},{},{}".format(captura, "0001", UID_HISTORICO))
        exigir(pty_bridge.esperar("ENROLL_ARM,") == "ENROLL_ARM," + captura,
                "El UID histórico no dejó la captura disponible para otra lectura.")
        _, _, estado = cliente.obtener_captura(captura)
        exigir(estado.get("estado") == "ESCANEANDO", "La lectura histórica finalizó la captura.")
        tarjetas = cliente.lista_tarjetas()
        exigir(codigo_objetivo not in tarjetas.decode("utf-8"),
                "Una lectura rechazada creó una asociación para el objetivo.")

        proxy.bloquear_uid = UID_NUEVO
        pty_bridge.enviar("ENROLL_READ,{},{},{}".format(captura, "0002", UID_NUEVO))
        exigir(proxy.respuesta_perdida.wait(5), "El proxy no descartó la primera respuesta HTTP.")
        exigir(pty_bridge.esperar("ENROLL_CANCEL,") == "ENROLL_CANCEL," + captura,
                "El bridge no canceló el lector al preparar la vista previa.")
        limite = time.monotonic() + 6
        while time.monotonic() < limite:
            with proxy.lock:
                reintentos = [lectura for lectura in proxy.lecturas if lectura[2] == UID_NUEVO]
            if len(reintentos) >= 2:
                break
            time.sleep(0.05)
        exigir(len(reintentos) == 2 and reintentos[0][0] == reintentos[1][0]
                and reintentos[0][1] == reintentos[1][1],
                "El retry HTTP no reutilizó el mismo cuerpo y la misma clave.")
        _, _, resumen = cliente.obtener_captura(captura)
        exigir(resumen.get("estado") == "VISTA_PREVIA", "La captura no quedó en vista previa.")
        exigir(UID_NUEVO not in json.dumps(resumen), "El resumen de captura expuso el UID.")
        previa_estado, previa_headers, previa = cliente.json(
                "GET", "/api/v1/rfid-1/capturas/" + captura + "/vista-previa")
        exigir(previa_estado == 200 and previa.get("uid") == UID_NUEVO,
                "La sesión propietaria no recibió su vista previa autorizada.")
        exigir("no-store" in previa_headers.get("Cache-Control", "").lower(),
                "La vista previa autorizada no prohíbe el almacenamiento en caché.")
        tarjetas = cliente.lista_tarjetas()
        exigir(codigo_objetivo not in tarjetas.decode("utf-8"),
                "Una vista previa creó una asociación antes de confirmar.")

        pty_bridge.detener()
        inicio_reinicio = len(pty_bridge.tramas)
        pty_bridge.buffer.clear()
        pty_bridge.iniciar()
        exigir(pty_bridge.esperar("ENROLL_CANCEL,") == "ENROLL_CANCEL," + captura,
                "El reinicio no canceló una captura que ya estaba en vista previa.")
        pty_bridge.recopilar(0.8)
        tramas_reinicio = pty_bridge.tramas[inicio_reinicio:]
        exigir(not any(trama.startswith("ENROLL_ARM," + captura) for trama in tramas_reinicio),
                "El reinicio rearmó una vista previa ya aceptada.")

        pty_bridge.enviar("RFID,0030,{}".format(UID_NORMAL))
        exigir(pty_bridge.esperar("ACK,") == "ACK,0030", "El lector no reconoció la lectura ordinaria.")
        exigir(pty_bridge.esperar("RESULT,") == "RESULT,0030,DENY",
                "La lectura ordinaria no quedó en modo fail-closed.")
        tarjetas = cliente.lista_tarjetas().decode("utf-8")
        exigir(codigo_objetivo not in tarjetas and UID_NORMAL not in tarjetas,
                "La lectura ordinaria creó una asociación de tarjeta.")

        estado_confirmacion, _, _ = cliente.confirmar(captura)
        exigir(estado_confirmacion == 200, "El propietario no pudo confirmar la vista previa.")
        _, _, final = cliente.obtener_captura(captura)
        exigir(final.get("estado") == "COMPLETADA", "La confirmación no finalizó la captura.")
        tarjetas = cliente.lista_tarjetas()
        exigir(codigo_objetivo in tarjetas.decode("utf-8"), "La asociación confirmada no aparece en el historial.")
    finally:
        pty_bridge.cerrar()
        proxy.shutdown()
        proxy.server_close()
        servidor.join(timeout=2)

    salida_bridge = "".join(pty_bridge.salidas)
    for secreto in (token, UID_HISTORICO, UID_NUEVO, UID_NORMAL, correo):
        exigir(secreto not in salida_bridge, "La salida del bridge expuso datos sensibles.")
    exigir("ALLOW" not in salida_bridge, "La salida del bridge incluyó una decisión ALLOW.")
    print("PASS: aceptación PTY end-to-end Stage 1 en TTY sintético.")

if __name__ == "__main__":
    main()
