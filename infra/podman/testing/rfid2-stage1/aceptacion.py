"""Comprueba autorización RFID 2 contra API y PostgreSQL desechables."""

import concurrent.futures
import contextlib
import io
import json
import os
import pty
import secrets
import select
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid


BASE = os.environ["RFID2_STAGE1_API_URL"].rstrip("/")
TOKEN = os.environ["RFID2_STAGE1_TOKEN"]
API_CONTENEDOR = os.environ["RFID2_STAGE1_API_CONTAINER"]
DB_CONTENEDOR = os.environ["RFID2_STAGE1_DB_CONTAINER"]
DB = os.environ["RFID2_STAGE1_POSTGRES_DB"]
DB_USER = os.environ["RFID2_STAGE1_POSTGRES_USER"]
UIDS = [secrets.token_hex(4).upper() for _ in range(5)]
APROBACIONES = 0
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "rfid1-bridge")))
from bridge import SesionBridge
from cliente_capturas import ClienteCapturas
from puerto_serie import PuertoSerie


def exigir(condicion, detalle):
    global APROBACIONES
    if not condicion:
        raise AssertionError(detalle)
    APROBACIONES += 1


def sql(consulta):
    resultado = subprocess.run(
        ["podman", "exec", "-i", DB_CONTENEDOR, "psql", "-X", "-qAt",
         "-v", "ON_ERROR_STOP=1", "-U", DB_USER, "-d", DB],
        input=consulta, text=True, capture_output=True, check=True,
    )
    return resultado.stdout.strip()


def preparar_datos():
    cliente = str(uuid.uuid4())
    uids = UIDS
    consulta = f"""
    INSERT INTO cuenta (id,nombres,primer_apellido,segundo_apellido,correo,correo_normalizado,
        rol,estado,hash_contrasena_acceso,revision_acceso,creada_en,actualizada_en)
    VALUES ('{cliente}','Cliente Sintético','Prueba',NULL,'cliente-rfid2@example.invalid',
        'cliente-rfid2@example.invalid','CLIENTE','ACTIVA','hash-sintetico',1,now(),now());
    INSERT INTO empleado (nombres,primer_apellido) VALUES
        ('Empleado Sintético 1','Prueba'),('Empleado Sintético 2','Prueba'),
        ('Empleado Sintético 3','Prueba'),('Empleado Sintético 4','Prueba');
    INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico,cliente_id) VALUES ('{uids[0]}','{cliente}');
    INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico,empleado_id)
        SELECT '{uids[1]}',id FROM empleado WHERE nombres='Empleado Sintético 1';
    INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico,empleado_id)
        SELECT '{uids[2]}',id FROM empleado WHERE nombres='Empleado Sintético 2';
    UPDATE asociacion_tarjeta_rfid1 SET estado='CANCELADA',cancelada_en=now()
        WHERE uid_canonico='{uids[2]}';
    INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico,empleado_id)
        SELECT '{uids[3]}',id FROM empleado WHERE nombres='Empleado Sintético 3';
    INSERT INTO asociacion_tarjeta_rfid1 (uid_canonico,empleado_id)
        SELECT '{uids[4]}',id FROM empleado WHERE nombres='Empleado Sintético 4';
    """
    sql(consulta)


def solicitud(metodo, ruta, cuerpo=None, token=None, timeout=8):
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    encabezados = {"Accept": "application/json"}
    if datos is not None:
        encabezados["Content-Type"] = "application/json"
    if token is not None:
        encabezados["Authorization"] = "Bearer " + token
    peticion = urllib.request.Request(BASE + ruta, data=datos, headers=encabezados, method=metodo)
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            return respuesta.status, respuesta.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()
    except (urllib.error.URLError, TimeoutError):
        return 503, ""


def entrada(uid, lectura_id=None):
    return solicitud("POST", "/api/v1/dispositivos/rfid-2/entradas",
                     {"uid": uid, "lecturaId": lectura_id or str(uuid.uuid4())}, TOKEN)


def conteo(criterio, valor):
    permitido = {"uid_historico", "lectura_id"}
    if criterio not in permitido:
        raise ValueError("criterio no permitido")
    return int(sql(f"SELECT count(*) FROM movimiento_estacionamiento WHERE {criterio}='{valor}'"))


def cuerpo_decision(respuesta):
    try:
        return json.loads(respuesta)
    except ValueError:
        return {}


def probar_pty_api_real(uid, lectura_id):
    maestro, esclavo = pty.openpty()
    nombre_esclavo = os.ttyname(esclavo)
    os.close(esclavo)
    puerto = PuertoSerie(nombre_esclavo)
    cliente = ClienteCapturas(BASE, TOKEN)
    sesion = SesionBridge(cliente, intervalo_ping=0.1, tiempo_espera_pong=2, intervalo_lectura=0.02)
    detener = threading.Event()
    errores = []
    salida = io.StringIO()

    def ejecutar_bridge():
        try:
            with contextlib.redirect_stdout(salida):
                sesion.ejecutar(puerto, detener)
        except Exception as error:
            errores.append(error)

    hilo = threading.Thread(target=ejecutar_bridge, daemon=True)
    hilo.start()
    buffer = bytearray()
    resultado = None
    try:
        os.write(maestro, f"RFID2,{lectura_id},{uid}\r\n".encode("ascii"))
        limite = time.monotonic() + 10
        while time.monotonic() < limite and resultado is None:
            listos, _, _ = select.select([maestro], [], [], 0.1)
            if not listos:
                continue
            buffer.extend(os.read(maestro, 1024))
            while b"\n" in buffer:
                linea, _, resto = buffer.partition(b"\n")
                buffer[:] = resto
                linea = linea.removesuffix(b"\r")
                if linea == b"PING":
                    os.write(maestro, b"PONG\n")
                prefijo = f"RFID2_RESULT,{lectura_id},".encode("ascii")
                if linea.startswith(prefijo):
                    resultado = linea.decode("ascii")
        exigir(resultado == f"RFID2_RESULT,{lectura_id},AUTORIZADA",
               "PTY serial entrega la decisión real de API con su UUID")
        exigir(uid not in salida.getvalue() and TOKEN not in salida.getvalue(),
               "bridge no registra UID ni Bearer durante la integración PTY")
        exigir(not errores, "bridge PTY permanece activo durante el intercambio")
    finally:
        detener.set()
        hilo.join(timeout=2)
        sesion.estado_dispositivo.cerrar()
        puerto.cerrar()
        os.close(maestro)


def probar():
    exigir(sql("SELECT version FROM flyway_schema_history WHERE version='13' AND success") == "13",
           "Flyway V13 se aplicó en PostgreSQL desechable")
    exigir(solicitud("POST", "/api/v1/dispositivos/rfid-2/entradas",
                     {"uid": UIDS[0], "lecturaId": str(uuid.uuid4())})[0] == 401,
           "sin Bearer se rechaza la ruta técnica")
    exigir(solicitud("POST", "/api/v1/dispositivos/rfid-2/entradas",
                     {"uid": UIDS[0], "lecturaId": str(uuid.uuid4())}, "incorrecto")[0] == 401,
           "Bearer incorrecto se rechaza")
    exigir(solicitud("GET", "/api/v1/panel", token=TOKEN)[0] == 401,
           "Bearer del dispositivo no autoriza rutas DUENO")

    lectura = str(uuid.uuid4())
    estado, texto = entrada(UIDS[0], lectura)
    exigir(estado == 200 and cuerpo_decision(texto).get("resultado") == "AUTORIZADA",
           "CLIENTE ACTIVO sin movimiento obtiene autorización")
    exigir(conteo("lectura_id", lectura) == 1 and conteo("uid_historico", UIDS[0]) == 1,
           "se persiste exactamente un movimiento")
    exigir(sql(f"""SELECT tipo_persona='CLIENTE' AND cliente_id IS NOT NULL AND empleado_id IS NULL
        AND fecha_entrada=(instante_entrada AT TIME ZONE 'America/Mexico_City')::date
        AND hora_entrada=(instante_entrada AT TIME ZONE 'America/Mexico_City')::time
        AND fecha_salida IS NULL AND hora_salida IS NULL AND instante_salida IS NULL
        FROM movimiento_estacionamiento WHERE lectura_id='{lectura}'""") == "t",
        "identidad, hora local y campos de salida se conservan correctamente")
    exigir(entrada(UIDS[0], lectura)[0] == 200
           and cuerpo_decision(entrada(UIDS[0], lectura)[1]).get("resultado") == "AUTORIZADA",
           "replay idéntico devuelve la autorización confirmada")
    exigir(cuerpo_decision(entrada(UIDS[0])[1]).get("motivo") == "ENTRADA_PENDIENTE",
           "una nueva lectura con movimiento abierto se deniega")
    conflicto, texto_conflicto = entrada(UIDS[1], lectura)
    exigir(conflicto == 409 and "UID" not in texto_conflicto.upper(),
           "reutilizar lecturaId con otro UID se rechaza sin exponer identidad")
    cancelar = sql(f"UPDATE asociacion_tarjeta_rfid1 SET estado='CANCELADA',cancelada_en=now() "
                   f"WHERE uid_canonico='{UIDS[0]}' RETURNING estado")
    exigir(cancelar == "CANCELADA" and entrada(UIDS[0], lectura)[0] == 200,
           "replay autorizado precede el estado actual de una tarjeta cancelada")

    desconocida, texto_desconocida = entrada("DEADBEEF")
    exigir(desconocida == 200 and cuerpo_decision(texto_desconocida).get("motivo") == "TARJETA_DESCONOCIDA"
           and conteo("uid_historico", "DEADBEEF") == 0,
           "UID desconocido se deniega sin movimiento")
    estado_cancelada, texto_cancelada = entrada(UIDS[2])
    exigir(estado_cancelada == 200 and cuerpo_decision(texto_cancelada).get("motivo") == "TARJETA_CANCELADA"
           and conteo("uid_historico", UIDS[2]) == 0,
           "tarjeta cancelada se deniega sin movimiento")

    solicitudes = [str(uuid.uuid4()) for _ in range(12)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as grupo:
        respuestas = list(grupo.map(lambda lectura_id: entrada(UIDS[3], lectura_id), solicitudes))
    decisiones = [cuerpo_decision(texto).get("resultado") for estado, texto in respuestas if estado == 200]
    exigir(len(decisiones) == 12 and decisiones.count("AUTORIZADA") == 1
           and decisiones.count("DENEGADA") == 11,
           "lecturas concurrentes permiten como máximo una entrada abierta")
    exigir(sql(f"SELECT count(*) FROM movimiento_estacionamiento WHERE uid_historico='{UIDS[3]}' "
               "AND instante_salida IS NULL") == "1",
           "PostgreSQL impide movimientos abiertos duplicados")
    exigir(sql(f"SELECT tipo_persona='EMPLEADO' AND cliente_id IS NULL AND empleado_id IS NOT NULL "
               f"FROM movimiento_estacionamiento WHERE uid_historico='{UIDS[3]}' "
               "AND instante_salida IS NULL") == "t",
           "movimiento EMPLEADO conserva la identidad histórica correcta")

    token_invalido = solicitud("POST", "/api/v1/dispositivos/rfid-2/entradas",
                               {"uid": UIDS[4], "lecturaId": str(uuid.uuid4())}, "incorrecto")
    exigir(token_invalido[0] == 401 and conteo("uid_historico", UIDS[4]) == 0,
           "credencial inválida no crea entrada")

    lectura_serial = str(uuid.uuid4())
    probar_pty_api_real(UIDS[4], lectura_serial)
    exigir(conteo("lectura_id", lectura_serial) == 1
           and conteo("uid_historico", UIDS[4]) == 1,
           "lectura PTY integra serial, bridge, API y movimiento persistido")

    lectura_fallida = str(uuid.uuid4())
    subprocess.run(["podman", "stop", DB_CONTENEDOR], check=True, capture_output=True)
    try:
        estado, texto_fallo = entrada(UIDS[4], lectura_fallida)
        exigir(estado == 503 and "AUTORIZADA" not in texto_fallo and UIDS[4] not in texto_fallo
               and TOKEN not in texto_fallo,
               "falla de base responde sin autorización, UID ni credencial")
    finally:
        subprocess.run(["podman", "start", DB_CONTENEDOR], check=True, capture_output=True)
    for _ in range(30):
        if solicitud("GET", "/actuator/health")[0] == 200:
            break
        import time
        time.sleep(1)
    exigir(solicitud("GET", "/actuator/health")[0] == 200,
           "API se recupera tras restaurar PostgreSQL desechable")
    exigir(conteo("lectura_id", lectura_fallida) == 0,
           "la falla de base no creó un movimiento")

    logs = subprocess.run(["podman", "logs", API_CONTENEDOR], capture_output=True, text=True, check=True)
    registro = logs.stdout + logs.stderr
    exigir(TOKEN not in registro and all(uid not in registro for uid in UIDS),
           "logs de API no contienen UID sintéticos ni Bearer")


if __name__ == "__main__":
    preparar_datos()
    probar()
    print(f"Aceptación API/PostgreSQL RFID2: {APROBACIONES} comprobaciones aprobadas.")
