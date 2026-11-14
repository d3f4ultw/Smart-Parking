#!/usr/bin/env python3
import json
import subprocess
import sys
import time

PROJECT = 'smartparking-vision-c1-pressure-20261103-095735'


def main() -> int:
    caso = sys.argv[1] if len(sys.argv) > 1 else 'sin-caso'
    limite = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    nombre = PROJECT + '-api-1'
    inicio = time.monotonic()
    señal = subprocess.run(
        ['podman', 'kill', '--signal', 'SIGTERM', nombre],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if señal.returncode != 0:
        print(json.dumps({'caso': caso, 'senalSIGTERM': False, 'exitPodman': señal.returncode}))
        return 1
    while time.monotonic() - inicio < limite:
        inspeccion = subprocess.run(
            ['podman', 'inspect', '--format', '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}', nombre],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        estado = inspeccion.stdout.strip().split()
        if inspeccion.returncode == 0 and estado and estado[0] in {'exited', 'stopped'}:
            codigo = int(estado[1]) if len(estado) > 1 and estado[1].isdigit() else None
            oom = estado[2].lower() == 'true' if len(estado) > 2 else None
            print(json.dumps({
                'caso': caso,
                'senalSIGTERM': True,
                'tiempoMs': round((time.monotonic() - inicio) * 1000),
                'estado': estado[0],
                'exitCode': codigo,
                'oomKilled': oom,
                'forzado': False,
            }))
            return 0
        time.sleep(0.1)
    print(json.dumps({
        'caso': caso,
        'senalSIGTERM': True,
        'timeoutMs': round(limite * 1000),
        'estado': 'sin-confirmar-salida',
        'forzado': False,
    }))
    return 124


if __name__ == '__main__':
    raise SystemExit(main())
