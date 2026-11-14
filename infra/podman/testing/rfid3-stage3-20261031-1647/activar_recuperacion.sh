#!/usr/bin/env bash
# Restablece el puente previo, que no procesa RFID3, y exige señales sanitizadas.
set -euo pipefail
cd /mnt/new-volume/SmartParking
recuperacion='/mnt/new-volume/SmartParking/infra/rfid1-bridge/recuperacion-rfid3-stage3-20261031-1647'
unidad='smartparking-rfid1-bridge.service'
habilitada=0
verificada=0
al_salir() {
    if (( habilitada && ! verificada )); then
        systemctl --user stop "$unidad" || true
        systemctl --user disable "$unidad" || true
        printf 'RECUPERACION_NO_VERIFICADA: puente detenido y deshabilitado.\n' >&2
    fi
}
trap al_salir EXIT
python3 - "$recuperacion" <<'PY'
import hashlib, json, sys
from pathlib import Path
base = Path(sys.argv[1])
huellas = json.loads((base / 'sha256.json').read_text())
assert len(huellas) == 8
assert all(hashlib.sha256((base / nombre).read_bytes()).hexdigest() == valor
           for nombre, valor in huellas.items())
PY
test "$(stat -c %a infra/rfid1-bridge/private/.env)" = 600
test "$(curl --max-time 3 -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/actuator/health)" = 200
if fuser -s /dev/ttyACM0 2>/dev/null; then exit 1; fi
systemctl --user enable "$recuperacion/$unidad"
habilitada=1
systemctl --user daemon-reload
fragmento=$(systemctl --user show "$unidad" -p FragmentPath --value)
test "$(readlink -f "$fragmento")" = "$recuperacion/$unidad"
test -z "$(systemctl --user show "$unidad" -p DropInPaths --value)"
inicio=$(date +%s)
systemctl --user start "$unidad"
sleep 20
test "$(systemctl --user show "$unidad" -p ActiveState --value)" = active
test "$(systemctl --user show "$unidad" -p SubState --value)" = running
test "$(systemctl --user is-enabled "$unidad")" = enabled
test "$(systemctl --user show "$unidad" -p NRestarts --value)" = 0
pid=$(systemctl --user show "$unidad" -p MainPID --value)
test "$pid" -gt 0
python3 - "$pid" "$recuperacion/bridge.py" <<'PY'
from pathlib import Path
import sys
argumentos = (Path('/proc') / sys.argv[1] / 'cmdline').read_bytes().split(b'\0')
assert sys.argv[2].encode() in argumentos
PY
test "$(fuser /dev/ttyACM0 2>/dev/null | xargs)" = "$pid"
test "$(lsof -n -t /dev/ttyACM0 | sort -u | xargs)" = "$pid"
resumen=$(journalctl --user -u "$unidad" --since "@$inicio" --no-pager -o cat | awk '/USB: PONG/{p++} /reconect|desconect|error|fallo/{e++} /Lectura |entrada RFID2|salida RFID3/{l++} END {printf "%d %d %d",p,e,l}')
read -r pongs errores lecturas <<< "$resumen"
test "$pongs" -ge 5
test "$errores" = 0
test "$lecturas" = 0
verificada=1
printf 'RECUPERACION_OK; PONG=%s; REINICIOS=0; PROPIETARIO_UNICO=%s; RFID3_NO_PROCESADO\n' "$pongs" "$pid"
