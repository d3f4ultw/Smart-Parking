#!/usr/bin/env bash
# Inicia un solo bridge y exige PONG, sin mostrar tramas ni credenciales.
set -euo pipefail
cd /mnt/new-volume/SmartParking
unidad='smartparking-rfid1-bridge.service'
iniciado=0
exito=0
al_salir() {
    if (( iniciado && ! exito )); then
        systemctl --user stop "$unidad" || true
        printf 'BRIDGE_NO_VERIFICADO: servicio detenido para mantener el fallo cerrado.\n' >&2
    fi
}
trap al_salir EXIT
test "$(systemctl --user show "$unidad" -p ActiveState --value)" = inactive
test "$(stat -c %a infra/rfid1-bridge/private/.env)" = 600
python3 - <<'PY'
import hashlib,json
from pathlib import Path
base=Path('infra/podman/testing/rfid3-stage3-20261031-1647/bridge-candidato')
manifiesto=json.loads((base/'sha256.json').read_text())
assert all(hashlib.sha256((Path('infra/rfid1-bridge')/n).read_bytes()).hexdigest()==h for n,h in manifiesto.items())
PY
inicio=$(date +%s)
iniciado=1
systemctl --user start "$unidad"
sleep 16
test "$(systemctl --user show "$unidad" -p ActiveState --value)" = active
test "$(systemctl --user show "$unidad" -p SubState --value)" = running
test "$(systemctl --user show "$unidad" -p UnitFileState --value)" = enabled
test "$(systemctl --user show "$unidad" -p NRestarts --value)" = 0
pid=$(systemctl --user show "$unidad" -p MainPID --value)
test "$pid" -gt 0
propietarios=$(fuser /dev/ttyACM0 2>/dev/null | xargs)
test "$propietarios" = "$pid"
propietarios=$(lsof -n -t /dev/ttyACM0 | sort -u | xargs)
test "$propietarios" = "$pid"
resumen=$(journalctl --user -u "$unidad" --since "@$inicio" --no-pager -o cat | awk '/USB: PONG/{p++} /reconect|desconect|error|fallo/{e++} /Lectura |entrada RFID2|salida RFID3/{l++} END {printf "%d %d %d",p,e,l}')
read -r pongs errores lecturas <<< "$resumen"
test "$pongs" -ge 5
test "$errores" = 0
test "$lecturas" = 0
printf 'BRIDGE_OK; PONG=%s; REINICIOS=0; PROPIETARIO_UNICO=%s\n' "$pongs" "$pid"
exito=1
