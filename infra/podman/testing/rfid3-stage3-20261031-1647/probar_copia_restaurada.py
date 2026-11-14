"""Prueba salidas con fixtures que se eliminan solo de PostgreSQL desechable."""

import os
from pathlib import Path
import json
import re
import secrets
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid


RAIZ = Path('/mnt/new-volume/SmartParking')
PROYECTO = 'smartparking-rfid3-stage3-20261031-1647'
DB = PROYECTO + '-db-1'
API = PROYECTO + '-api-1'
IMAGEN = '309df6a69722d06c99ecc94e520fa290df2949af58c19922d58de614adfdf840'


def verificar_aislamiento(imagen_esperada=IMAGEN):
    if os.environ.get('RFID3_STAGE1_DB_CONTAINER') != DB or os.environ.get('RFID3_STAGE1_API_CONTAINER') != API:
        raise RuntimeError('El entorno no apunta al proyecto desechable esperado.')
    for contenedor in (DB, API):
        etiqueta = subprocess.check_output(
            ['podman', 'inspect', '--format', '{{index .Config.Labels "com.smartparking.testing.run"}}', contenedor],
            text=True).strip()
        if etiqueta != PROYECTO:
            raise RuntimeError('Un contenedor no pertenece al ensayo desechable.')
    imagen = subprocess.check_output(['podman', 'inspect', '--format', '{{.Image}}', API], text=True).strip()
    if imagen != imagen_esperada:
        raise RuntimeError('El API desechable no usa la imagen congelada.')
    direcciones = subprocess.check_output(['podman', 'port', API, '8080/tcp'], text=True).splitlines()
    destino = urlsplit(os.environ.get('RFID3_STAGE1_API_URL', ''))
    esperado = '127.0.0.1:{}'.format(destino.port) if destino.port else ''
    if (destino.scheme != 'http' or destino.hostname != '127.0.0.1' or destino.path not in ('', '/')
            or destino.username or destino.password or destino.query or destino.fragment
            or direcciones != [esperado]):
        raise RuntimeError('La URL no corresponde al puerto loopback del API desechable.')
    if (os.environ.get('RFID3_STAGE1_POSTGRES_DB') != 'smartparking_local'
            or os.environ.get('RFID3_STAGE1_POSTGRES_USER') != 'smartparking_local'):
        raise RuntimeError('La base o el usuario no corresponden al ensayo.')
    protegido = RAIZ / 'infra/podman/testing/rfid3-stage3-20261031-1647/aislado.env'
    credenciales = dict(linea.split('=', 1) for linea in protegido.read_text().splitlines())
    if os.environ.get('RFID3_STAGE1_TOKEN') != credenciales['RFID3_STAGE1_TOKEN']:
        raise RuntimeError('La credencial no coincide con la sintética congelada.')
    inspeccion = json.loads(subprocess.check_output(['podman', 'inspect', API, DB, 'smartparking-db-1'], text=True))
    api, base, persistente = inspeccion
    entorno_api = dict(valor.split('=', 1) for valor in api['Config']['Env'] if '=' in valor)
    if (entorno_api.get('RFID1_TOKEN_SHA256') != credenciales['RFID3_STAGE1_TOKEN_SHA256']
            or entorno_api.get('POSTGRES_HOST') != 'db'):
        raise RuntimeError('El API no usa el hash de la credencial sintética.')
    red_esperada = PROYECTO + '_pruebas'
    if set(api['NetworkSettings']['Networks']) != {red_esperada} or set(base['NetworkSettings']['Networks']) != {red_esperada}:
        raise RuntimeError('La API o base no están en la red aislada esperada.')
    if 'db' not in (base['NetworkSettings']['Networks'][red_esperada].get('Aliases') or []):
        raise RuntimeError('El alias db no pertenece a la base desechable.')
    red = json.loads(subprocess.check_output(['podman', 'network', 'inspect', red_esperada], text=True))[0]
    if not red.get('internal'):
        raise RuntimeError('La red de prueba no es interna.')
    pruebas = [m for m in base['Mounts'] if m.get('Destination') == '/var/lib/postgresql']
    produccion = [m for m in persistente['Mounts'] if m.get('Destination') == '/var/lib/postgresql']
    if (len(pruebas) != 1 or len(produccion) != 1 or pruebas[0].get('Type') != 'volume'
            or pruebas[0].get('Name') != PROYECTO + '_datos'
            or pruebas[0].get('Name') == produccion[0].get('Name')
            or pruebas[0].get('Source') == produccion[0].get('Source')):
        raise RuntimeError('El volumen de prueba no es distinto del persistente.')


def secuencias(aceptacion):
    nombres = aceptacion.sql("SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY 1;").splitlines()
    if any(not re.fullmatch(r'[a-z_][a-z0-9_]*', n) for n in nombres):
        raise RuntimeError('Nombre de secuencia inesperado.')
    valores = {}
    for nombre in nombres:
        campos = aceptacion.sql('SELECT last_value,is_called FROM public."' + nombre + '";').split('|')
        if len(campos) != 2 or not campos[0].isdigit() or campos[1] not in ('t', 'f'):
            raise RuntimeError('Estado de secuencia inesperado.')
        valores[nombre] = campos
    return valores


def crear_fixtures(a, etiqueta, cantidad=10):
    for uid in a.UIDS[:cantidad]:
        if a.sql("SELECT count(*) FROM asociacion_tarjeta_rfid1 WHERE uid_canonico='" + uid + "';") != '0':
            raise RuntimeError('Colisión de una tarjeta sintética.')
        fila = a.sql("WITH persona AS (INSERT INTO empleado(nombres,primer_apellido) "
                     "VALUES ('" + etiqueta + "','Prueba') RETURNING id), "
                     "tarjeta AS (INSERT INTO asociacion_tarjeta_rfid1(uid_canonico,empleado_id) "
                     "SELECT '" + uid + "', id FROM persona RETURNING asociacion_id,empleado_id) "
                     "SELECT asociacion_id,empleado_id FROM tarjeta;").split('|')
        if len(fila) != 2 or not all(campo.isdigit() for campo in fila):
            raise RuntimeError('No se pudo identificar un fixture sintético.')


def probar_restricciones(a, uuid_salida, uuid_entrada):
    otra = str(uuid.uuid4())
    consulta = """
    DO $prueba$
    DECLARE unica boolean := false; requiere_instante boolean := false;
    BEGIN
      BEGIN
        UPDATE movimiento_estacionamiento SET lectura_salida_id='%s',
          instante_salida=instante_entrada, fecha_salida=fecha_entrada, hora_salida=hora_entrada
        WHERE lectura_id='%s';
      EXCEPTION WHEN unique_violation THEN unica := true; END;
      BEGIN
        UPDATE movimiento_estacionamiento SET lectura_salida_id='%s' WHERE lectura_id='%s';
      EXCEPTION WHEN check_violation THEN requiere_instante := true; END;
      IF NOT unica OR NOT requiere_instante THEN RAISE EXCEPTION 'Fallo de restricciones de prueba'; END IF;
    END $prueba$;
    """ % (uuid_salida, uuid_entrada, otra, uuid_entrada)
    a.sql(consulta)


def esperar_bloqueo_especifico(a):
    for _ in range(60):
        bloqueadas = a.sql("SELECT count(*) FROM pg_stat_activity espera WHERE espera.datname=current_database() "
                          "AND EXISTS (SELECT 1 FROM pg_stat_activity bloqueador "
                          "WHERE bloqueador.pid=ANY(pg_blocking_pids(espera.pid)) "
                          "AND bloqueador.application_name='rfid3_bloqueo');")
        if int(bloqueadas):
            return
        time.sleep(0.02)
    raise RuntimeError('La solicitud no esperó el bloqueo sintético esperado.')


def limpiar(a, etiqueta, estados_secuencias):
    empleados = "SELECT id FROM empleado WHERE nombres='" + etiqueta + "' AND primer_apellido='Prueba'"
    asociaciones = "SELECT asociacion_id FROM asociacion_tarjeta_rfid1 WHERE empleado_id IN (" + empleados + ")"
    a.sql("BEGIN; DELETE FROM movimiento_estacionamiento WHERE asociacion_id IN (" + asociaciones + "); "
          "ALTER TABLE asociacion_tarjeta_rfid1 DISABLE TRIGGER asociacion_tarjeta_rfid1_historial_bud; "
          "DELETE FROM asociacion_tarjeta_rfid1 WHERE empleado_id IN (" + empleados + "); "
          "ALTER TABLE asociacion_tarjeta_rfid1 ENABLE TRIGGER asociacion_tarjeta_rfid1_historial_bud; "
          "DELETE FROM empleado WHERE id IN (" + empleados + "); COMMIT;")
    if a.sql("SELECT count(*) FROM empleado WHERE nombres='" + etiqueta + "' AND primer_apellido='Prueba';") != '0':
        raise RuntimeError('Permanecen fixtures sintéticos.')
    for nombre, (valor, llamado) in estados_secuencias.items():
        a.sql("SELECT setval('public.\"" + nombre + "\"'::regclass," + valor + "," +
              ('true' if llamado == 't' else 'false') + ");")
    estado = a.sql("SELECT tgenabled FROM pg_trigger WHERE tgrelid='public.asociacion_tarjeta_rfid1'::regclass "
                   "AND tgname='asociacion_tarjeta_rfid1_historial_bud';")
    if estado != 'O':
        raise RuntimeError('El trigger de historial no quedó habilitado.')


def main():
    verificar_aislamiento()
    sys.path.insert(0, str(RAIZ / 'infra/podman/testing/rfid3-stage1'))
    import aceptacion as a
    estado_original = secuencias(a)
    etiqueta = 'ST3' + secrets.token_hex(16)
    if a.sql("SELECT count(*) FROM empleado WHERE nombres='" + etiqueta + "';") != '0':
        raise RuntimeError('Colisión del marcador sintético.')
    try:
        crear_fixtures(a, etiqueta)
        uid, otro, tercero = a.UIDS[:3]
        entrada = str(uuid.uuid4())
        salida = str(uuid.uuid4())
        entrada_otra = str(uuid.uuid4())
        a.exigir(a.autorizada(a.entrada(uid, entrada)), 'entrada sintética autorizada')
        a.exigir(a.autorizada(a.salida(uid, salida)), 'salida sintética autorizada')
        a.exigir(a.autorizada(a.salida(uid, salida)), 'replay sintético autorizado')
        a.exigir(a.denegada(a.salida(uid), 'SIN_ENTRADA_ABIERTA'), 'salida duplicada denegada')
        a.exigir(a.salida(otro, salida)[0] == 409, 'UUID con otra tarjeta rechazada')
        a.exigir(a.autorizada(a.entrada(uid)), 'entrada posterior a salida')
        a.exigir(a.autorizada(a.entrada(tercero, entrada_otra)), 'entrada para restricciones')
        probar_restricciones(a, salida, entrada_otra)
        a.esperar_bloqueo_api = lambda: esperar_bloqueo_especifico(a)
        a.probar_carreras()
        registros = ''
        for nombre in (API, DB):
            proceso = subprocess.run(['podman', 'logs', nombre], capture_output=True, text=True, check=True)
            registros += proceso.stdout + proceso.stderr
        if any(secreto in registros for secreto in [a.TOKEN] + a.UIDS[:10]):
            raise RuntimeError('Los registros contienen un identificador sintético o credencial.')
        print('Fixtures aislados: salida, replay, denegación, restricciones y concurrencia aprobados.')
    finally:
        limpiar(a, etiqueta, estado_original)
        print('Limpieza sintética y trigger verificados.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('PRUEBA_AISLADA_BLOQUEADA:', type(error).__name__)
        raise SystemExit(1) from None
