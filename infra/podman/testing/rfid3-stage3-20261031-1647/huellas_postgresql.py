"""Calcula huellas agregadas sin exportar filas de negocio de PostgreSQL."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys


def consultar(contenedor, sentencia):
    proceso = subprocess.run(
        ['podman', 'exec', '-i', contenedor, 'sh', '-c',
         'exec psql -X -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
        input="SET TIME ZONE 'UTC'; SET datestyle TO 'ISO, MDY';\n" + sentencia,
        capture_output=True, text=True, check=False,
    )
    if proceso.returncode:
        raise RuntimeError('No se pudo calcular una huella agregada.')
    return proceso.stdout.strip()


def huellas(contenedor):
    nombres = consultar(contenedor,
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;").splitlines()
    if not nombres or any(not re.fullmatch(r'[a-z_][a-z0-9_]*', nombre) for nombre in nombres):
        raise RuntimeError('Inventario de tablas inesperado.')
    resultado = {}
    for nombre in nombres:
        expresion = "to_jsonb(t) - 'lectura_salida_id'" if nombre == 'movimiento_estacionamiento' else 'to_jsonb(t)'
        filtro = "WHERE version IS DISTINCT FROM '14'" if nombre == 'flyway_schema_history' else ''
        sentencia = ("SELECT count(*),encode(sha256(convert_to(coalesce(string_agg(h,'' ORDER BY h),''),"
                     "'UTF8')),'hex') FROM (SELECT encode(sha256(convert_to((" + expresion +
                     ")::text,'UTF8')),'hex') AS h FROM public.\"" + nombre + "\" t " + filtro + ") filas;")
        valor = consultar(contenedor, sentencia).split('|')
        if len(valor) != 2 or not valor[0].isdigit() or not re.fullmatch(r'[0-9a-f]{64}', valor[1]):
            raise RuntimeError('Resultado de huella inválido.')
        resultado[nombre] = {'filas': int(valor[0]), 'sha256': valor[1]}
    return resultado


def main():
    if len(sys.argv) != 3:
        raise SystemExit('Uso: huellas_postgresql.py CONTENEDOR DESTINO_NUEVO')
    destino = Path(sys.argv[2])
    resultado = huellas(sys.argv[1])
    descriptor = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as archivo:
        json.dump(resultado, archivo, sort_keys=True, indent=2)
        archivo.write('\n')
    print('Huellas agregadas guardadas: {} tablas'.format(len(resultado)))


if __name__ == '__main__':
    main()
