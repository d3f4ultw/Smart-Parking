"""Aceptación aislada RFID3; las identidades de prueba permanecen en memoria."""

import concurrent.futures
import http.cookiejar
import http.server
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

from aceptacion_pty import integrar
from aceptacion_cancelacion import probar as probar_cancelacion


BASE = os.environ["RFID3_STAGE1_API_URL"].rstrip("/")
TOKEN = os.environ["RFID3_STAGE1_TOKEN"]
DB_CONTAINER = os.environ["RFID3_STAGE1_DB_CONTAINER"]
API_CONTAINER = os.environ["RFID3_STAGE1_API_CONTAINER"]
DB = os.environ["RFID3_STAGE1_POSTGRES_DB"]
DB_USER = os.environ["RFID3_STAGE1_POSTGRES_USER"]
UIDS = [secrets.token_hex(4).upper() for _ in range(18)]
RUTA_SALIDA = "/api/v1/dispositivos/rfid-3/salidas"
RUTA_ENTRADA = "/api/v1/dispositivos/rfid-2/entradas"
COMPROBACIONES = 0


def exigir(condicion, mensaje):
    global COMPROBACIONES
    if not condicion:
        raise AssertionError(mensaje)
    COMPROBACIONES += 1


def sql(consulta):
    proceso = subprocess.run(
        ["podman", "exec", "-i", DB_CONTAINER, "psql", "-X", "-qAt",
         "-v", "ON_ERROR_STOP=1", "-U", DB_USER, "-d", DB],
        input=consulta, text=True, capture_output=True,
    )
    if proceso.returncode:
        raise RuntimeError("Falló una consulta en PostgreSQL desechable")
    return proceso.stdout.strip()


def solicitud(metodo, ruta, cuerpo=None, token=None, cliente=None, extra=None, base=BASE):
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    encabezados = {"Accept": "application/json"}
    if datos is not None:
        encabezados["Content-Type"] = "application/json"
    if token is not None:
        encabezados["Authorization"] = "Bearer " + token
    encabezados.update(extra or {})
    peticion = urllib.request.Request(base + ruta, data=datos, headers=encabezados, method=metodo)
    try:
        abrir = cliente.open if cliente else urllib.request.urlopen
        with abrir(peticion, timeout=8) as respuesta:
            texto = respuesta.read().decode()
            return respuesta.status, json.loads(texto) if texto else {}, respuesta.headers
    except urllib.error.HTTPError as error:
        texto = error.read().decode()
        try:
            contenido = json.loads(texto) if texto else {}
        except ValueError:
            contenido = {}
        return error.code, contenido, error.headers


def leer(ruta, uid, lectura=None, token=TOKEN, cliente=None):
    return solicitud("POST", ruta, {"uid": uid, "lecturaId": lectura or str(uuid.uuid4())},
                     token, cliente)


def preparar_dueno():
    cliente = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    correo = "dueno-stage1@example.invalid"
    contrasena = secrets.token_urlsafe(28) + "aA1!"
    csrf = solicitud("GET", "/api/v1/csrf", cliente=cliente)[1]["token"]
    propietario = {"nombres": "Dueno Sintetico", "primerApellido": "Prueba", "correo": correo,
                   "contrasenaAcceso": contrasena, "contrasenaAdministrativa": secrets.token_urlsafe(28) + "aA1!"}
    estacionamiento = {"nombre": "Aceptacion aislada", "tipo": "MIXTO", "horario": {
        "modo": "INTERVALO_DIARIO", "zonaHoraria": "America/Mexico_City",
        "horaApertura": "22:00", "horaCierre": "06:00"}}
    estado, _, _ = solicitud("POST", "/api/v1/configuracion/inicial",
                            {"propietario": propietario, "estacionamiento": estacionamiento}, cliente=cliente,
                            extra={"X-CSRF-TOKEN": csrf, "Idempotency-Key": str(uuid.uuid4())})
    exigir(estado == 201, "configuración sintética del propietario")
    csrf = solicitud("GET", "/api/v1/csrf", cliente=cliente)[1]["token"]
    estado, respuesta, _ = solicitud("POST", "/api/v1/sesion", {"correo": correo, "contrasena": contrasena},
                                    cliente=cliente, extra={"X-CSRF-TOKEN": csrf})
    exigir(estado == 200, "sesión sintética DUENO")
    return cliente, respuesta["csrfToken"]


def preparar_personas():
    cliente = str(uuid.uuid4())
    sentencias = [f"""
        INSERT INTO cuenta (id,nombres,primer_apellido,segundo_apellido,correo,correo_normalizado,
          rol,estado,hash_contrasena_acceso,revision_acceso,creada_en,actualizada_en)
        VALUES ('{cliente}','Cliente Sintetico','Prueba',NULL,'cliente-stage1@example.invalid',
          'cliente-stage1@example.invalid','CLIENTE','ACTIVA','hash-sintetico',1,now(),now());
        INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico,cliente_id) VALUES ('{UIDS[0]}','{cliente}');
    """]
    for indice, uid in enumerate(UIDS[1:], 1):
        sentencias.append(f"""
            WITH persona AS (INSERT INTO empleado (nombres,primer_apellido)
              VALUES ('Empleado Sintetico {indice}','Prueba') RETURNING id)
            INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico,empleado_id) SELECT '{uid}',id FROM persona;
        """)
    sql("\n".join(sentencias))


def entrada(uid, lectura=None):
    return leer(RUTA_ENTRADA, uid, lectura)


def salida(uid, lectura=None):
    return leer(RUTA_SALIDA, uid, lectura)


def autorizada(respuesta):
    return (respuesta[0] == 200 and respuesta[1].get("resultado") == "AUTORIZADA"
            and respuesta[1].get("motivo") is None)


def denegada(respuesta, motivo):
    return respuesta[0] == 200 and respuesta[1] == {"resultado": "DENEGADA", "motivo": motivo}


def iniciar_bloqueo(uid, segundos=1.5, cancelar=False):
    operacion = (f"UPDATE asociacion_tarjeta_rfid1 SET estado='CANCELADA', cancelada_en=now() "
                 f"WHERE uid_canonico='{uid}'" if cancelar else
                 f"SELECT asociacion_id FROM asociacion_tarjeta_rfid1 WHERE uid_canonico='{uid}' FOR UPDATE")
    proceso = subprocess.Popen(
        ["podman", "exec", "-i", "-e", "PGAPPNAME=rfid3_bloqueo", DB_CONTAINER,
         "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-U", DB_USER, "-d", DB],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    proceso.stdin.write(f"BEGIN; {operacion}; SELECT pg_sleep({segundos}); COMMIT;\n")
    proceso.stdin.close()
    for _ in range(100):
        if sql("SELECT count(*) FROM pg_stat_activity WHERE application_name='rfid3_bloqueo' "
               "AND wait_event='PgSleep'") == "1":
            return proceso
        time.sleep(0.03)
    proceso.terminate()
    raise AssertionError("el bloqueo sintético no comenzó")


def esperar_bloqueo_api():
    for _ in range(60):
        if int(sql("SELECT count(*) FROM pg_stat_activity WHERE application_name <> 'rfid3_bloqueo' "
                   "AND wait_event_type='Lock'")):
            return
        time.sleep(0.02)
    raise AssertionError("la solicitud no esperó el bloqueo de tarjeta")


def probar_carreras():
    # Ambas órdenes se fuerzan mientras un tercero retiene el mismo bloqueo de tarjeta.
    for indice, primera_entrada in ((4, True), (5, False)):
        uid = UIDS[indice]
        if not primera_entrada:
            exigir(autorizada(entrada(uid)), "preparación de entrada abierta")
        bloqueo = iniciar_bloqueo(uid)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as grupo:
                primero = grupo.submit(entrada if primera_entrada else salida, uid)
                esperar_bloqueo_api()
                segundo = grupo.submit(salida if primera_entrada else entrada, uid)
                r1, r2 = primero.result(timeout=7), segundo.result(timeout=7)
            exigir(autorizada(r1) and autorizada(r2), "entrada y salida se serializan en el orden solicitado")
        finally:
            bloqueo.wait(timeout=5)
        exigir(sql(f"SELECT bool_and(instante_salida IS NULL OR instante_salida >= instante_entrada) "
                   f"FROM movimiento_estacionamiento WHERE uid_historico='{uid}'") == "t",
               "cada movimiento conserva su cronología")
        exigir(sql(f"SELECT COALESCE(bool_and(anterior IS NULL OR instante_entrada >= anterior),true) FROM "
                   f"(SELECT instante_entrada, lag(instante_salida) OVER (ORDER BY movimiento_id) anterior "
                   f"FROM movimiento_estacionamiento WHERE uid_historico='{uid}') m") == "t",
               "la entrada siguiente no precede a la salida anterior")

    uid = UIDS[6]
    exigir(autorizada(entrada(uid)), "entrada para salidas simultáneas")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as grupo:
        resultados = list(grupo.map(lambda _: salida(uid), range(2)))
    exigir(sum(autorizada(r) for r in resultados) == 1
           and sum(denegada(r, "SIN_ENTRADA_ABIERTA") for r in resultados) == 1,
           "dos salidas simultáneas cierran una sola vez")

    uid = UIDS[7]
    exigir(autorizada(entrada(uid)), "entrada para cancelación concurrente")
    bloqueo = iniciar_bloqueo(uid, cancelar=True)
    try:
        resultado = salida(uid)
    finally:
        bloqueo.wait(timeout=5)
    exigir(denegada(resultado, "TARJETA_CANCELADA"), "cancelación confirmada precede la salida")
    exigir(sql(f"SELECT count(*) FROM movimiento_estacionamiento WHERE uid_historico='{uid}' "
               "AND instante_salida IS NULL") == "1", "cancelación no cierra el movimiento")

    uid = UIDS[8]
    exigir(autorizada(entrada(uid)), "entrada para timeout")
    bloqueo = iniciar_bloqueo(uid, segundos=3.5)
    try:
        resultado = salida(uid)
    finally:
        bloqueo.wait(timeout=6)
    exigir(resultado[0] >= 500 and resultado[1].get("resultado") != "AUTORIZADA", "timeout falla cerrado")
    exigir(sql(f"SELECT count(*) FROM movimiento_estacionamiento WHERE uid_historico='{uid}' "
               "AND instante_salida IS NULL") == "1", "timeout previo al commit no cerró el movimiento")


def probar_respuesta_perdida():
    uid = UIDS[9]
    exigir(autorizada(entrada(uid)), "entrada para respuesta HTTP perdida")
    lectura = str(uuid.uuid4())

    class Proxy(http.server.BaseHTTPRequestHandler):
        intentos = 0

        def log_message(self, formato, *argumentos):
            return

        def do_POST(self):
            datos = self.rfile.read(int(self.headers["Content-Length"]))
            peticion = urllib.request.Request(BASE + RUTA_SALIDA, data=datos, method="POST",
                                              headers={"Content-Type": "application/json",
                                                       "Authorization": self.headers["Authorization"]})
            with urllib.request.urlopen(peticion, timeout=6) as respuesta:
                contenido = respuesta.read()
            Proxy.intentos += 1
            if Proxy.intentos == 1:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(contenido)))
            self.end_headers()
            self.wfile.write(contenido)

    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    base = f"http://127.0.0.1:{servidor.server_port}"
    try:
        try:
            solicitud("POST", RUTA_SALIDA, {"uid": uid, "lecturaId": lectura}, TOKEN, base=base)
            raise AssertionError("la primera respuesta debió perderse")
        except (ConnectionError, OSError, urllib.error.URLError):
            pass
        exigir(sql(f"SELECT count(*) FROM movimiento_estacionamiento WHERE lectura_salida_id='{lectura}'") == "1",
               "el commit puede ocurrir antes de perder la respuesta")
        repeticion = solicitud("POST", RUTA_SALIDA, {"uid": uid, "lecturaId": lectura}, TOKEN, base=base)
        exigir(autorizada(repeticion), "replay con el UUID original recupera la decisión confirmada")
        exigir(sql(f"SELECT count(*) FROM movimiento_estacionamiento WHERE uid_historico='{uid}'") == "1",
               "replay no crea ni duplica movimientos")
    finally:
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=3)


def probar():
    exigir(sql("SELECT count(*) FROM flyway_schema_history WHERE success AND version::int BETWEEN 1 AND 14") == "14",
           "Flyway aplicó V1–V14 en PostgreSQL desechable")
    dueno, csrf = preparar_dueno()
    preparar_personas()
    exigir(leer(RUTA_SALIDA, UIDS[0], token=None)[0] == 401, "sin Bearer la salida se rechaza")
    exigir(leer(RUTA_SALIDA, UIDS[0], token="incorrecto")[0] == 401, "Bearer incorrecto se rechaza")
    exigir(solicitud("GET", "/api/v1/panel", token=TOKEN)[0] == 401, "Bearer no autoriza DUENO")
    exigir(solicitud("POST", RUTA_SALIDA, {"uid": UIDS[0], "lecturaId": str(uuid.uuid4())},
                     cliente=dueno, extra={"X-CSRF-TOKEN": csrf})[0] == 401,
           "la sesión DUENO no autoriza la ruta del dispositivo")
    exigir(salida("NO-VALIDO")[0] == 400, "UID inválido se rechaza")
    exigir(leer(RUTA_SALIDA, UIDS[0], "no-es-uuid")[0] == 400, "UUID inválida se rechaza")
    exigir(denegada(salida("DEADBEEF"), "TARJETA_DESCONOCIDA"), "tarjeta desconocida")
    sql(f"UPDATE asociacion_tarjeta_rfid1 SET estado='CANCELADA',cancelada_en=now() WHERE uid_canonico='{UIDS[1]}'")
    exigir(denegada(salida(UIDS[1]), "TARJETA_CANCELADA"), "tarjeta cancelada")
    exigir(denegada(salida(UIDS[2]), "SIN_ENTRADA_ABIERTA"), "tarjeta sin entrada")

    uid = UIDS[0]
    identificador_entrada, identificador_salida = str(uuid.uuid4()), str(uuid.uuid4())
    exigir(autorizada(entrada(uid, identificador_entrada)), "entrada de cliente")
    antes = sql(f"SELECT md5(row(movimiento_id,asociacion_id,tipo_persona,cliente_id,empleado_id,"
                f"uid_historico,lectura_id,fecha_entrada,hora_entrada,instante_entrada)::text) "
                f"FROM movimiento_estacionamiento WHERE lectura_id='{identificador_entrada}'")
    respuesta = salida(uid.lower(), identificador_salida)
    exigir(autorizada(respuesta), "salida autorizada de cliente")
    exigir("motivo" not in respuesta[1], "salida autorizada omite motivo")
    exigir(respuesta[2].get("Cache-Control") == "no-store, private", "respuesta privada")
    despues = sql(f"SELECT md5(row(movimiento_id,asociacion_id,tipo_persona,cliente_id,empleado_id,"
                  f"uid_historico,lectura_id,fecha_entrada,hora_entrada,instante_entrada)::text) "
                  f"FROM movimiento_estacionamiento WHERE lectura_id='{identificador_entrada}'")
    exigir(antes == despues, "identidad y entrada históricas permanecen inmutables")
    exigir(sql(f"SELECT count(*)=1 AND bool_and(fecha_salida=(instante_salida AT TIME ZONE "
               f"'America/Mexico_City')::date AND hora_salida=(instante_salida AT TIME ZONE "
               f"'America/Mexico_City')::time AND instante_salida>=instante_entrada) "
               f"FROM movimiento_estacionamiento WHERE lectura_salida_id='{identificador_salida}'") == "t",
           "un solo cierre con fecha, hora y zona coherentes")
    exigir(autorizada(salida(uid, identificador_salida)), "replay autorizado")
    exigir(salida(UIDS[2], identificador_salida)[0] == 409, "UUID de salida en conflicto")
    sql(f"UPDATE asociacion_tarjeta_rfid1 SET estado='CANCELADA',cancelada_en=now() WHERE uid_canonico='{uid}'")
    exigir(autorizada(salida(uid, identificador_salida)), "replay precede cancelación")

    uid = UIDS[3]
    exigir(autorizada(entrada(uid)), "entrada de empleado")
    sql("UPDATE configuracion_estacionamiento SET zona_horaria='Zona/Invalida' WHERE id=1")
    exigir(salida(uid)[0] == 503, "zona inválida devuelve fallo operacional")
    exigir(autorizada(salida(UIDS[0], identificador_salida)), "replay funciona incluso con zona inválida")
    sql("UPDATE configuracion_estacionamiento SET zona_horaria='America/Mexico_City' WHERE id=1")
    lectura = str(uuid.uuid4())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as grupo:
        respuestas = list(grupo.map(lambda _: salida(uid, lectura), range(2)))
    exigir(all(autorizada(r) for r in respuestas), "misma UUID y UID simultáneos reproducen un cierre")
    exigir(sql(f"SELECT count(*) FROM movimiento_estacionamiento WHERE lectura_salida_id='{lectura}'") == "1",
           "UUID de salida única")

    uid_a, uid_b = UIDS[12:14]
    exigir(autorizada(entrada(uid_a)) and autorizada(entrada(uid_b)), "entradas para UUID compartida")
    lectura = str(uuid.uuid4())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as grupo:
        respuestas = list(grupo.map(lambda tarjeta: salida(tarjeta, lectura), (uid_a, uid_b)))
    exigir(sum(autorizada(r) for r in respuestas) == 1 and sum(r[0] == 409 for r in respuestas) == 1,
           "UUID simultánea con distintos UID autoriza solo a uno y rechaza al otro")
    exigir(sql(f"SELECT count(*) FROM movimiento_estacionamiento WHERE lectura_salida_id='{lectura}'") == "1",
           "la colisión concurrente no duplica cierres")

    probar_carreras()
    probar_cancelacion(sys.modules[__name__], dueno, csrf, UIDS[16:18])
    probar_respuesta_perdida()
    for indice, perdidas in ((11, 1), (14, 2)):
        exigir(autorizada(entrada(UIDS[indice])), "entrada para integración serial y HTTP incierto")
        integrar(BASE, TOKEN, UIDS[indice], perdidas, sql, exigir)
    uid = UIDS[10]
    exigir(autorizada(entrada(uid)) and autorizada(salida(uid)), "preparación para regresión de reloj")
    sql(f"UPDATE movimiento_estacionamiento SET instante_salida=now()+interval '1 day', "
        f"fecha_salida=((now()+interval '1 day') AT TIME ZONE 'America/Mexico_City')::date, "
        f"hora_salida=((now()+interval '1 day') AT TIME ZONE 'America/Mexico_City')::time "
        f"WHERE uid_historico='{uid}'")
    regresion = entrada(uid)
    exigir(regresion[0] >= 500 and regresion[1].get("resultado") != "AUTORIZADA",
           f"reloj regresivo falla cerrado: HTTP {regresion[0]}, decisión {regresion[1].get('resultado')}")
    exigir(sql(f"SELECT count(*) FROM movimiento_estacionamiento WHERE uid_historico='{uid}'") == "1",
           "el reloj regresivo no crea entrada")
    uid = UIDS[15]
    exigir(autorizada(entrada(uid)), "entrada para verificar reloj de salida regresivo")
    sql(f"UPDATE movimiento_estacionamiento SET instante_entrada=now()+interval '1 day', "
        f"fecha_entrada=((now()+interval '1 day') AT TIME ZONE 'America/Mexico_City')::date, "
        f"hora_entrada=((now()+interval '1 day') AT TIME ZONE 'America/Mexico_City')::time "
        f"WHERE uid_historico='{uid}'")
    exigir(salida(uid)[0] == 503, "la salida anterior a la entrada falla cerrada")
    exigir(sql(f"SELECT count(*) FROM movimiento_estacionamiento WHERE uid_historico='{uid}' "
               "AND instante_salida IS NULL") == "1", "la salida regresiva no cierra el movimiento")
    logs = subprocess.run(["podman", "logs", API_CONTAINER], capture_output=True, text=True, check=True)
    logs_db = subprocess.run(["podman", "logs", DB_CONTAINER], capture_output=True, text=True, check=True)
    registro = logs.stdout + logs.stderr + logs_db.stdout + logs_db.stderr
    sensibles = [TOKEN, "dueno-stage1@example.invalid", "cliente-stage1@example.invalid"] + UIDS
    exigir(all(valor not in registro for valor in sensibles), "logs sin UID, correos ni Bearer sintéticos")
    print(f"Aceptación API/PostgreSQL RFID3: {COMPROBACIONES} comprobaciones aprobadas.")


if __name__ == "__main__":
    probar()
