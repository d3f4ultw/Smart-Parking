#!/usr/bin/env python3
import re
import subprocess
import sys

PROJECT = 'smartparking-vision-c1-pressure-20261103-095735'


def main() -> int:
    fase = sys.argv[1] if len(sys.argv) > 1 else 'sin-fase'
    listado = subprocess.run(
        ['podman', 'ps', '--filter', 'label=com.smartparking.testing.run=' + PROJECT, '--format', '{{.Names}}'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if listado.returncode != 0:
        print('podman ps fallo; no se imprimen detalles de otros recursos')
        return listado.returncode
    nombres = [
        nombre for nombre in listado.stdout.splitlines()
        if re.fullmatch(re.escape(PROJECT) + r'-[a-zA-Z0-9_-]+', nombre)
    ]
    if not nombres:
        print(f'{fase}: sin contenedores QA activos')
        return 0
    comando = [
        'podman', 'stats', '--no-stream',
        '--format', '{{.Name}} CPU={{.CPUPerc}} RAM={{.MemUsage}} MEM={{.MemPerc}}',
        *nombres,
    ]
    print('fase=' + fase)
    resultado = subprocess.run(comando, check=False)
    return resultado.returncode


if __name__ == '__main__':
    raise SystemExit(main())
