#!/usr/bin/env bash
set -euo pipefail
umask 077

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$raiz"
compose_file="infra/podman/testing/tarjetas-rfid-stage1/compose.yaml"
proyecto="smartparking-rfid1-stage1-$(tr -d '-' < /proc/sys/kernel/random/uuid)"
run_id="$(tr -d '-' < /proc/sys/kernel/random/uuid)"
private_dir="infra/podman/testing/tarjetas-rfid-stage1/.private-$run_id"
dump_file="$private_dir/v11-restoration.dump"

export RFID1_STAGE1_PROJECT_NAME="$proyecto"
export RFID1_STAGE1_POSTGRES_DB="sp_rfid1_stage1_fresh"
export RFID1_STAGE1_POSTGRES_USER="sp_rfid1_stage1"
export RFID1_STAGE1_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export RFID1_STAGE1_RESTORE_DB="sp_rfid1_stage1_v11"
export RFID1_STAGE1_RESTORE_USER="sp_rfid1_restore"
export RFID1_STAGE1_RESTORE_PASSWORD="$(openssl rand -hex 24)"
export SMARTPARKING_RFID1_TOKEN="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
export RFID1_STAGE1_TOKEN_SHA256
RFID1_STAGE1_TOKEN_SHA256="$(printf '%s' "$SMARTPARKING_RFID1_TOKEN" | sha256sum | cut -d ' ' -f1)"
export RFID1_STAGE1_OWNER_EMAIL="rfid1-stage1-$run_id@example.invalid"
export RFID1_STAGE1_OWNER_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
export RFID1_STAGE1_ADMIN_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"

limpiar() {
    cd "$raiz"
    podman compose --project-name "$proyecto" -f "$compose_file" down --volumes --remove-orphans >/dev/null 2>&1 || true
    podman image rm "localhost/$proyecto-api:stage1" >/dev/null 2>&1 || true
    python3 - "$private_dir" <<'PY'
from pathlib import Path
import shutil
import sys

ruta = Path(sys.argv[1])
if ruta.parent != Path("infra/podman/testing/tarjetas-rfid-stage1") or not ruta.name.startswith(".private-"):
    raise SystemExit("Ruta temporal inesperada; no se eliminó.")
if ruta.exists():
    shutil.rmtree(ruta)
PY
    unset SMARTPARKING_RFID1_TOKEN RFID1_STAGE1_TOKEN_SHA256
    unset RFID1_STAGE1_POSTGRES_PASSWORD RFID1_STAGE1_RESTORE_PASSWORD
    unset RFID1_STAGE1_OWNER_PASSWORD RFID1_STAGE1_ADMIN_PASSWORD
    unset RFID1_STAGE1_OWNER_EMAIL RFID1_STAGE1_PROJECT_NAME
    unset RFID1_STAGE1_POSTGRES_DB RFID1_STAGE1_POSTGRES_USER
    unset RFID1_STAGE1_RESTORE_DB RFID1_STAGE1_RESTORE_USER
    unset POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
    unset API_BIND_ADDRESS API_PORT SPRING_PROFILE SPRING_APPLICATION_NAME
    unset SESSION_TIMEOUT SESSION_COOKIE_SECURE SMTP_ENABLED
    unset RFID1_STAGE1_API_URL RFID1_STAGE1_DB_JDBC_URL RFID1_STAGE1_DB_USER RFID1_STAGE1_DB_PASSWORD
}
trap limpiar EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

estado_persistente() {
    local nombre
    for nombre in smartparking-db-1 smartparking-api-1 smartparking-web-1 smartparking-mailpit-1 smartparking-stripe-cli-1; do
        podman inspect --format '{{.Name}}={{.Id}}:{{.State.Status}}' "$nombre"
    done
    podman volume inspect --format '{{.Name}}={{.Mountpoint}}' smartparking_postgres_datos
    podman network inspect --format '{{.Name}}={{.Id}}' smartparking_red_privada
    podman network inspect --format '{{.Name}}={{.Id}}' smartparking_api_web_privada
}

esperar_salud_api() {
    local puerto="$1"
    local estado
    for intento in $(seq 1 60); do
        estado="$(curl --max-time 1 -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$puerto/actuator/health" 2>/dev/null || true)"
        if [[ "$estado" == "200" ]]; then
            return 0
        fi
        sleep 1
    done
    return 1
}

diagnosticar_api() {
    local contenedor="$1"
    local puerto="$2"
    local base="$3"
    local usuario="$4"
    local base_datos="$5"
    local codigo estado versiones causas
    codigo="$(curl --max-time 2 -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$puerto/actuator/health" 2>/dev/null || true)"
    estado="$(podman inspect --format '{{.State.Status}}:{{.State.ExitCode}}' "$contenedor" 2>/dev/null || printf 'desconocido')"
    versiones="$(podman exec "$base" psql -X -qAt -U "$usuario" -d "$base_datos" \
        -c "SELECT string_agg(version, ',' ORDER BY installed_rank) FROM flyway_schema_history WHERE success" 2>/dev/null || printf 'sin_historial')"
    causas="$(podman logs "$contenedor" 2>&1 | python3 -c '
import re
import sys

causas = []
for linea in sys.stdin:
    if "APPLICATION FAILED TO START" in linea:
        causas.append("APPLICATION_FAILED_TO_START")
    metodo = re.search(r"NoSuchMethodException:\s*([\w.$]+)", linea)
    if metodo:
        causas.append("NoSuchMethodException:" + metodo.group(1))
    coincidencia = re.search(r"Caused by:\s*([\w.$]*(?:Exception|Error))", linea)
    if coincidencia:
        causas.append(coincidencia.group(1).rsplit(".", 1)[-1])
print(",".join(causas[-3:]) or "sin_excepcion_en_logs")
')"
    printf 'ERROR: health_api=%s estado_api=%s flyway=%s causas=%s\n' "$codigo" "$estado" "$versiones" "$causas"
}

salida_persistente_inicial="$(estado_persistente)"

printf '%s\n' "Empaquetando API candidata con Maven offline y JDK 27."
pushd services/api >/dev/null
mvn --offline --batch-mode --no-transfer-progress -DskipTests package
popd >/dev/null

mkdir -m 700 "$private_dir"
chmod 700 "$private_dir"
printf '%s\n' "Capturando V11 por pg_dump de solo lectura en almacenamiento privado."
podman exec smartparking-db-1 sh -c 'pg_dump --format=custom --no-owner --no-privileges --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' > "$dump_file"
chmod 600 "$dump_file"
test -s "$dump_file"
pg_restore --list "$dump_file" >/dev/null

podman compose --project-name "$proyecto" -f "$compose_file" config --quiet
podman compose --project-name "$proyecto" -f "$compose_file" build api_fresh
podman compose --project-name "$proyecto" -f "$compose_file" up -d db_fresh db_restored

db_fresh="$(podman compose --project-name "$proyecto" -f "$compose_file" ps -q db_fresh)"
db_restored="$(podman compose --project-name "$proyecto" -f "$compose_file" ps -q db_restored)"
for db_id in "$db_fresh" "$db_restored"; do
    saludable=0
    for intento in $(seq 1 60); do
        salud_db="$(podman inspect --format '{{.State.Health.Status}}' "$db_id")"
        if [[ "$salud_db" == "healthy" ]]; then
            saludable=1
            break
        fi
        sleep 1
    done
    [[ "$saludable" == "1" ]]
done

printf '%s\n' "Restaurando el snapshot V11 únicamente en PostgreSQL 18.6 desechable."
podman exec -i "$db_restored" pg_restore --exit-on-error --no-owner --no-privileges \
    --username="$RFID1_STAGE1_RESTORE_USER" --dbname="$RFID1_STAGE1_RESTORE_DB" < "$dump_file" >/dev/null
python3 - "$dump_file" <<'PY'
from pathlib import Path
import sys

ruta = Path(sys.argv[1])
if ruta.parent.parent != Path("infra/podman/testing/tarjetas-rfid-stage1") or ruta.name != "v11-restoration.dump":
    raise SystemExit("Ruta del dump inesperada; no se eliminó.")
ruta.unlink(missing_ok=True)
PY

versiones_v11="$(podman exec "$db_restored" psql -X -qAt -U "$RFID1_STAGE1_RESTORE_USER" -d "$RFID1_STAGE1_RESTORE_DB" \
    -c "SELECT string_agg(version, ',' ORDER BY installed_rank) FROM flyway_schema_history WHERE success")"
[[ "$versiones_v11" == "1,2,3,4,5,6,7,8,9,10,11" ]]
empleados_asociados_antes="$(podman exec "$db_restored" psql -X -qAt -U "$RFID1_STAGE1_RESTORE_USER" -d "$RFID1_STAGE1_RESTORE_DB" \
    -c "SELECT count(*)::text FROM asociacion_tarjeta_rfid1 WHERE empleado_id IS NOT NULL")"
[[ "$empleados_asociados_antes" -gt 0 ]]
firma_asociaciones_antes="$(podman exec "$db_restored" psql -X -qAt -U "$RFID1_STAGE1_RESTORE_USER" -d "$RFID1_STAGE1_RESTORE_DB" \
    -c "SELECT count(*)::text || '|' || COALESCE(md5(string_agg(uid_canonico || '|' || COALESCE(cliente_id::text, '') || '|' || COALESCE(empleado_id::text, '') || '|' || extract(epoch FROM asociada_en)::text, E'\\n' ORDER BY asociacion_id)), '') FROM asociacion_tarjeta_rfid1")"

podman compose --project-name "$proyecto" -f "$compose_file" up -d api_restored
api_restaurada="$(podman compose --project-name "$proyecto" -f "$compose_file" ps -q api_restored)"
puerto_api_restaurada="$(podman port "$api_restaurada" 8080/tcp | awk -F: '{print $NF}')"
if ! esperar_salud_api "$puerto_api_restaurada"; then
    diagnosticar_api "$api_restaurada" "$puerto_api_restaurada" "$db_restored" \
        "$RFID1_STAGE1_RESTORE_USER" "$RFID1_STAGE1_RESTORE_DB"
    exit 1
fi
versiones_restauradas="$(podman exec "$db_restored" psql -X -qAt -U "$RFID1_STAGE1_RESTORE_USER" -d "$RFID1_STAGE1_RESTORE_DB" \
    -c "SELECT string_agg(version, ',' ORDER BY installed_rank) FROM flyway_schema_history WHERE success")"
[[ "$versiones_restauradas" == "1,2,3,4,5,6,7,8,9,10,11,12" ]]
firma_asociaciones_despues="$(podman exec "$db_restored" psql -X -qAt -U "$RFID1_STAGE1_RESTORE_USER" -d "$RFID1_STAGE1_RESTORE_DB" \
    -c "SELECT count(*)::text || '|' || COALESCE(md5(string_agg(uid_canonico || '|' || COALESCE(cliente_id::text, '') || '|' || COALESCE(empleado_id::text, '') || '|' || extract(epoch FROM asociada_en)::text, E'\\n' ORDER BY asociacion_id)), '') FROM asociacion_tarjeta_rfid1")"
empleados_asociados_despues="$(podman exec "$db_restored" psql -X -qAt -U "$RFID1_STAGE1_RESTORE_USER" -d "$RFID1_STAGE1_RESTORE_DB" \
    -c "SELECT count(*)::text FROM asociacion_tarjeta_rfid1 WHERE empleado_id IS NOT NULL")"
[[ "$firma_asociaciones_antes" == "$firma_asociaciones_despues" ]]
[[ "$empleados_asociados_antes" == "$empleados_asociados_despues" ]]
printf '%s\n' "PASS: V12 aplicada sobre snapshot V11 y asociaciones históricas preservadas."
podman compose --project-name "$proyecto" -f "$compose_file" stop api_restored >/dev/null

db_port="$(podman port "$db_fresh" 5432/tcp | awk -F: '{print $NF}')"
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT="$db_port"
export POSTGRES_DB="$RFID1_STAGE1_POSTGRES_DB"
export POSTGRES_USER="$RFID1_STAGE1_POSTGRES_USER"
export POSTGRES_PASSWORD="$RFID1_STAGE1_POSTGRES_PASSWORD"
export RFID1_STAGE1_DB_JDBC_URL="jdbc:postgresql://127.0.0.1:$db_port/$RFID1_STAGE1_POSTGRES_DB"
export RFID1_STAGE1_DB_USER="$POSTGRES_USER"
export RFID1_STAGE1_DB_PASSWORD="$POSTGRES_PASSWORD"
export API_BIND_ADDRESS=127.0.0.1
export API_PORT=0
export SPRING_PROFILE=test
export SPRING_APPLICATION_NAME=smartparking-api-tarjetas-stage1-test
export SESSION_TIMEOUT=30m
export SESSION_COOKIE_SECURE=false
export SMTP_ENABLED=false

test_clases="${RFID1_STAGE1_MAVEN_TEST:-RepositorioRfid1JdbcTest,RepositorioTransicionesRfid1JdbcTest,RepositorioConfirmacionRfid1JdbcTest,RepositorioTarjetasRfidJdbcTest,ServicioConfirmacionRfid1Test,ServicioTarjetasRfid1Test,MantenimientoCapturasRfid1Test,ModeloTarjetasRfid1Test,ServicioRfid1Test,GestorSesionesPropietarioTest,ControladorLecturasRfid1SeguridadTest,TarjetasRfid1Stage1ApiAceptacionTest,TarjetasRfid1Stage1HistoriaAceptacionTest,CapturasRfid1ApiAceptacionTest}"
printf '%s\n' "Ejecutando aceptación API enfocada en PostgreSQL fresco."
pushd services/api >/dev/null
mvn --offline --batch-mode --no-transfer-progress -Dsmartparking.integration.disposable=true "-Dtest=$test_clases" test
popd >/dev/null

versiones_frescas="$(podman exec "$db_fresh" psql -X -qAt -U "$RFID1_STAGE1_POSTGRES_USER" -d "$RFID1_STAGE1_POSTGRES_DB" \
    -c "SELECT string_agg(version, ',' ORDER BY installed_rank) FROM flyway_schema_history WHERE success")"
[[ "$versiones_frescas" == "1,2,3,4,5,6,7,8,9,10,11,12" ]]

export API_BIND_ADDRESS=0.0.0.0
export API_PORT=8080
podman compose --project-name "$proyecto" -f "$compose_file" up -d api_fresh
api_fresca="$(podman compose --project-name "$proyecto" -f "$compose_file" ps -q api_fresh)"
puerto_api="$(podman port "$api_fresca" 8080/tcp | awk -F: '{print $NF}')"
if ! esperar_salud_api "$puerto_api"; then
    diagnosticar_api "$api_fresca" "$puerto_api" "$db_fresh" \
        "$RFID1_STAGE1_POSTGRES_USER" "$RFID1_STAGE1_POSTGRES_DB"
    exit 1
fi
export RFID1_STAGE1_API_URL="http://127.0.0.1:$puerto_api"
export RFID1_STAGE1_API_CONTAINER="$api_fresca"
export RFID1_STAGE1_DB_CONTAINER="$db_fresh"
PYTHONDONTWRITEBYTECODE=1 python3 -B infra/podman/testing/tarjetas-rfid-stage1/assertions/pty_aceptacion.py

salida_persistente_final="$(estado_persistente)"
[[ "$salida_persistente_inicial" == "$salida_persistente_final" ]]
printf '%s\n' "PASS: V1–V12, API/PTY aislados y recursos persistentes SmartParking preservados."
