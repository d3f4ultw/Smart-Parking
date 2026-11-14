#!/usr/bin/env bash
set -euo pipefail
umask 077

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$raiz"
compose_file="infra/podman/testing/tarjetas-rfid-stage2/compose.yaml"
proyecto="smartparking-tarjetas-rfid-stage2-$(tr -d '-' < /proc/sys/kernel/random/uuid | cut -c1-12)"
run_id="$(tr -d '-' < /proc/sys/kernel/random/uuid)"
browser_args=("$@")
web_format_targets=(
    app/components/admin/clientes/TablaClientes.vue
    app/components/admin/empleados/TablaEmpleados.vue
    app/components/admin/tarjetas-rfid/DirectorioTarjetasRfid1.vue
    app/components/admin/tarjetas-rfid/ModalAsociacionTarjetaRfid1.vue
    app/components/admin/tarjetas-rfid/ModalDetalleTarjetaRfid1.vue
    app/components/admin/tarjetas-rfid/SelectorPersonaRfid1.vue
    app/composables/useFlujoAsociacionRfid1.ts
    app/composables/useBusquedaPersonasRfid1.ts
    app/composables/useCancelacionCapturaRfid1.ts
    app/composables/useCapturaRfid1.ts
    app/composables/useDirectorioTarjetasRfid1.ts
    app/composables/useRetornoFocoRfid1.ts
    app/composables/useVigenciaCapturaRfid1.ts
    app/layouts/admin.vue
    app/pages/admin/clientes.vue
    app/pages/admin/empleados.vue
    app/pages/admin/tarjetas-rfid.vue
    app/plugins/eventos-administracion.client.ts
    app/types/rfid1.ts
    app/utils/rfid1-api.ts
    server/api/[...path].ts
    server/utils/rfid1-bff.ts
    tests/rfid1-bff.mjs
    tests/browser/tarjetas-rfid/01-directorio.spec.ts
    tests/browser/tarjetas-rfid/02-asociacion.spec.ts
    tests/browser/tarjetas-rfid/03-historial.spec.ts
    tests/browser/tarjetas-rfid/04-seguridad.spec.ts
    tests/browser/tarjetas-rfid/05-reconciliacion.spec.ts
    tests/browser/tarjetas-rfid/06-concurrencia.spec.ts
    tests/browser/tarjetas-rfid/soporte.ts
)
if ((${#browser_args[@]} == 0)); then
    browser_args=("tarjetas-rfid/")
fi

unset POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
unset API_BIND_ADDRESS API_PORT SPRING_PROFILE SPRING_APPLICATION_NAME
unset SESSION_TIMEOUT SESSION_COOKIE_SECURE SMTP_ENABLED
unset NUXT_API_INTERNAL_BASE TEST_OWNER_EMAIL TEST_OWNER_PASSWORD TEST_CLIENT_EMAIL
unset TEST_CLIENT_PASSWORD TEST_DEVICE_TOKEN TEST_API_BASE_URL TEST_WEB_BASE_URL

export RFID1_STAGE2_PROJECT_NAME="$proyecto"
export RFID1_STAGE2_POSTGRES_DB="smartparking_rfid1_stage2"
export RFID1_STAGE2_POSTGRES_USER="smartparking_rfid1_stage2"
export RFID1_STAGE2_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export RFID1_STAGE2_DEVICE_TOKEN="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
export RFID1_STAGE2_TOKEN_SHA256
RFID1_STAGE2_TOKEN_SHA256="$(printf '%s' "$RFID1_STAGE2_DEVICE_TOKEN" | sha256sum | cut -d ' ' -f1)"
export RFID1_STAGE2_OWNER_EMAIL="dueno-tarjetas-stage2-$run_id@example.invalid"
export RFID1_STAGE2_OWNER_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
export RFID1_STAGE2_ADMIN_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
export RFID1_STAGE2_CLIENT_EMAIL="cliente-tarjetas-stage2-$run_id@example.invalid"
export RFID1_STAGE2_CLIENT_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
export TEST_OWNER_EMAIL="$RFID1_STAGE2_OWNER_EMAIL"
export TEST_OWNER_PASSWORD="$RFID1_STAGE2_OWNER_PASSWORD"
export TEST_CLIENT_EMAIL="$RFID1_STAGE2_CLIENT_EMAIL"
export TEST_CLIENT_PASSWORD="$RFID1_STAGE2_CLIENT_PASSWORD"
export TEST_DEVICE_TOKEN="$RFID1_STAGE2_DEVICE_TOKEN"

limpiar() {
    podman compose --project-name "$proyecto" -f "$compose_file" down --volumes --remove-orphans \
        >/dev/null 2>&1 || true
    podman image rm "localhost/$proyecto-api:stage2" "localhost/$proyecto-web:stage2" \
        "localhost/$proyecto-web-checks:stage2" "localhost/$proyecto-browser:stage2" \
        >/dev/null 2>&1 || true
}
trap limpiar EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

leer_persistentes() {
    while IFS= read -r id; do
        [[ -z "$id" ]] && continue
        podman inspect --format '{{.Id}} {{.Name}} {{.Image}} {{.Config.Image}} {{.State.Status}}' "$id"
    done < <(podman ps -a --filter label=com.docker.compose.project=smartparking --format '{{.ID}}' | sort)
}

esperar_http200() {
    local url="$1" estado
    for intento in $(seq 1 90); do
        estado="$(curl --max-time 1 -sS -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
        if [[ "$estado" == "200" ]]; then return 0; fi
        sleep 1
    done
    echo "Un servicio Stage 2 no alcanzó disponibilidad: ${url##*/}." >&2
    return 1
}

persistentes_antes="$(leer_persistentes)"
volumen_antes="$(podman volume inspect --format '{{.Name}} {{.CreatedAt}}' smartparking_postgres_datos)"
red_privada_antes="$(podman network inspect --format '{{.Name}} {{.Id}}' smartparking_red_privada)"
red_api_antes="$(podman network inspect --format '{{.Name}} {{.Id}}' smartparking_api_web_privada)"

podman compose --project-name "$proyecto" -f "$compose_file" config --quiet
echo "Validando formato del alcance RFID, lint y typecheck Web dentro de Podman."
podman compose --project-name "$proyecto" -f "$compose_file" --profile checks build web_checks
podman compose --project-name "$proyecto" -f "$compose_file" --profile checks run --rm web_checks \
    pnpm exec vp fmt -c tooling/vite.config.ts "${web_format_targets[@]}" --check
podman compose --project-name "$proyecto" -f "$compose_file" --profile checks run --rm web_checks pnpm run lint
podman compose --project-name "$proyecto" -f "$compose_file" --profile checks run --rm web_checks pnpm run typecheck
echo "Construyendo API, Web y Playwright en contenedores Podman."
podman compose --project-name "$proyecto" -f "$compose_file" --profile browser build api web browser
podman compose --project-name "$proyecto" -f "$compose_file" up -d db api web

db="$(podman compose --project-name "$proyecto" -f "$compose_file" ps -q db)"
api="$(podman compose --project-name "$proyecto" -f "$compose_file" ps -q api)"
web="$(podman compose --project-name "$proyecto" -f "$compose_file" ps -q web)"
api_mapeo="$(podman port "$api" 8080/tcp)"
web_mapeo="$(podman port "$web" 3000/tcp)"
if [[ "$api_mapeo" != 127.0.0.1:* || "$web_mapeo" != 127.0.0.1:* ]]; then
    echo "Los puertos de prueba API/Web no quedaron ligados a loopback." >&2
    exit 1
fi
api_port="${api_mapeo##*:}"
web_port="${web_mapeo##*:}"
for port in "$api_port" "$web_port"; do
    case "$port" in
        3000|5432|8025|8080)
            echo "Un servicio desechable tomó un puerto reservado." >&2
            exit 1
            ;;
    esac
done

export RFID1_STAGE2_API_URL="http://127.0.0.1:$api_port"
esperar_http200 "$RFID1_STAGE2_API_URL/actuator/health"
esperar_http200 "http://127.0.0.1:$web_port/"

PYTHONDONTWRITEBYTECODE=1 python3 -B infra/podman/testing/tarjetas-rfid-stage2/bootstrap_web.py
echo "Ejecutando aceptación BFF dentro del contenedor Web."
podman exec --workdir /app "$web" node /tests/rfid1-bff.mjs
echo "Ejecutando aceptación Playwright dentro del contenedor de navegador."
podman compose --project-name "$proyecto" -f "$compose_file" --profile browser run --rm browser \
    pnpm exec playwright test --config=playwright.config.ts "${browser_args[@]}"

versiones="$(podman exec --env PGOPTIONS='-c default_transaction_read_only=on' "$db" \
    sh -c 'psql -X -qAt --set ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT string_agg(version, chr(44) ORDER BY installed_rank) FROM flyway_schema_history WHERE success"')"
if [[ "$versiones" != "1,2,3,4,5,6,7,8,9,10,11,12" ]]; then
    echo "La base Stage 2 desechable no terminó en Flyway V1–V12." >&2
    exit 1
fi

limpiar
trap - EXIT INT TERM
if [[ -n "$(podman ps -a --filter label=com.smartparking.testing.run="$proyecto" --format '{{.ID}}')" \
    || -n "$(podman volume ls --filter label=com.smartparking.testing.run="$proyecto" --format '{{.Name}}')" \
    || -n "$(podman network ls --filter label=com.smartparking.testing.run="$proyecto" --format '{{.Name}}')" ]]; then
    echo "La limpieza limitada dejó recursos Stage 2 desechables." >&2
    exit 1
fi
if [[ "$(leer_persistentes)" != "$persistentes_antes" \
    || "$(podman volume inspect --format '{{.Name}} {{.CreatedAt}}' smartparking_postgres_datos)" != "$volumen_antes" \
    || "$(podman network inspect --format '{{.Name}} {{.Id}}' smartparking_red_privada)" != "$red_privada_antes" \
    || "$(podman network inspect --format '{{.Name}} {{.Id}}' smartparking_api_web_privada)" != "$red_api_antes" ]]; then
    echo "Cambió un recurso persistente; no se intenta revertirlo." >&2
    exit 1
fi
printf '%s\n' "PASS: BFF/Playwright completados, Flyway V1–V12 y recursos persistentes SmartParking preservados."

unset RFID1_STAGE2_DEVICE_TOKEN RFID1_STAGE2_TOKEN_SHA256 RFID1_STAGE2_POSTGRES_PASSWORD
unset RFID1_STAGE2_OWNER_PASSWORD RFID1_STAGE2_ADMIN_PASSWORD RFID1_STAGE2_CLIENT_PASSWORD
unset TEST_DEVICE_TOKEN TEST_OWNER_PASSWORD TEST_CLIENT_PASSWORD
