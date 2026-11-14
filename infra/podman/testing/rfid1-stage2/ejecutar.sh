#!/usr/bin/env bash
set -euo pipefail
umask 077

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$raiz"
compose_file="infra/podman/testing/rfid1-stage2/compose.yaml"
proyecto="smartparking-rfid1-stage2-$(tr -d '-' < /proc/sys/kernel/random/uuid)"
export RFID1_STAGE2_PROJECT_NAME="$proyecto"
export RFID1_STAGE2_POSTGRES_DB=smartparking_test_rfid1_stage2
export RFID1_STAGE2_POSTGRES_USER=smartparking_test_rfid1
export RFID1_STAGE2_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export RFID1_STAGE2_TOKEN_SHA256
export SMARTPARKING_RFID1_TOKEN="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
RFID1_STAGE2_TOKEN_SHA256="$(printf '%s' "$SMARTPARKING_RFID1_TOKEN" | sha256sum | cut -d ' ' -f1)"
export RFID1_STAGE2_OWNER_EMAIL="rfid-stage2-$(tr -d '-' < /proc/sys/kernel/random/uuid)@example.invalid"
export RFID1_STAGE2_OWNER_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
export RFID1_STAGE2_ADMIN_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"

limpiar() {
    cd "$raiz"
    podman compose --project-name "$proyecto" -f "$compose_file" down --volumes --remove-orphans >/dev/null 2>&1 || true
    podman image rm "localhost/${proyecto}-api:stage2" >/dev/null 2>&1 || true
    unset SMARTPARKING_RFID1_TOKEN RFID1_STAGE2_TOKEN_SHA256
    unset RFID1_STAGE2_POSTGRES_PASSWORD RFID1_STAGE2_OWNER_PASSWORD RFID1_STAGE2_ADMIN_PASSWORD
    unset RFID1_STAGE2_OWNER_EMAIL RFID1_STAGE2_PROJECT_NAME
    unset RFID1_STAGE2_POSTGRES_DB RFID1_STAGE2_POSTGRES_USER
    unset RFID1_STAGE2_API_URL RFID1_STAGE2_API_CONTAINER RFID1_STAGE2_DB_CONTAINER
    unset RFID1_STAGE2_DB_JDBC_URL RFID1_STAGE2_DB_USER RFID1_STAGE2_DB_PASSWORD
    unset POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
    unset SPRING_PROFILE SPRING_APPLICATION_NAME API_BIND_ADDRESS API_PORT
    unset SESSION_TIMEOUT SESSION_COOKIE_SECURE SMTP_ENABLED
}
trap limpiar EXIT INT TERM

echo "Empaquetando la API con Maven offline y JDK 27."
pushd services/api >/dev/null
mvn --offline --batch-mode --no-transfer-progress -DskipTests package
popd >/dev/null

podman compose --project-name "$proyecto" -f "$compose_file" config --quiet
podman compose --project-name "$proyecto" -f "$compose_file" up --build -d

api_container="$(podman compose --project-name "$proyecto" -f "$compose_file" ps -q api)"
db_container="$(podman compose --project-name "$proyecto" -f "$compose_file" ps -q db)"
api_port="$(podman port "$api_container" 8080/tcp | sed 's/.*://')"
db_port="$(podman port "$db_container" 5432/tcp | sed 's/.*://')"
export RFID1_STAGE2_API_URL="http://127.0.0.1:${api_port}"
export RFID1_STAGE2_API_CONTAINER="$api_container"
export RFID1_STAGE2_DB_CONTAINER="$db_container"
export RFID1_STAGE2_DB_JDBC_URL="jdbc:postgresql://127.0.0.1:${db_port}/${RFID1_STAGE2_POSTGRES_DB}"
export RFID1_STAGE2_DB_USER="$RFID1_STAGE2_POSTGRES_USER"
export RFID1_STAGE2_DB_PASSWORD="$RFID1_STAGE2_POSTGRES_PASSWORD"
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT="$db_port"
export POSTGRES_DB="$RFID1_STAGE2_POSTGRES_DB"
export POSTGRES_USER="$RFID1_STAGE2_POSTGRES_USER"
export POSTGRES_PASSWORD="$RFID1_STAGE2_POSTGRES_PASSWORD"

salud=0
for intento in $(seq 1 60); do
    estado="$(curl --max-time 1 -sS -o /dev/null -w '%{http_code}' "$RFID1_STAGE2_API_URL/actuator/health" 2>/dev/null || true)"
    if [[ "$estado" == "200" ]]; then
        salud=1
        break
    fi
    estado_contenedor="$(podman inspect --format '{{.State.Status}}' "$api_container")"
    if [[ "$estado_contenedor" != "running" ]]; then
        echo "La API desechable se detuvo antes de alcanzar estado saludable." >&2
        exit 1
    fi
    sleep 1
done
if [[ "$salud" != "1" ]]; then
    echo "La API desechable no alcanzó estado saludable." >&2
    exit 1
fi

PYTHONDONTWRITEBYTECODE=1 python3 -B infra/podman/testing/rfid1-stage2/aceptacion_api.py

test_clase="${RFID1_STAGE2_MAVEN_TEST:-CapturasRfid1ApiAceptacionTest}"
export SPRING_PROFILE=test
export SPRING_APPLICATION_NAME=smartparking-api-rfid1-stage2-test
export API_BIND_ADDRESS=127.0.0.1
export API_PORT=0
export SESSION_TIMEOUT=30m
export SESSION_COOKIE_SECURE=false
export SMTP_ENABLED=false
pushd services/api >/dev/null
mvn --offline --batch-mode --no-transfer-progress -Dsmartparking.integration.disposable=true "-Dtest=${test_clase}" test
popd >/dev/null

verificar_contenedor() {
    local nombre="$1"
    local id_esperado="$2"
    local id_actual
    id_actual="$(podman inspect --format '{{.Id}}' "$nombre")"
    [[ "$id_actual" == "$id_esperado"* ]]
}

verificar_contenedor smartparking-mailpit-1 65927aa83490
verificar_contenedor smartparking-db-1 c537acad534d
verificar_contenedor smartparking-stripe-cli-1 ad279e1fc7a0
verificar_contenedor smartparking-api-1 96afab821540
verificar_contenedor smartparking-web-1 4a2e4c5b1cc2
podman volume inspect smartparking_postgres_datos >/dev/null
podman network inspect smartparking_red_privada >/dev/null
echo "Los cinco contenedores, el volumen PostgreSQL y la red persistentes conservan sus identidades."
