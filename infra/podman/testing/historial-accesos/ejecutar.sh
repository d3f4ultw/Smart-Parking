#!/usr/bin/env bash
set -euo pipefail
umask 077

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$raiz"
archivo_compose="infra/podman/testing/historial-accesos/compose.yaml"
proyecto="smartparking-historial-accesos-$(tr -d '-' < /proc/sys/kernel/random/uuid)"
export HISTORIAL_ACCESOS_PROJECT_NAME="$proyecto"
export HISTORIAL_ACCESOS_POSTGRES_DB=sp_accesos_mvp_fresh
export HISTORIAL_ACCESOS_POSTGRES_USER=sp_accesos_mvp
export HISTORIAL_ACCESOS_POSTGRES_PASSWORD="$(openssl rand -hex 32)"
selector_pruebas="${1:-HistorialAccesosAceptacionHttpTest}"

limpiar() {
    cd "$raiz"
    podman compose --project-name "$proyecto" -f "$archivo_compose" \
        down --volumes --remove-orphans >/dev/null 2>&1 || true
    unset HISTORIAL_ACCESOS_PROJECT_NAME HISTORIAL_ACCESOS_POSTGRES_DB
    unset HISTORIAL_ACCESOS_POSTGRES_USER HISTORIAL_ACCESOS_POSTGRES_PASSWORD
    unset POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
    unset SMARTPARKING_POSTGRES_DESCARTABLE
}
trap limpiar EXIT INT TERM

podman compose --project-name "$proyecto" -f "$archivo_compose" config --quiet
podman compose --project-name "$proyecto" -f "$archivo_compose" up -d db
id_db="$(podman compose --project-name "$proyecto" -f "$archivo_compose" ps -q db)"
puerto_db="$(podman port "$id_db" 5432/tcp | sed -E 's/.*:([0-9]+)$/\1/')"
[[ "$puerto_db" =~ ^[0-9]{1,5}$ ]] || {
    echo "PostgreSQL no publicó un puerto loopback temporal válido." >&2
    exit 1
}

salud=0
for intento in $(seq 1 60); do
    if podman exec "$id_db" pg_isready -p 5432 \
        -U "$HISTORIAL_ACCESOS_POSTGRES_USER" \
        -d "$HISTORIAL_ACCESOS_POSTGRES_DB" >/dev/null 2>&1; then
        salud=1
        break
    fi
    estado="$(podman inspect --format '{{.State.Status}}' "$id_db")"
    if [[ "$estado" != "running" ]]; then
        echo "PostgreSQL temporal se detuvo antes de estar listo." >&2
        exit 1
    fi
    sleep 1
done
[[ "$salud" == "1" ]] || {
    echo "PostgreSQL 18.6 temporal no alcanzó estado saludable." >&2
    exit 1
}

export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$puerto_db"
export POSTGRES_DB="$HISTORIAL_ACCESOS_POSTGRES_DB"
export POSTGRES_USER="$HISTORIAL_ACCESOS_POSTGRES_USER"
export POSTGRES_PASSWORD="$HISTORIAL_ACCESOS_POSTGRES_PASSWORD"
export SMARTPARKING_POSTGRES_DESCARTABLE=true
export SPRING_PROFILE=test SPRING_APPLICATION_NAME=smartparking-historial-accesos-aceptacion
export API_BIND_ADDRESS=127.0.0.1 API_PORT=0 SESSION_TIMEOUT=30m SESSION_COOKIE_SECURE=false
export SMTP_ENABLED=false

pushd services/api >/dev/null
mvn --offline --batch-mode --no-transfer-progress \
    -Dmaven.repo.local=/tmp/smartparking-m2 \
    -DargLine=-javaagent:/tmp/smartparking-m2/org/mockito/mockito-core/5.23.0/mockito-core-5.23.0.jar \
    -Dsmartparking.integration.disposable=true \
    "-Dtest=$selector_pruebas" test
popd >/dev/null

versiones="$(podman exec "$id_db" psql -X -qAt -v ON_ERROR_STOP=1 \
    -U "$HISTORIAL_ACCESOS_POSTGRES_USER" \
    -d "$HISTORIAL_ACCESOS_POSTGRES_DB" \
    -c "SELECT count(*) FROM flyway_schema_history WHERE success")"
[[ "$versiones" == "21" ]] || {
    echo "Se esperaban V1–V21 exitosas en la base temporal; se encontraron $versiones." >&2
    exit 1
}
echo "Aceptación HTTP terminada con PostgreSQL 18.6 y Flyway V1–V21; solo se eliminará el proyecto temporal $proyecto."
