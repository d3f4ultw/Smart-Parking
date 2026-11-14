"""Comprueba entrada y replay de la imagen previa solo en la copia V14."""

import secrets
import sys
import uuid

import probar_copia_restaurada as aislada


def main():
    aislada.verificar_aislamiento('79ad4890e16b75a21e3bf3a35f9eef444c99f66a92ea05326ff075cd687bada2')
    sys.path.insert(0, str(aislada.RAIZ / 'infra/podman/testing/rfid3-stage1'))
    import aceptacion as a
    secuencias = aislada.secuencias(a)
    etiqueta = 'ST3' + secrets.token_hex(16)
    if a.sql("SELECT count(*) FROM empleado WHERE nombres='" + etiqueta + "';") != '0':
        raise RuntimeError('Colisión del marcador sintético.')
    try:
        aislada.crear_fixtures(a, etiqueta, cantidad=1)
        lectura = str(uuid.uuid4())
        if not a.autorizada(a.entrada(a.UIDS[0], lectura)):
            raise RuntimeError('La entrada sintética no fue autorizada.')
        if not a.autorizada(a.entrada(a.UIDS[0], lectura)):
            raise RuntimeError('El replay sintético no fue autorizado.')
        if a.sql("SELECT count(*) FROM movimiento_estacionamiento WHERE lectura_id='" + lectura + "';") != '1':
            raise RuntimeError('El replay alteró el número de movimientos.')
        print('API anterior sobre V14: entrada sintética y replay conservan un solo movimiento.')
    finally:
        aislada.limpiar(a, etiqueta, secuencias)
        print('Fixture sintético retirado y trigger verificado.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('PRUEBA_API_ANTERIOR_BLOQUEADA:', type(error).__name__)
        raise SystemExit(1) from None
