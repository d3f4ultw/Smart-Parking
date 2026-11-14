#!/usr/bin/env bash
set -euo pipefail
umask 077

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$raiz"
compose_file="infra/podman/testing/rfid1-stage3/compose.yaml"
proyecto="smartparking-rfid1-stage3-$(tr -d '-' < /proc/sys/kernel/random/uuid | cut -c1-12)"
signal_dir="$raiz/infra/podman/testing/rfid1-stage3/.${proyecto}-signals"
if [[ -e "$signal_dir" ]]; then
    echo "El directorio temporal de señal ya existe; se detiene para no reemplazarlo." >&2
    exit 1
fi
mkdir -m 700 "$signal_dir"
export RFID1_STAGE3_PROJECT_NAME="$proyecto"
export RFID1_STAGE3_SIGNAL_DIR="$signal_dir"
export RFID1_STAGE3_POSTGRES_DB=smartparking_test_rfid1_stage3
export RFID1_STAGE3_POSTGRES_USER=smartparking_test_rfid1_stage3
export RFID1_STAGE3_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export RFID1_STAGE3_DEVICE_TOKEN="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
export RFID1_STAGE3_TOKEN_SHA256
RFID1_STAGE3_TOKEN_SHA256="$(printf '%s' "$RFID1_STAGE3_DEVICE_TOKEN" | sha256sum | cut -d ' ' -f1)"
export RFID1_STAGE3_OWNER_EMAIL="dueno-rfid-stage3-$(tr -d '-' < /proc/sys/kernel/random/uuid)@example.invalid"
export RFID1_STAGE3_OWNER_PASSWORD="$(openssl rand -hex 24)"
export RFID1_STAGE3_ADMIN_PASSWORD="$(openssl rand -hex 24)"
export RFID1_STAGE3_CLIENT_EMAIL="cliente-rfid-stage3-$(tr -d '-' < /proc/sys/kernel/random/uuid)@example.invalid"
export RFID1_STAGE3_CLIENT_PASSWORD="$(openssl rand -hex 24)"

limpiar() {
    podman compose --project-name "$proyecto" -f "$compose_file" down --volumes --remove-orphans \
        >/dev/null 2>&1 || true
    podman image rm -f "localhost/${proyecto}-api:stage3" "localhost/${proyecto}-web:stage3" \
        "localhost/${proyecto}-browser:stage3" \
        >/dev/null 2>&1 || true
    if [[ "$signal_dir" == "$raiz/infra/podman/testing/rfid1-stage3/.${proyecto}-signals" ]]; then
        rm -rf -- "$signal_dir"
    fi
}
trap limpiar EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

leer_persistentes() {
    # La salida de `podman ps` incluye duraciones relativas; se comparan campos estables.
    while IFS= read -r id; do
        [[ -z "$id" ]] && continue
        podman inspect --format '{{.Id}} {{.Name}} {{.Image}} {{.Config.Image}} {{.State.Status}}' "$id"
    done < <(podman ps -a --filter label=com.docker.compose.project=smartparking --format '{{.ID}}' | sort)
}
persistentes_antes="$(leer_persistentes)"
volumen_antes="$(podman volume inspect --format '{{.Name}} {{.CreatedAt}}' smartparking_postgres_datos)"
red_antes="$(podman network inspect --format '{{.Name}} {{.Id}}' smartparking_red_privada)"
db_estado_antes="$(podman inspect --format '{{.State.Status}}' smartparking-db-1)"
consulta_flyway="no"
if [[ "$db_estado_antes" == "running" ]]; then
    flyway_antes="$(podman exec --env PGOPTIONS='-c default_transaction_read_only=on' smartparking-db-1 \
        sh -c 'psql -X -qAt --set ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -c "SELECT version FROM flyway_schema_history WHERE success ORDER BY installed_rank;"')"
    versiones_esperadas=$'1\n2\n3\n4\n5\n6\n7\n8\n9\n10'
    if [[ "$flyway_antes" != "$versiones_esperadas" ]]; then
        echo "La instalación persistente no está en V1–V10; se detiene sin tocarla." >&2
        exit 1
    fi
    consulta_flyway="si"
elif [[ "$db_estado_antes" == "exited" ]]; then
    echo "PostgreSQL persistente está detenido; no se iniciará ni se consultará en esta corrida."
else
    echo "El estado de PostgreSQL persistente no es estable; se detiene sin tocarlo." >&2
    exit 1
fi

echo "Empaquetando API con JDK 27 y Maven offline."
(
    cd services/api
    mvn --offline --batch-mode --no-transfer-progress -DskipTests package
)

podman compose --project-name "$proyecto" -f "$compose_file" config --quiet
podman compose --project-name "$proyecto" -f "$compose_file" --profile browser build browser
podman compose --project-name "$proyecto" -f "$compose_file" up --build -d db api web
api_container="$(podman compose --project-name "$proyecto" -f "$compose_file" ps -q api)"
db_container="$(podman compose --project-name "$proyecto" -f "$compose_file" ps -q db)"
web_container="$(podman compose --project-name "$proyecto" -f "$compose_file" ps -q web)"
api_mapeo="$(podman port "$api_container" 8080/tcp)"
db_mapeo="$(podman port "$db_container" 5432/tcp)"
web_mapeo="$(podman port "$web_container" 3000/tcp)"
if [[ "$api_mapeo" != 127.0.0.1:* || "$db_mapeo" != 127.0.0.1:* || "$web_mapeo" != 127.0.0.1:* ]]; then
    echo "Un puerto descartable no quedó ligado exclusivamente a loopback." >&2
    exit 1
fi
api_port="${api_mapeo##*:}"
db_port="${db_mapeo##*:}"
web_port="${web_mapeo##*:}"
if [[ "$api_port" == "$db_port" || "$api_port" == "$web_port" || "$db_port" == "$web_port" ]]; then
    echo "Podman asignó puertos superpuestos a los servicios desechables." >&2
    exit 1
fi
for puerto in "$api_port" "$db_port" "$web_port"; do
    case "$puerto" in
        3000|8080|5432|8025)
            echo "Un servicio descartable tomó un puerto reservado de la instalación persistente." >&2
            exit 1
            ;;
    esac
done
export RFID1_STAGE3_API_URL="http://127.0.0.1:${api_port}"

esperar_servicio() {
    local url="$1" estado
    for intento in $(seq 1 90); do
        estado="$(curl --max-time 1 -sS -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
        if [[ "$estado" == "200" ]]; then return 0; fi
        sleep 1
    done
    echo "Un servicio Stage 3 no alcanzó disponibilidad: ${url##*/}." >&2
    return 1
}
esperar_servicio "$RFID1_STAGE3_API_URL/actuator/health"
esperar_servicio "http://127.0.0.1:${web_port}/"

PYTHONDONTWRITEBYTECODE=1 python3 -B infra/podman/testing/rfid1-stage3/bootstrap_web.py
echo "Ejecutando prueba BFF en el contenedor Web candidato."
podman exec --workdir /app "$web_container" node /tests/rfid1-bff.mjs
echo "Ejecutando aceptación Playwright en el proyecto aislado."
podman compose --project-name "$proyecto" -f "$compose_file" --profile browser run --rm browser

asociaciones_por_tipo="$(podman exec --env PGOPTIONS='-c default_transaction_read_only=on' "$db_container" \
    sh -c 'psql -X -qAt --set ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT count(*) FILTER (WHERE cliente_id IS NOT NULL), \
    count(*) FILTER (WHERE empleado_id IS NOT NULL) FROM asociacion_tarjeta_rfid1;"')"
if [[ "$asociaciones_por_tipo" != "1|1" ]]; then
    echo "La base descartable no contiene una asociación sintética por tipo de persona." >&2
    exit 1
fi
echo "PostgreSQL Stage 3 descartable confirma 1 asociación CLIENTE y 1 EMPLEADO."
echo "Proyecto aislado: $proyecto; puertos loopback API=$api_port, PostgreSQL=$db_port, Web=$web_port."

export RFID1_STAGE3_API_CONTAINER="$api_container"
export RFID1_STAGE3_DB_CONTAINER="$db_container"
export RFID1_STAGE3_WEB_CONTAINER="$web_container"
export RFID1_STAGE3_API_PORT="$api_port"
export RFID1_STAGE3_DB_PORT="$db_port"
export RFID1_STAGE3_WEB_PORT="$web_port"
echo "GATE A PASS. El entorno descartable sigue activo para la decisión del Gate B."
echo "Usa este shell solo para el preflight físico y la asociación autorizada; el comando exit limpia la prueba."
bash --noprofile --norc -i

resultado_fisico="PENDIENTE"
if [[ -f "$signal_dir/physical-result" ]]; then
    resultado_fisico="$(cat "$signal_dir/physical-result")"
fi
limpiar
trap - EXIT INT TERM
if [[ -n "$(podman ps --filter label=com.smartparking.testing.run="$proyecto" --format '{{.ID}}')" ]]; then
    echo "Quedaron contenedores Stage 3 tras la limpieza específica." >&2
    exit 1
fi
if [[ -n "$(podman volume ls --filter label=com.smartparking.testing.run="$proyecto" --format '{{.Name}}')" ]]; then
    echo "Quedaron volúmenes Stage 3 tras la limpieza específica." >&2
    exit 1
fi
if [[ -n "$(podman network ls --filter label=com.smartparking.testing.run="$proyecto" --format '{{.Name}}')" ]]; then
    echo "Quedaron redes Stage 3 tras la limpieza específica." >&2
    exit 1
fi
if [[ "$(leer_persistentes)" != "$persistentes_antes" ]]; then
    echo "Cambió la identidad de un contenedor persistente; no se intentará revertirlo." >&2
    exit 1
fi
if [[ "$consulta_flyway" == "si" ]]; then
    flyway_despues="$(podman exec --env PGOPTIONS='-c default_transaction_read_only=on' smartparking-db-1 \
        sh -c 'psql -X -qAt --set ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -c "SELECT version FROM flyway_schema_history WHERE success ORDER BY installed_rank;"')"
    if [[ "$flyway_despues" != "$flyway_antes" ]]; then
        echo "Cambió el historial Flyway persistente; se conserva para revisión." >&2
        exit 1
    fi
elif [[ "$(podman inspect --format '{{.State.Status}}' smartparking-db-1)" != "$db_estado_antes" ]]; then
    echo "Cambió el estado del PostgreSQL persistente; se conserva para revisión." >&2
    exit 1
fi
if [[ "$(podman volume inspect --format '{{.Name}} {{.CreatedAt}}' smartparking_postgres_datos)" != "$volumen_antes" \
    || "$(podman network inspect --format '{{.Name}} {{.Id}}' smartparking_red_privada)" != "$red_antes" ]]; then
    echo "Cambió un recurso persistente; se conserva para revisión." >&2
    exit 1
fi
if [[ "$consulta_flyway" == "si" ]]; then
    echo "La instalación persistente conserva contenedores, volumen, red y Flyway V1–V10."
else
    echo "La instalación persistente conserva contenedores, volumen y red; PostgreSQL permaneció detenido y Flyway no se consultó."
fi
echo "Resultado físico registrado por el Gate B: ${resultado_fisico//[$'\n']/; }."
unset RFID1_STAGE3_DEVICE_TOKEN RFID1_STAGE3_TOKEN_SHA256 RFID1_STAGE3_POSTGRES_PASSWORD
unset RFID1_STAGE3_OWNER_PASSWORD RFID1_STAGE3_ADMIN_PASSWORD RFID1_STAGE3_CLIENT_PASSWORD
unset RFID1_STAGE3_OWNER_EMAIL RFID1_STAGE3_CLIENT_EMAIL RFID1_STAGE3_PROJECT_NAME
unset RFID1_STAGE3_POSTGRES_DB RFID1_STAGE3_POSTGRES_USER RFID1_STAGE3_API_URL
unset RFID1_STAGE3_SIGNAL_DIR RFID1_STAGE3_API_CONTAINER RFID1_STAGE3_DB_CONTAINER RFID1_STAGE3_WEB_CONTAINER
unset RFID1_STAGE3_API_PORT RFID1_STAGE3_DB_PORT RFID1_STAGE3_WEB_PORT
