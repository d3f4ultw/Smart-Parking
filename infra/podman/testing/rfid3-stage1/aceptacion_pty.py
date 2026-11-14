"""Integra un PTY, el bridge candidato y la API desechable con respuestas perdidas."""

import contextlib
import http.server
import io
import os
import pty
import select
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../rfid1-bridge")))
from bridge import SesionBridge
from cliente_capturas import ClienteCapturas
from puerto_serie import PuertoSerie


def integrar(base, token, uid, perder, sql, exigir):
    lectura = str(uuid.uuid4())
    ruta_salida = "/api/v1/dispositivos/rfid-3/salidas"

    class Proxy(http.server.BaseHTTPRequestHandler):
        intentos = 0
        identificadores = []

        def log_message(self, formato, *argumentos):
            return

        def do_GET(self):
            self.reenviar()

        def do_POST(self):
            self.reenviar()

        def reenviar(self):
            datos = self.rfile.read(int(self.headers.get("Content-Length", "0"))) or None
            encabezados = {}
            for nombre in ("Authorization", "Content-Type", "Accept"):
                if self.headers.get(nombre):
                    encabezados[nombre] = self.headers[nombre]
            peticion = urllib.request.Request(base + self.path, data=datos, method=self.command, headers=encabezados)
            try:
                with urllib.request.urlopen(peticion, timeout=5) as respuesta:
                    estado, contenido = respuesta.status, respuesta.read()
            except urllib.error.HTTPError as error:
                estado, contenido = error.code, error.read()
            if self.path == ruta_salida:
                import json
                Proxy.intentos += 1
                Proxy.identificadores.append(json.loads(datos)["lecturaId"])
                if Proxy.intentos <= perder:
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    self.connection.close()
                    return
            try:
                self.send_response(estado)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(contenido)))
                self.end_headers()
                self.wfile.write(contenido)
            except OSError:
                pass

    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    hilo_proxy = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo_proxy.start()
    maestro, esclavo = pty.openpty()
    nombre_esclavo = os.ttyname(esclavo)
    os.close(esclavo)
    puerto = PuertoSerie(nombre_esclavo)
    cliente = ClienteCapturas(f"http://127.0.0.1:{servidor.server_port}", token)
    sesion = SesionBridge(cliente, intervalo_ping=0.1, tiempo_espera_pong=2, intervalo_lectura=0.02)
    detener = threading.Event()
    errores = []
    registro = io.StringIO()

    def ejecutar_bridge():
        try:
            with contextlib.redirect_stdout(registro):
                sesion.ejecutar(puerto, detener)
        except Exception as error:
            errores.append(type(error).__name__)

    hilo = threading.Thread(target=ejecutar_bridge, daemon=True)
    hilo.start()
    buffer = bytearray()
    respuestas = []

    def recibir(hasta):
        limite = time.monotonic() + hasta
        while time.monotonic() < limite:
            listos, _, _ = select.select([maestro], [], [], 0.05)
            if not listos:
                continue
            buffer.extend(os.read(maestro, 1024))
            while b"\n" in buffer:
                linea, _, resto = buffer.partition(b"\n")
                buffer[:] = resto
                linea = linea.removesuffix(b"\r")
                if linea == b"PING":
                    os.write(maestro, b"PONG\n")
                if linea.startswith(f"RFID3_RESULT,{lectura},".encode("ascii")):
                    respuestas.append(linea.decode("ascii").rsplit(",", 1)[1])
                    return respuestas[-1]
        return None

    try:
        trama = f"RFID3,{lectura},{uid}\n".encode("ascii")
        os.write(maestro, trama[:9])
        os.write(maestro, trama[9:])
        esperado = "AUTORIZADA" if perder == 1 else "DENEGADA"
        exigir(recibir(8) == esperado, "PTY respeta la decisión ante respuestas HTTP perdidas")
        exigir(Proxy.intentos == 2 and all(valor == lectura for valor in Proxy.identificadores),
               "el bridge reintenta con la misma UUID")
        exigir(sql(f"SELECT count(*) FROM movimiento_estacionamiento WHERE lectura_salida_id='{lectura}'") == "1",
               "PostgreSQL confirmó un solo cierre durante la pérdida HTTP")
        if perder > 1:
            anteriores = Proxy.intentos
            os.write(maestro, trama)
            exigir(recibir(3) == "DENEGADA", "retransmisión terminal permanece denegada")
            exigir(Proxy.intentos == anteriores, "la denegación terminal no reenvía a la API")
            recibir(0.5)
            exigir("AUTORIZADA" not in respuestas, "ninguna respuesta tardía cambia la denegación terminal")
        exigir(not errores, "bridge PTY no terminó con error")
    finally:
        detener.set()
        hilo.join(timeout=5)
        sesion.estado_dispositivo.cerrar()
        puerto.cerrar()
        os.close(maestro)
        servidor.shutdown()
        servidor.server_close()
        hilo_proxy.join(timeout=3)
    exigir(uid not in registro.getvalue() and token not in registro.getvalue(), "PTY no registra UID ni Bearer")
