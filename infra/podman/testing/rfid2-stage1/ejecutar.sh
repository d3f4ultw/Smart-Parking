#!/usr/bin/env bash
set -euo pipefail
umask 077

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$raiz"
archivo_compose="infra/podman/testing/rfid2-stage1/compose.yaml"
proyecto="smartparking-rfid2-stage1-$(tr -d '-' < /proc/sys/kernel/random/uuid)"
export RFID2_STAGE1_PROJECT_NAME="$proyecto"
export RFID2_STAGE1_POSTGRES_DB=sp_rfid1_stage1_fresh
export RFID2_STAGE1_POSTGRES_USER=sp_rfid1_stage1
export RFID2_STAGE1_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export RFID2_STAGE1_TOKEN="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
export RFID2_STAGE1_TOKEN_SHA256="$(printf '%s' "$RFID2_STAGE1_TOKEN" | sha256sum | cut -d ' ' -f1)"
export SMARTPARKING_RFID1_TOKEN="$RFID2_STAGE1_TOKEN"
export RFID1_STAGE1_OWNER_EMAIL="rfid2-compat-$(tr -d '-' < /proc/sys/kernel/random/uuid)@example.invalid"
export RFID1_STAGE1_OWNER_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
export RFID1_STAGE1_ADMIN_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
imagen_api="localhost/${proyecto}-api:stage1"

limpiar() {
    cd "$raiz"
    podman compose --project-name "$proyecto" -f "$archivo_compose" \
        down --volumes --remove-orphans >/dev/null 2>&1 || true
    podman image rm "$imagen_api" >/dev/null 2>&1 || true
    unset RFID2_STAGE1_TOKEN RFID2_STAGE1_TOKEN_SHA256 RFID2_STAGE1_POSTGRES_PASSWORD
    unset SMARTPARKING_RFID1_TOKEN RFID1_STAGE1_OWNER_EMAIL RFID1_STAGE1_OWNER_PASSWORD
    unset RFID1_STAGE1_ADMIN_PASSWORD POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
    unset RFID2_STAGE1_PROJECT_NAME RFID2_STAGE1_POSTGRES_DB RFID2_STAGE1_POSTGRES_USER
    unset RFID2_STAGE1_API_URL RFID2_STAGE1_API_CONTAINER RFID2_STAGE1_DB_CONTAINER
}
trap limpiar EXIT INT TERM

echo "Empaquetando la API candidata con Maven offline y JDK 27."
pushd services/api >/dev/null
mvn --offline --batch-mode --no-transfer-progress -DskipTests package
popd >/dev/null

podman compose --project-name "$proyecto" -f "$archivo_compose" config --quiet
podman compose --project-name "$proyecto" -f "$archivo_compose" up --build -d

id_api="$(podman compose --project-name "$proyecto" -f "$archivo_compose" ps -q api)"
id_db="$(podman compose --project-name "$proyecto" -f "$archivo_compose" ps -q db)"
puerto_api="$(podman port "$id_api" 8080/tcp | sed 's/.*://')"
puerto_db="$(podman port "$id_db" 5432/tcp | sed 's/.*://')"
export RFID2_STAGE1_API_URL="http://127.0.0.1:${puerto_api}"
export RFID2_STAGE1_API_CONTAINER="$id_api"
export RFID2_STAGE1_DB_CONTAINER="$id_db"
export RFID2_STAGE1_POSTGRES_DB RFID2_STAGE1_POSTGRES_USER
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$puerto_db"
export POSTGRES_DB="$RFID2_STAGE1_POSTGRES_DB" POSTGRES_USER="$RFID2_STAGE1_POSTGRES_USER"
export POSTGRES_PASSWORD="$RFID2_STAGE1_POSTGRES_PASSWORD"

salud=0
for intento in $(seq 1 60); do
    codigo="$(curl --max-time 1 -sS -o /dev/null -w '%{http_code}' \
        "$RFID2_STAGE1_API_URL/actuator/health" 2>/dev/null || true)"
    if [[ "$codigo" == "200" ]]; then
        salud=1
        break
    fi
    estado="$(podman inspect --format '{{.State.Status}}' "$id_api")"
    if [[ "$estado" != "running" ]]; then
        echo "La API aislada se detuvo; diagnóstico reciente:" >&2
        podman logs --tail 120 "$id_api" >&2 || true
        exit 1
    fi
    sleep 1
done
[[ "$salud" == "1" ]] || { echo "La API aislada no alcanzó estado saludable." >&2; exit 1; }

export SPRING_PROFILE=test SPRING_APPLICATION_NAME=smartparking-rfid2-rfid1-compatibilidad
export API_BIND_ADDRESS=127.0.0.1 API_PORT=0 SESSION_TIMEOUT=30m SESSION_COOKIE_SECURE=false
export SMTP_ENABLED=false
pushd services/api >/dev/null
mvn --offline --batch-mode --no-transfer-progress \
    -Dsmartparking.integration.disposable=true \
    -Dtest=CapturasRfid1ApiAceptacionTest test
popd >/dev/null

PYTHONDONTWRITEBYTECODE=1 python3 -B infra/podman/testing/rfid2-stage1/aceptacion.py
pushd infra/rfid1-bridge >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests
popd >/dev/null

echo "Stage 1 aislado concluyó; el trap elimina solo el proyecto temporal RFID2."
