"""Inspecciona y respalda el ESP32 durante una pausa supervisada del bridge."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time


RAIZ = Path('/mnt/new-volume/SmartParking')
TRABAJO = RAIZ / 'infra/podman/testing/rfid3-stage3-20261031-1647'
FIRMWARE = RAIZ / 'firmware/esp32'
ANTERIOR = FIRMWARE / '.backups/20261031-153904-rfid3-stage2-pretest/manifiesto.json'
ACTIVADOR = FIRMWARE / '.backups/20261031-083218-rfid3-aceptacion-final/activar_final.py'
PUERTO = '/dev/ttyACM0'


def nombre_seguro(nombre):
    """Normaliza solo rutas absolutas provenientes del inventario conocido."""
    if not isinstance(nombre, str) or not nombre.startswith('/'):
        raise RuntimeError('Ruta remota no absoluta.')
    ruta = PurePosixPath(nombre)
    if '..' in ruta.parts or any(not parte.isascii() for parte in ruta.parts):
        raise RuntimeError('Ruta remota insegura.')
    partes = ruta.parts[1:]
    if not partes or any(parte in ('', '.', '..') for parte in partes):
        raise RuntimeError('Ruta remota vacía o insegura.')
    return '/'.join(partes)


def guardar_nuevo(ruta, contenido):
    ruta.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as archivo:
        archivo.write(contenido)


def inventario_remoto(repl):
    codigo = '''import os, ujson\nrutas=[]\ndef caminar(d,n):\n if n>6: raise RuntimeError('profundidad excedida')\n for entrada in os.ilistdir(d):\n  if len(rutas)>=128: raise RuntimeError('limite de archivos')\n  nombre,tipo=entrada[0],entrada[1]\n  ruta=(d.rstrip('/')+'/'+nombre)\n  if tipo & 0xf000 == 0x4000: caminar(ruta,n+1)\n  elif tipo & 0xf000 == 0x8000: rutas.append([ruta,os.stat(ruta)[6]])\n  else: raise RuntimeError('tipo inesperado')\ncaminar('/',0)\nprint('ARCHIVOS:'+ujson.dumps(rutas))'''
    resultado = repl.consultar_linea('ARCHIVOS:', 'exec({!r})'.format(codigo))
    archivos = json.loads(resultado)
    if len(archivos) > 128:
        raise RuntimeError('Demasiados archivos remotos.')
    nombres = {}
    for ruta, tamano in archivos:
        nombre = nombre_seguro(ruta)
        if nombre in nombres or not isinstance(tamano, int) or tamano < 0 or tamano > 100000:
            raise RuntimeError('Inventario remoto inesperado.')
        nombres[nombre] = tamano
    return nombres


def observar_arranque(repl):
    """Exige arranque y PONG sin registrar ninguna posible trama de tarjeta."""
    buffer = bytearray()
    inicio = time.monotonic()
    siguiente_ping = inicio
    arranques = pongs = 0
    rfid1 = rfid3 = False
    while time.monotonic() - inicio < 30:
        ahora = time.monotonic()
        if ahora >= siguiente_ping:
            repl.serie.write(b'PING\r\n')
            siguiente_ping = ahora + 2
        buffer.extend(repl.serie.read(512))
        while b'\n' in buffer:
            linea, _, resto = buffer.partition(b'\n')
            buffer = bytearray(resto)
            texto = linea.decode('ascii', 'ignore').strip()
            if texto == 'PONG':
                pongs += 1
            elif texto == 'READY,1':
                arranques += 1
            elif texto.startswith('RFID_READER,READY,'):
                rfid1 = True
            elif texto.startswith('RFID_DIAG,RFID3,READY,'):
                rfid3 = True
            elif texto.startswith(('RFID,', 'RFID2,', 'RFID3,')):
                raise RuntimeError('Lectura no solicitada durante mantenimiento.')
            elif texto.startswith(('RFID_READER,ERROR', 'RFID_DIAG,RFID3,ERROR', 'Traceback')):
                raise RuntimeError('Error durante el arranque del firmware original.')
        if arranques > 1:
            raise RuntimeError('Reinicio inesperado durante la observación.')
        if arranques == 1 and rfid1 and rfid3 and pongs >= 3:
            print('ARRANQUE_ORIGINAL_OK; RFID1/RFID3 READY; PONG={}'.format(pongs), flush=True)
            return
    raise RuntimeError('No se confirmó el arranque del firmware original.')


def comprobar_exclusividad():
    if not stat.S_ISCHR(os.stat(PUERTO).st_mode) or not os.access(PUERTO, os.R_OK | os.W_OK):
        raise RuntimeError('El dispositivo USB no existe o no es accesible.')
    for comando in (['fuser', '-s', PUERTO], ['lsof', '-n', '-t', PUERTO]):
        proceso = subprocess.run(comando, capture_output=True, text=True, timeout=5)
        if proceso.returncode != 1 or proceso.stdout.strip() or proceso.stderr.strip():
            raise RuntimeError('El USB no está libre o la inspección de propietarios falló.')
    estado = subprocess.run(['systemctl', '--user', 'show', 'smartparking-rfid1-bridge.service',
                             '--property=ActiveState,SubState,MainPID'],
                            capture_output=True, text=True, check=True, timeout=5).stdout.splitlines()
    if set(estado) != {'ActiveState=inactive', 'SubState=dead', 'MainPID=0'}:
        raise RuntimeError('El bridge no está confirmado como inactivo.')


def main():
    comprobar_exclusividad()
    sys.path.insert(0, str(FIRMWARE / 'tools'))
    from transferencia_repl import ReplFriendly
    spec = importlib.util.spec_from_file_location('activador_rfid', ACTIVADOR)
    activador = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(activador)
    esperado = {}
    for dato in json.loads(ANTERIOR.read_text())['archivos']:
        nombre = nombre_seguro(dato['ruta'])
        if nombre != 'maintenance.flag':
            if nombre in esperado:
                raise RuntimeError('Manifiesto previo duplicado.')
            esperado[nombre] = dato
    destino = TRABAJO / 'firmware-anterior'
    destino.mkdir(mode=0o700)
    repl = ReplFriendly(PUERTO)
    bandera_intentada = False
    prompt = False
    seguro_para_arranque = False
    try:
        repl.serie.write(b'\x03')
        try:
            repl._leer_prompt(3.0)
            prompt = True
        except TimeoutError:
            bandera_intentada = True
            repl.serie.write(b'STOP\r\n')
            repl._leer_prompt(20.0)
            prompt = True
        repl.preparar_escritura()
        if bandera_intentada:
            if not repl.existe('maintenance.flag'):
                raise RuntimeError('STOP no creó la bandera esperada.')
        else:
            if repl.existe('maintenance.flag'):
                raise RuntimeError('Bandera de mantenimiento preexistente.')
            bandera_intentada = True
            repl.comando("f=open('maintenance.flag','w'); f.write('1\\n'); f.close()")
        activador.verificar_identidad(repl)
        capacidades = json.loads(repl.consultar_linea(
            'CAPACIDADES:',
            "import sys,os,time,machine,gc,ujson; gc.collect(); print('CAPACIDADES:'+ujson.dumps([sys.implementation.name,list(sys.implementation.version),hasattr(os,'urandom'),all(hasattr(time,x) for x in ('ticks_ms','ticks_add','ticks_diff')),all(hasattr(machine,x) for x in ('UART','Pin','PWM')),gc.mem_free()]))"))
        if capacidades[0] != 'micropython' or not all(capacidades[2:5]) or capacidades[5] < 40000:
            raise RuntimeError('Las capacidades o la memoria disponible no cumplen el preflight.')
        print('IDENTIDAD_VERIFICADA; RUNTIME=' + json.dumps(capacidades), flush=True)
        observados = inventario_remoto(repl)
        observados.pop('maintenance.flag', None)
        if set(observados) != set(esperado):
            raise RuntimeError('El inventario instalado difiere del cierre de Stage 2.')
        registros = []
        for nombre in sorted(observados):
            tamano = observados[nombre]
            if tamano != esperado[nombre]['bytes']:
                raise RuntimeError('Un tamaño instalado difiere del cierre de Stage 2.')
            remoto = '/' + nombre
            huella = repl.sha256_remoto(remoto)
            if huella != esperado[nombre]['sha256']:
                raise RuntimeError('Un archivo instalado difiere del cierre de Stage 2.')
            contenido = repl.descargar(remoto, tamano)
            if hashlib.sha256(contenido).hexdigest() != huella or repl.sha256_remoto(remoto) != huella:
                raise RuntimeError('El respaldo no coincide al releer.')
            guardar_nuevo(destino / nombre, contenido)
            registros.append({'ruta': nombre, 'bytes': tamano, 'sha256': huella})
        guardar_nuevo(destino / 'manifiesto.json',
                      (json.dumps(registros, indent=2, sort_keys=True) + '\n').encode())
        for dato in registros:
            contenido = (destino / dato['ruta']).read_bytes()
            if len(contenido) != dato['bytes'] or hashlib.sha256(contenido).hexdigest() != dato['sha256']:
                raise RuntimeError('El respaldo local no pasó la verificación final.')
        print('SNAPSHOT_VERIFICADO archivos={}'.format(len(registros)), flush=True)
        seguro_para_arranque = True
    finally:
        if sys.exc_info()[0] is not None:
            prompt = False
        try:
            if bandera_intentada:
                if not prompt:
                    try:
                        repl._leer_prompt(4.0)
                    except TimeoutError:
                        repl.cerrar()
                        repl = ReplFriendly(PUERTO)
                        repl.entrar(permitir_stop=True)
                repl.preparar_escritura()
                if repl.existe('maintenance.flag'):
                    contenido = repl.consultar_linea(
                        'FLAG:', "f=open('maintenance.flag','rb'); b=f.read(); f.close(); print('FLAG:'+ubinascii.hexlify(b).decode())")
                    if contenido != '310a':
                        raise RuntimeError('La bandera tiene contenido inesperado.')
                    repl.comando("os.remove('maintenance.flag')")
                repl.serie.write(b'import machine; machine.reset()\r\n')
                observar_arranque(repl)
        except BaseException as error:
            seguro_para_arranque = False
            print('RECUPERACION_FIRMWARE_INCOMPLETA:', type(error).__name__, flush=True)
        finally:
            repl.cerrar()
    if not seguro_para_arranque:
        raise RuntimeError('No se completó la inspección y recuperación del firmware.')


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print('INSPECCION_BLOQUEADA:', type(error).__name__, flush=True)
        raise SystemExit(1) from None
