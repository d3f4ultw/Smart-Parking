#!/usr/bin/env bash
# Libera únicamente la guardia de esta ejecución antes de iniciar el bridge.
set -euo pipefail
cd /mnt/new-volume/SmartParking
registro='infra/podman/testing/rfid3-stage3-20261031-1647/activacion-esp32.log'
db='smartparking-db-1'
rg -q '^FIRMWARE_CANDIDATO_ACTIVO$' "$registro"
test "$(systemctl --user show smartparking-rfid1-bridge.service -p ActiveState --value)" = inactive
test "$(curl --max-time 2 -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/actuator/health)" = 200
for herramienta in fuser lsof; do
    set +e
    if [[ "$herramienta" == fuser ]]; then salida=$(fuser -s /dev/ttyACM0 2>&1); else salida=$(lsof -n -t /dev/ttyACM0 2>&1); fi
    estado=$?
    set -e
    test "$estado" = 1
    test -z "$salida"
done
guardia=$(podman exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1 -c "SELECT (count(DISTINCT c.oid)=(SELECT count(*) FROM pg_tables WHERE schemaname='\''public'\'') AND count(DISTINCT a.pid)=1) FROM pg_locks l JOIN pg_class c ON c.oid=l.relation JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_stat_activity a ON a.pid=l.pid WHERE n.nspname='\''public'\'' AND c.relkind IN ('\''r'\'','\''p'\'') AND l.mode='\''ShareLock'\'' AND l.granted AND a.datname=current_database() AND l.database=(SELECT oid FROM pg_database WHERE datname=current_database()) AND a.application_name='\''smartparking_rfid3_stage3_guard_1647'\'' AND a.wait_event='\''PgSleep'\'';"')
test "$guardia" = t
podman exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=current_database() AND application_name='\''smartparking_rfid3_stage3_guard_1647'\'';"' >/dev/null
for intento in $(seq 1 5); do
    restantes=$(podman exec "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -qAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND application_name='\''smartparking_rfid3_stage3_guard_1647'\'';"')
    [[ "$restantes" == 0 ]] && break
    sleep 1
done
test "${restantes:-1}" = 0
printf 'GUARDIA_LIBERADA; API_HEALTH=200; USB_LIBRE\n'
