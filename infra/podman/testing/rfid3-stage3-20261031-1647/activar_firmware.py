"""Coordina instalación ESP32 con callbacks sanitizados y recuperación."""

import importlib.util
from pathlib import Path
import signal
import sys
import time

import inspeccion_firmware as inspeccion
import promocion_firmware as promocion


BASE = Path(__file__).resolve().parent
FUENTE = inspeccion.FIRMWARE
sys.path.insert(0, str(FUENTE / 'tools'))
import instalacion_stage3 as instalacion
from transferencia_repl import ReplFriendly


TEMPORAL = '/sp_rfid3_stage3_20261031_1647'
BOOTSTRAP = FUENTE / '.backups/20261031-083218-rfid3-aceptacion-final/bootstrap_final.py'
ESTADO = {'sesion': None, 'bandera_propia': False}


def abrir_sesion():
    """Registra la sesión antes de permitir que SIGINT interrumpa al llamador."""
    anterior = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
    try:
        repl = ReplFriendly(inspeccion.PUERTO)
        ESTADO['sesion'] = repl
        return repl
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, anterior)


def verificar_identidad(repl):
    spec = importlib.util.spec_from_file_location('activador_anterior', inspeccion.ACTIVADOR)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    modulo.verificar_identidad(repl)


def confirmar_firmware_en_marcha(repl):
    """Exige dos PONG nuevos antes de STOP si aún no se posee la bandera."""
    for _ in range(2):
        confirmado = False
        for intento in range(3):
            previo = bytes(repl._buffer) + repl.serie.read(4096)
            repl._buffer.clear()
            if b'>>>' in previo:
                repl._buffer.extend(previo)
                raise RuntimeError('El dispositivo está en REPL; no se enviará STOP.')
            if any(linea.startswith((b'RFID,', b'RFID2,', b'RFID3,', b'ENROLL_READ,'))
                   for linea in previo.replace(b'\r', b'').split(b'\n')):
                raise RuntimeError('Se observó una lectura no solicitada.')
            repl.serie.write(b'PING\r\n')
            datos = bytearray()
            limite = time.monotonic() + 2
            while time.monotonic() < limite:
                datos.extend(repl.serie.read(512))
                lineas = bytes(datos).replace(b'\r', b'').split(b'\n')
                if b'>>>' in datos:
                    repl._buffer.extend(datos)
                    raise RuntimeError('El dispositivo está en REPL; no se enviará STOP.')
                if any(linea.startswith((b'RFID,', b'RFID2,', b'RFID3,', b'ENROLL_READ,')) for linea in lineas):
                    raise RuntimeError('Se observó una lectura no solicitada.')
                if b'PONG' in lineas:
                    confirmado = True
                    break
            if confirmado:
                break
        if not confirmado:
            raise RuntimeError('No se confirmó firmware en marcha antes de STOP.')


def solicitar_stop(repl):
    try:
        confirmar_firmware_en_marcha(repl)
    except RuntimeError:
        if ESTADO['bandera_propia'] and b'>>>' in repl._buffer:
            repl._leer_prompt(3.0)
            return
        raise
    if not ESTADO['bandera_propia']:
        ESTADO['bandera_propia'] = True
    repl.serie.write(b'STOP\r\n')
    repl._leer_prompt(20.0)


def resincronizar(repl, permitir_crear_bandera=False):
    """Recupera el prompt manteniendo la bandera, incluso tras un ACK perdido."""
    repl = ESTADO['sesion'] or repl
    anterior = repl
    nueva = None
    try:
        try:
            try:
                repl._leer_prompt(3.0)
            except TimeoutError:
                repl.serie.write(b'\x03')
                try:
                    repl._leer_prompt(3.0)
                except TimeoutError:
                    solicitar_stop(repl)
        except Exception:
            repl.cerrar()
            nueva = abrir_sesion()
            repl = nueva
            try:
                repl.entrar(permitir_stop=False)
            except Exception:
                solicitar_stop(repl)
        repl.preparar_escritura()
        existe = repl.existe('/maintenance.flag')
        if existe and not ESTADO['bandera_propia']:
            raise RuntimeError('Se encontró una bandera de mantenimiento ajena.')
        if permitir_crear_bandera and not existe:
            ESTADO['bandera_propia'] = True
            repl.comando("f=open('/maintenance.flag','w'); f.write('1\\n'); f.close()")
        instalacion._bandera(repl)
        ESTADO['sesion'] = repl
        return repl
    except BaseException:
        actual = ESTADO['sesion']
        if actual is not None and actual is not anterior:
            actual.cerrar()
        raise


def verificar_arranque(repl):
    """Verifica imports y tres lectores sin presentar o revelar tarjetas."""
    repl.serie.write(b'\x04')
    repl._leer_prompt(20.0)
    repl.preparar_escritura()
    vacia = repl.consultar_linea(
        'CACHE:', "import sys; n=('config','buzzer','entrada_rfid2','salida_rfid3','comunicacion.serial','comunicacion.protocolo','aplicacion'); print('CACHE:'+str(all(x not in sys.modules for x in n)))")
    if vacia != 'True':
        raise RuntimeError('La caché de módulos no está vacía.')
    importados = repl.consultar_linea(
        'IMPORTS:', 'import config,buzzer,entrada_rfid2,salida_rfid3,comunicacion.serial,comunicacion.protocolo,aplicacion; print(\'IMPORTS:OK\')')
    if importados != 'OK':
        raise RuntimeError('Falló la importación en MicroPython.')
    codigo = '\n'.join(BOOTSTRAP.read_text().splitlines()[1:])
    repl.serie.write(('exec({!r})\r\n'.format(codigo)).encode('ascii'))
    buffer = bytearray()
    lectores = {}
    pongs = arranques = 0
    inicio = siguiente_ping = time.monotonic()
    while time.monotonic() - inicio < 45:
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
            elif texto.startswith(('RFID,', 'RFID2,', 'RFID3,', 'ENROLL_READ,')):
                raise RuntimeError('Se observó una lectura no solicitada.')
            elif texto.startswith(('RFID_READER,ERROR', 'RFID_DIAG,RFID3,ERROR', 'Traceback')):
                raise RuntimeError('Falló la inicialización de un lector.')
            elif texto.startswith('RFID_DIAG,RFID3,DETECCION'):
                raise RuntimeError('Se observó una detección no solicitada.')
            elif texto.startswith('DIAG,'):
                partes = texto.split(',')
                if len(partes) == 4 and partes[1] in ('RFID1', 'RFID2', 'RFID3'):
                    if partes[2] == 'DETECCION' or (partes[2] == 'ESTADO' and partes[3] != 'READY'):
                        raise RuntimeError('Se observó una detección o error de lector.')
                    if partes[2] == 'ESTADO' and partes[3] == 'READY':
                        lectores[partes[1]] = 'READY'
        if arranques > 1:
            raise RuntimeError('Se detectó un reinicio inesperado.')
        if arranques == 1 and len(lectores) == 3 and pongs >= 3:
            print('TRES_LECTORES_READY; PONG={}'.format(pongs), flush=True)
            return {'imports': True, 'lectores': lectores, 'pongs': pongs,
                    'reinicios_inesperados': 0, 'lecturas': 0}
    raise RuntimeError('La placa no confirmó los tres lectores y PONG.')


def retirar_bandera_y_arrancar(repl):
    instalacion._bandera(repl)
    repl.comando("os.remove('/maintenance.flag')")
    repl.serie.write(b'import machine; machine.reset()\r\n')
    inspeccion.observar_arranque(repl)


def recuperar_original(repl):
    originales, cambios, tamanos = instalacion._validar_local(BASE / 'firmware-congelado', BASE / 'firmware-anterior')
    for _ in range(2):
        try:
            repl = resincronizar(repl, permitir_crear_bandera=True)
            verificar_identidad(repl)
            original = TEMPORAL + '/original'
            listo = (repl.existe(TEMPORAL) and repl.existe(original)
                     and repl.existe(original + '/comunicacion'))
            if listo:
                remoto = instalacion._Remoto(repl)
                promovido = remoto.existe(instalacion.NUEVO) or any(
                    remoto.existe(original + '/' + nombre) for nombre in instalacion.ARCHIVOS[:-1])
                promocion.recuperar(remoto, cambios, original)
                if promovido:
                    instalacion._verificar_copias(repl, TEMPORAL, originales, ('resguardo',))
            instalacion._verificar_estado(repl, inspeccion.inventario_remoto,
                                         originales, cambios, tamanos, TEMPORAL, False)
            retirar_bandera_y_arrancar(repl)
            print('FIRMWARE_ORIGINAL_RECUPERADO', flush=True)
            return repl
        except BaseException:
            continue
    repl.cerrar()
    raise RuntimeError('La recuperación del firmware original no pudo verificarse.')


def recuperar_previo(repl):
    for _ in range(2):
        try:
            repl = resincronizar(repl, permitir_crear_bandera=True)
            verificar_identidad(repl)
            originales, cambios, tamanos = instalacion._validar_local(
                BASE / 'firmware-congelado', BASE / 'firmware-anterior')
            instalacion._verificar_estado(repl, inspeccion.inventario_remoto,
                                         originales, cambios, tamanos, TEMPORAL, False)
            retirar_bandera_y_arrancar(repl)
            return repl
        except BaseException:
            continue
    repl.cerrar()
    raise RuntimeError('El firmware previo no pudo reiniciarse con seguridad.')


def main():
    inspeccion.comprobar_exclusividad()
    ESTADO.update(sesion=None, bandera_propia=False)
    repl = None
    bandera_intentada = False
    interrupcion_intentada = False
    bandera_ajena = False
    promovido = False
    restaurado = False
    try:
        repl = abrir_sesion()
        interrupcion_intentada = True
        repl.serie.write(b'\x03')
        try:
            repl._leer_prompt(3.0)
        except TimeoutError:
            bandera_intentada = True
            solicitar_stop(repl)
        repl.preparar_escritura()
        if bandera_intentada:
            instalacion._bandera(repl)
        else:
            if repl.existe('/maintenance.flag'):
                bandera_ajena = True
                raise RuntimeError('Bandera de mantenimiento preexistente.')
            bandera_intentada = True
            ESTADO['bandera_propia'] = True
            repl.comando("f=open('/maintenance.flag','w'); f.write('1\\n'); f.close()")
        verificar_identidad(repl)
        promovido = True
        resultado = instalacion.instalar_stage3(
            repl=repl, candidato=BASE / 'firmware-congelado', respaldo=BASE / 'firmware-anterior',
            temporal=TEMPORAL, promocion=promocion, inventariar=inspeccion.inventario_remoto,
            resincronizar=resincronizar, verificar_arranque=verificar_arranque)
        repl = resultado['sesion']
        retirar_bandera_y_arrancar(repl)
        print('FIRMWARE_CANDIDATO_ACTIVO', flush=True)
        return True
    except instalacion.ErrorInstalacion as error:
        repl = ESTADO['sesion'] or error.sesion
        if error.recuperado is False:
            print('RECUPERACION_INCOMPLETA', flush=True)
            return False
        try:
            repl = recuperar_previo(repl)
            restaurado = True
        except Exception:
            print('RECUPERACION_INCOMPLETA', flush=True)
        print('INSTALACION_DETENIDA_ETAPA=' + error.etapa, flush=True)
        return False
    except BaseException as error:
        print('INSTALACION_DETENIDA_TIPO=' + type(error).__name__, flush=True)
        repl = ESTADO['sesion'] or repl
        if interrupcion_intentada and not bandera_ajena and repl is not None:
            try:
                if promovido:
                    repl = recuperar_original(repl)
                else:
                    repl = recuperar_previo(repl)
                restaurado = True
            except BaseException:
                print('RECUPERACION_INCOMPLETA', flush=True)
        return False
    finally:
        vigente = ESTADO['sesion']
        if vigente is not None:
            vigente.cerrar()
        if repl is not None and repl is not vigente:
            repl.cerrar()
        ESTADO.update(sesion=None, bandera_propia=False)
        if restaurado:
            print('FIRMWARE_ORIGINAL_REINICIADO', flush=True)


if __name__ == '__main__':
    try:
        raise SystemExit(0 if main() else 1)
    except Exception as error:
        print('INSTALACION_BLOQUEADA:', type(error).__name__, flush=True)
        raise SystemExit(1) from None
