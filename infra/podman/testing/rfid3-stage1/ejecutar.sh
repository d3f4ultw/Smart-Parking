#!/usr/bin/env bash
set -euo pipefail
umask 077

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$raiz"
archivo_compose="infra/podman/testing/rfid3-stage1/compose.yaml"
proyecto="smartparking-rfid3-stage1-$(tr -d '-' < /proc/sys/kernel/random/uuid)"
export RFID3_STAGE1_PROJECT_NAME="$proyecto"
export RFID3_STAGE1_POSTGRES_DB=rfid3_prueba
export RFID3_STAGE1_POSTGRES_USER=rfid3_prueba
export RFID3_STAGE1_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export RFID3_STAGE1_TOKEN="$(openssl rand -hex 32)"
export RFID3_STAGE1_TOKEN_SHA256="$(printf '%s' "$RFID3_STAGE1_TOKEN" | sha256sum | cut -d ' ' -f1)"
imagen_api="localhost/${proyecto}-api:stage1"

limpiar() {
    cd "$raiz"
    podman compose --project-name "$proyecto" -f "$archivo_compose" \
        down --volumes --remove-orphans >/dev/null 2>&1 || true
    podman image rm "$imagen_api" >/dev/null 2>&1 || true
}
trap limpiar EXIT INT TERM

echo 'Empaquetando la API candidata con JDK 27 y Maven offline.'
(cd services/api && mvn --offline --batch-mode --no-transfer-progress \
    -Daether.syncContext.named.factory=rwlock-local -DskipTests package)
podman compose --project-name "$proyecto" -f "$archivo_compose" config --quiet
podman compose --project-name "$proyecto" -f "$archivo_compose" up --build -d
export RFID3_STAGE1_API_CONTAINER="$(podman compose --project-name "$proyecto" -f "$archivo_compose" ps -q api)"
export RFID3_STAGE1_DB_CONTAINER="$(podman compose --project-name "$proyecto" -f "$archivo_compose" ps -q db)"
puerto_api="$(podman port "$RFID3_STAGE1_API_CONTAINER" 8080/tcp | sed 's/.*://')"
export RFID3_STAGE1_API_URL="http://127.0.0.1:${puerto_api}"
for intento in $(seq 1 60); do
    codigo="$(curl --max-time 1 -sS -o /dev/null -w '%{http_code}' \
        "$RFID3_STAGE1_API_URL/actuator/health" 2>/dev/null || true)"
    [[ "$codigo" == 200 ]] && break
    if [[ "$(podman inspect --format '{{.State.Status}}' "$RFID3_STAGE1_API_CONTAINER")" != running ]]; then
        echo 'La API desechable terminó antes de estar saludable.' >&2
        exit 1
    fi
    sleep 1
done
[[ "$codigo" == 200 ]] || { echo 'La API desechable no alcanzó estado saludable.' >&2; exit 1; }
PYTHONDONTWRITEBYTECODE=1 python3 -B infra/podman/testing/rfid3-stage1/aceptacion.py
echo 'Aceptación aislada terminada; se eliminarán solo los recursos propios de esta ejecución.'
