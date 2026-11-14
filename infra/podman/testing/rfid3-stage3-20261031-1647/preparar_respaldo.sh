#!/usr/bin/env bash
# Mantiene la instalación en mantenimiento solo tras completar el respaldo V13.
set -euo pipefail
umask 077
cd /mnt/new-volume/SmartParking

trabajo='infra/podman/testing/rfid3-stage3-20261031-1647'
respaldo='infra/podman/private-backups/rfid3-stage3-20261031-1647'
dump="$respaldo/smartparking_local-v13.dump"
parcial="$respaldo/smartparking_local-v13.dump.parcial"
bridge='smartparking-rfid1-bridge.service'
api='smartparking-api-1'
db='smartparking-db-1'
puerto='/dev/ttyACM0'
detuvo_bridge=0
detuvo_api=0
completo=0
guardia=0

verificar_guardia() {
    local estado
    estado=$(podman exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1 -c "SELECT (count(DISTINCT c.oid)=(SELECT count(*) FROM pg_tables WHERE schemaname='\''public'\'') AND count(DISTINCT a.pid)=1) FROM pg_locks l JOIN pg_class c ON c.oid=l.relation JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_stat_activity a ON a.pid=l.pid WHERE n.nspname='\''public'\'' AND c.relkind IN ('\''r'\'','\''p'\'') AND l.mode='\''ShareLock'\'' AND l.granted AND a.datname=current_database() AND l.database=(SELECT oid FROM pg_database WHERE datname=current_database()) AND a.application_name='\''smartparking_rfid3_stage3_guard_1647'\'' AND a.wait_event='\''PgSleep'\'';"')
    [[ "$estado" == t ]]
}

liberar_guardia() {
    if (( guardia )); then
        local restantes
        podman exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=current_database() AND application_name='\''smartparking_rfid3_stage3_guard_1647'\'';"' >/dev/null || return 1
        for intento in $(seq 1 5); do
            restantes=$(podman exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND application_name='\''smartparking_rfid3_stage3_guard_1647'\'';"') || return 1
            [[ "$restantes" == 0 ]] && return 0
            sleep 1
        done
        return 1
    fi
}

recuperar() {
    if (( completo )); then return; fi
    printf 'CORTE_CANCELADO: se intentará restablecer el estado anterior.\n'
    if ! liberar_guardia; then
        printf 'RECUPERACION_INCOMPLETA: guardia de escritura aún activa o no verificable.\n' >&2
        return
    fi
    if (( detuvo_api )); then
        estado=$(podman inspect --format '{{.State.Status}}' "$api" 2>/dev/null || true)
        if [[ "$estado" != running ]]; then
            podman start "$api" >/dev/null || { printf 'API_ANTERIOR_NO_RESTITUIDA\n' >&2; return; }
        fi
    fi
    if (( detuvo_bridge )); then
        for intento in $(seq 1 40); do
            codigo=$(curl --max-time 1 -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/actuator/health || true)
            [[ "$codigo" == 200 ]] && break
            sleep 1
        done
        if [[ "${codigo:-000}" != 200 ]]; then
            printf 'BRIDGE_NO_RESTITUIDO: API anterior no saludable.\n' >&2
            return
        fi
        if ! systemctl --user is-active --quiet "$bridge"; then
            if ! PYTHONDONTWRITEBYTECODE=1 python3 -B firmware/esp32/.backups/20261031-142037-buzzer-rfid2-d21-rfid3-d25/arrancar_bridge_previo.py; then
                systemctl --user stop "$bridge" || true
                printf 'BRIDGE_NO_RESTITUIDO: recuperación no verificada.\n' >&2
            fi
        else
            printf 'BRIDGE_ACTIVO: verificar PONG y propietario antes de operar.\n' >&2
        fi
    fi
}
trap recuperar EXIT

test ! -e "$dump"
test ! -e "$parcial"
test ! -e "$respaldo/huellas-v13.json"
test ! -e "$respaldo/flyway-v13.txt"
test "$(stat -c %a "$respaldo")" = 700
test "$(systemctl --user show "$bridge" -p MainPID --value)" = 3773241
test "$(systemctl --user show "$bridge" -p NRestarts --value)" = 0
test "$(podman inspect --format '{{.Image}}' "$api")" = 79ad4890e16b75a21e3bf3a35f9eef444c99f66a92ea05326ff075cd687bada2
test "$(podman inspect --format '{{.State.Status}}' "$api")" = running

lecturas=$(podman exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM captura_rfid1 WHERE estado IN ('\''PENDIENTE'\'','\''ESCANEANDO'\'','\''VISTA_PREVIA'\'');"')
test "$lecturas" = 0
purga=$(podman exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM captura_rfid1 WHERE estado IN ('\''COMPLETADA'\'','\''CANCELADA'\'','\''EXPIRADA'\'','\''RECHAZADA'\'') AND actualizada_en <= now() - interval '\''23 hours'\'';"')
test "$purga" = 0
detuvo_bridge=1
systemctl --user stop "$bridge"
test "$(systemctl --user show "$bridge" -p ActiveState --value)" = inactive
for herramienta in fuser lsof; do
    set +e
    if [[ "$herramienta" == fuser ]]; then salida=$(fuser -s "$puerto" 2>&1); else salida=$(lsof -n -t "$puerto" 2>&1); fi
    estado=$?
    set -e
    if [[ "$estado" != 1 || -n "$salida" ]]; then
        printf 'USB_NO_LIBRE_O_INSPECCION_FALLIDA\n' >&2
        exit 1
    fi
done
estables=0
for intento in $(seq 1 30); do
    activas=$(podman exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND backend_type='\''client backend'\'' AND pid<>pg_backend_pid() AND (state <> '\''idle'\'' OR xact_start IS NOT NULL);"')
    if [[ "$activas" == 0 ]]; then estables=$((estables + 1)); else estables=0; fi
    (( estables >= 5 )) && break
    sleep 1
done
test "$estables" -ge 5
detuvo_api=1
podman stop --time 20 "$api" >/dev/null
test "$(podman inspect --format '{{.State.Status}}' "$api")" = exited

for intento in $(seq 1 20); do
    conexiones=$(podman exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND backend_type='\''client backend'\'' AND pid<>pg_backend_pid();"')
    [[ "$conexiones" == 0 ]] && break
    sleep 1
done
test "${conexiones:-1}" = 0
sql_guardia=$(cat <<'SQL'
BEGIN;
SET LOCAL lock_timeout = '5s';
DO $sp$
DECLARE tabla record;
BEGIN
  FOR tabla IN SELECT schemaname, tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename LOOP
    EXECUTE format('LOCK TABLE %I.%I IN SHARE MODE', tabla.schemaname, tabla.tablename);
  END LOOP;
END $sp$;
SELECT pg_sleep(900);
COMMIT;
SQL
)
guardia=1
podman exec -d -e PGAPPNAME=smartparking_rfid3_stage3_guard_1647 "$db" sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -q -v ON_ERROR_STOP=1 -c "$1"' sh "$sql_guardia" >/dev/null
for intento in $(seq 1 15); do
    if verificar_guardia; then break; fi
    sleep 1
done
verificar_guardia
printf 'GUARDIA_DE_ESCRITURA_ACTIVA\n'
estado=$(podman exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1 -c "SELECT (count(*)=13 AND count(DISTINCT version::integer)=13 AND count(*) FILTER (WHERE success AND version::integer BETWEEN 1 AND 13)=13 AND count(*) FILTER (WHERE version='\''14'\'')=0) FROM flyway_schema_history; SELECT count(*) FROM captura_rfid1 WHERE estado IN ('\''PENDIENTE'\'','\''ESCANEANDO'\'','\''VISTA_PREVIA'\'');"')
test "$estado" = $'t\n0'
podman exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1 -c "SELECT version,checksum,success FROM flyway_schema_history ORDER BY installed_rank;"' > "$respaldo/flyway-v13.txt"
cmp -s "$trabajo/flyway-preflight.txt" "$respaldo/flyway-v13.txt"
podman exec "$db" sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$parcial"
podman exec -i "$db" pg_restore --list < "$parcial" >/dev/null
test -s "$parcial"
mv -n "$parcial" "$dump"
test -f "$dump"
test ! -e "$parcial"
podman exec -i "$db" pg_restore --list < "$dump" >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -B "$trabajo/huellas_postgresql.py" "$db" "$respaldo/huellas-v13.json"
conexiones=$(podman exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND backend_type='\''client backend'\'' AND pid<>pg_backend_pid() AND application_name <> '\''smartparking_rfid3_stage3_guard_1647'\'';"')
test "$conexiones" = 0
verificar_guardia
sha256sum "$dump"
stat -c 'permisos=%a tamano=%s' "$dump"
printf 'RESPALDO_V13_VERIFICADO; SERVICIOS_EN_MANTENIMIENTO\n'
completo=1
