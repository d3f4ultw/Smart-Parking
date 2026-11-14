#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$raiz"
accion="${1:-}"
compose_file="infra/podman/testing/tarjetas-rfid-stage2/compose.yaml"
directorio_estado="${XDG_RUNTIME_DIR:-/tmp}/smartparking-tarjetas-rfid-stage3"
archivo_estado="$directorio_estado/estado.env"

leer_persistentes() {
    podman ps -a --filter label=com.docker.compose.project=smartparking \
        --format '{{.ID}} {{.Names}} {{.Image}} {{.State}}' | sort
}

normalizar_persistentes() {
    printf '%s\n' "$1" | awk 'NF >= 4 {print $1, $2, $3, $4}'
}

leer_redes_persistentes() {
    podman network ls --filter label=com.docker.compose.project=smartparking \
        --format '{{.Name}} {{.ID}}' | sort
}

leer_volumen_persistente() {
    podman volume inspect --format '{{.Name}} {{.CreatedAt}}' smartparking_postgres_datos
}

verificar_estado_persistente() {
    if [[ "$(leer_persistentes)" != "$(normalizar_persistentes "$PERSISTENTES_ANTES")" \
        || "$(leer_redes_persistentes)" != "$REDES_ANTES" \
        || "$(leer_volumen_persistente)" != "$VOLUMEN_ANTES" ]]; then
        echo "Cambió un recurso persistente SmartParking; no se intenta revertirlo." >&2
        return 1
    fi
}

guardar_estado() {
    mkdir -p "$directorio_estado"
    chmod 700 "$directorio_estado"
    {
        printf 'export RFID1_STAGE2_PROJECT_NAME=%q\n' "$RFID1_STAGE2_PROJECT_NAME"
        printf 'export RFID1_STAGE2_POSTGRES_DB=%q\n' "$RFID1_STAGE2_POSTGRES_DB"
        printf 'export RFID1_STAGE2_POSTGRES_USER=%q\n' "$RFID1_STAGE2_POSTGRES_USER"
        printf 'export RFID1_STAGE2_POSTGRES_PASSWORD=%q\n' "$RFID1_STAGE2_POSTGRES_PASSWORD"
        printf 'export RFID1_STAGE2_DEVICE_TOKEN=%q\n' "$RFID1_STAGE2_DEVICE_TOKEN"
        printf 'export RFID1_STAGE2_TOKEN_SHA256=%q\n' "$RFID1_STAGE2_TOKEN_SHA256"
        printf 'export RFID1_STAGE2_OWNER_EMAIL=%q\n' "$RFID1_STAGE2_OWNER_EMAIL"
        printf 'export RFID1_STAGE2_OWNER_PASSWORD=%q\n' "$RFID1_STAGE2_OWNER_PASSWORD"
        printf 'export RFID1_STAGE2_ADMIN_PASSWORD=%q\n' "$RFID1_STAGE2_ADMIN_PASSWORD"
        printf 'export RFID1_STAGE2_CLIENT_EMAIL=%q\n' "$RFID1_STAGE2_CLIENT_EMAIL"
        printf 'export RFID1_STAGE2_CLIENT_PASSWORD=%q\n' "$RFID1_STAGE2_CLIENT_PASSWORD"
        printf 'export PERSISTENTES_ANTES=%q\n' "$PERSISTENTES_ANTES"
        printf 'export REDES_ANTES=%q\n' "$REDES_ANTES"
        printf 'export VOLUMEN_ANTES=%q\n' "$VOLUMEN_ANTES"
        printf 'export RFID1_STAGE3_API_URL=%q\n' "$RFID1_STAGE3_API_URL"
        printf 'export RFID1_STAGE3_WEB_URL=%q\n' "$RFID1_STAGE3_WEB_URL"
    } > "$archivo_estado"
    chmod 600 "$archivo_estado"
}

cargar_estado() {
    if [[ ! -f "$archivo_estado" ]]; then
        echo "No hay un stack Stage 3 registrado." >&2
        exit 2
    fi
    # El archivo solo lo crea este runner con valores generados localmente y permisos 0600.
    # shellcheck disable=SC1090
    source "$archivo_estado"
    if [[ ! "$RFID1_STAGE2_PROJECT_NAME" =~ ^smartparking-tarjetas-rfid-stage3-[0-9a-f]{12}$ ]]; then
        echo "El identificador del proyecto Stage 3 no es válido." >&2
        exit 2
    fi
}

compose() {
    podman compose --project-name "$RFID1_STAGE2_PROJECT_NAME" -f "$compose_file" "$@"
}

esperar_http200() {
    local url="$1" estado
    for intento in $(seq 1 90); do
        estado="$(curl --max-time 1 -sS -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
        if [[ "$estado" == "200" ]]; then return 0; fi
        sleep 1
    done
    echo "Un servicio Stage 3 no alcanzó disponibilidad: ${url##*/}." >&2
    return 1
}

esperar_db() {
    local db
    db="$(compose ps -q db)"
    for intento in $(seq 1 90); do
        if podman exec "$db" pg_isready -U "$RFID1_STAGE2_POSTGRES_USER" \
            -d "$RFID1_STAGE2_POSTGRES_DB" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    echo "PostgreSQL Stage 3 no quedó listo." >&2
    return 1
}

bootstrap() {
    local web
    web="$(compose ps -q web)"
    RFID1_STAGE2_API_URL="$RFID1_STAGE3_API_URL" \
        PYTHONDONTWRITEBYTECODE=1 python3 -B infra/podman/testing/tarjetas-rfid-stage2/bootstrap_web.py
    podman exec --workdir /app "$web" node /tests/rfid1-bff.mjs
}

preparar_stack() {
    compose up -d db api web
    esperar_db
    local api web api_mapeo web_mapeo api_port web_port
    api="$(compose ps -q api)"
    web="$(compose ps -q web)"
    api_mapeo="$(podman port "$api" 8080/tcp)"
    web_mapeo="$(podman port "$web" 3000/tcp)"
    if [[ "$api_mapeo" != 127.0.0.1:* || "$web_mapeo" != 127.0.0.1:* ]]; then
        echo "Los puertos de API/Web Stage 3 no quedaron ligados a loopback." >&2
        return 1
    fi
    api_port="${api_mapeo##*:}"
    web_port="${web_mapeo##*:}"
    for port in "$api_port" "$web_port"; do
        case "$port" in
            3000|5432|8025|8080)
                echo "Un servicio desechable tomó un puerto reservado." >&2
                return 1
                ;;
        esac
    done
    RFID1_STAGE3_API_URL="http://127.0.0.1:$api_port"
    RFID1_STAGE3_WEB_URL="http://127.0.0.1:$web_port"
    guardar_estado
    esperar_http200 "$RFID1_STAGE3_API_URL/actuator/health"
    esperar_http200 "$RFID1_STAGE3_WEB_URL/"
    bootstrap
}

limpiar_proyecto() {
    compose down --volumes --remove-orphans
    podman image rm "localhost/$RFID1_STAGE2_PROJECT_NAME-api:stage2" \
        "localhost/$RFID1_STAGE2_PROJECT_NAME-web:stage2" \
        "localhost/$RFID1_STAGE2_PROJECT_NAME-browser:stage2" >/dev/null 2>&1 || true
    if [[ -n "$(podman ps -a --filter label=com.smartparking.testing.run="$RFID1_STAGE2_PROJECT_NAME" --format '{{.ID}}')" \
        || -n "$(podman volume ls --filter label=com.smartparking.testing.run="$RFID1_STAGE2_PROJECT_NAME" --format '{{.Name}}')" \
        || -n "$(podman network ls --filter label=com.smartparking.testing.run="$RFID1_STAGE2_PROJECT_NAME" --format '{{.Name}}')" ]]; then
        echo "La limpieza limitada dejó recursos Stage 3." >&2
        return 1
    fi
    verificar_estado_persistente
}

case "$accion" in
    iniciar)
        if [[ -e "$archivo_estado" ]]; then
            echo "Ya existe un stack Stage 3; usa estado, reiniciar o detener." >&2
            exit 2
        fi
        unset POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
        unset API_BIND_ADDRESS API_PORT SPRING_PROFILE SPRING_APPLICATION_NAME
        unset SESSION_TIMEOUT SESSION_COOKIE_SECURE SMTP_ENABLED NUXT_API_INTERNAL_BASE
        unset TEST_OWNER_EMAIL TEST_OWNER_PASSWORD TEST_CLIENT_EMAIL TEST_CLIENT_PASSWORD TEST_DEVICE_TOKEN
        run_id="$(tr -d '-' < /proc/sys/kernel/random/uuid)"
        RFID1_STAGE2_PROJECT_NAME="smartparking-tarjetas-rfid-stage3-${run_id:0:12}"
        RFID1_STAGE2_POSTGRES_DB="smartparking_rfid1_stage3"
        RFID1_STAGE2_POSTGRES_USER="smartparking_rfid1_stage3"
        RFID1_STAGE2_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
        RFID1_STAGE2_DEVICE_TOKEN="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
        RFID1_STAGE2_TOKEN_SHA256="$(printf '%s' "$RFID1_STAGE2_DEVICE_TOKEN" | sha256sum | cut -d ' ' -f1)"
        RFID1_STAGE2_OWNER_EMAIL="dueno-tarjetas-stage3-${run_id}@example.invalid"
        RFID1_STAGE2_OWNER_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
        RFID1_STAGE2_ADMIN_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
        RFID1_STAGE2_CLIENT_EMAIL="cliente-tarjetas-stage3-${run_id}@example.invalid"
        RFID1_STAGE2_CLIENT_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
        RFID1_STAGE3_API_URL=""
        RFID1_STAGE3_WEB_URL=""
        TEST_OWNER_EMAIL="$RFID1_STAGE2_OWNER_EMAIL"
        TEST_OWNER_PASSWORD="$RFID1_STAGE2_OWNER_PASSWORD"
        TEST_CLIENT_EMAIL="$RFID1_STAGE2_CLIENT_EMAIL"
        TEST_CLIENT_PASSWORD="$RFID1_STAGE2_CLIENT_PASSWORD"
        TEST_DEVICE_TOKEN="$RFID1_STAGE2_DEVICE_TOKEN"
        export RFID1_STAGE2_PROJECT_NAME RFID1_STAGE2_POSTGRES_DB RFID1_STAGE2_POSTGRES_USER
        export RFID1_STAGE2_POSTGRES_PASSWORD RFID1_STAGE2_DEVICE_TOKEN RFID1_STAGE2_TOKEN_SHA256
        export RFID1_STAGE2_OWNER_EMAIL RFID1_STAGE2_OWNER_PASSWORD RFID1_STAGE2_ADMIN_PASSWORD
        export RFID1_STAGE2_CLIENT_EMAIL RFID1_STAGE2_CLIENT_PASSWORD
        export TEST_OWNER_EMAIL TEST_OWNER_PASSWORD TEST_CLIENT_EMAIL TEST_CLIENT_PASSWORD TEST_DEVICE_TOKEN
        PERSISTENTES_ANTES="$(leer_persistentes)"
        REDES_ANTES="$(leer_redes_persistentes)"
        VOLUMEN_ANTES="$(leer_volumen_persistente)"
        export PERSISTENTES_ANTES REDES_ANTES VOLUMEN_ANTES
        guardar_estado
        on_error() {
            local codigo="$?"
            trap - ERR
            limpiar_proyecto || true
            rm -f "$archivo_estado"
            echo "Falló la preparación Stage 3 (código $codigo); se retiraron solo recursos etiquetados de esta ejecución." >&2
            exit "$codigo"
        }
        trap on_error ERR INT TERM
        compose config --quiet
        echo "Construyendo API, Web y navegador candidatos dentro de Podman."
        compose --profile browser build api web browser
        preparar_stack
        db="$(compose ps -q db)"
        versiones="$(podman exec --env PGOPTIONS='-c default_transaction_read_only=on' "$db" \
            sh -c 'psql -X -qAt --set ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -c "SELECT string_agg(version, chr(44) ORDER BY installed_rank) FROM flyway_schema_history WHERE success"')"
        if [[ "$versiones" != "1,2,3,4,5,6,7,8,9,10,11,12" ]]; then
            echo "La base desechable no terminó en Flyway V1–V12." >&2
            false
        fi
        echo "Ejecutando solo los flujos Playwright de asociación e historial de RFID."
        compose --profile browser run --rm browser pnpm exec playwright test \
            --config=playwright.config.ts tarjetas-rfid/02-asociacion.spec.ts \
            tarjetas-rfid/03-historial.spec.ts
        verificar_estado_persistente
        trap - ERR
        echo "Gate A PASS. Stack desechable activo para la aceptación física:"
        echo "Proyecto: $RFID1_STAGE2_PROJECT_NAME"
        echo "API aislada: $RFID1_STAGE3_API_URL"
        echo "Web aislada: $RFID1_STAGE3_WEB_URL"
        echo "Las credenciales sintéticas permanecen en $archivo_estado (modo 0600)."
        ;;
    estado)
        cargar_estado
        printf 'Proyecto: %s\nAPI aislada: %s\nWeb aislada: %s\n' \
            "$RFID1_STAGE2_PROJECT_NAME" "$RFID1_STAGE3_API_URL" "$RFID1_STAGE3_WEB_URL"
        compose ps
        ;;
    reiniciar)
        cargar_estado
        echo "Recreando solo la base V1–V12 desechable para iniciar un fixture sintético limpio."
        compose down --volumes --remove-orphans
        if [[ -n "$(podman volume ls --filter label=com.smartparking.testing.run="$RFID1_STAGE2_PROJECT_NAME" --format '{{.Name}}')" \
            || -n "$(podman network ls --filter label=com.smartparking.testing.run="$RFID1_STAGE2_PROJECT_NAME" --format '{{.Name}}')" ]]; then
            echo "No se retiraron los recursos del fixture Stage 3 anterior." >&2
            exit 1
        fi
        verificar_estado_persistente
        preparar_stack
        verificar_estado_persistente
        echo "Fixture Stage 3 limpio, nuevamente listo en los puertos aislados ya asignados."
        ;;
    detener)
        cargar_estado
        limpiar_proyecto
        rm -f "$archivo_estado"
        rmdir "$directorio_estado" 2>/dev/null || true
        unset RFID1_STAGE2_DEVICE_TOKEN RFID1_STAGE2_TOKEN_SHA256
        unset RFID1_STAGE2_POSTGRES_PASSWORD RFID1_STAGE2_OWNER_PASSWORD
        unset RFID1_STAGE2_ADMIN_PASSWORD RFID1_STAGE2_CLIENT_PASSWORD TEST_DEVICE_TOKEN
        echo "Stack, volumen, red e imágenes de prueba retirados; infraestructura persistente coincide con su inventario inicial."
        ;;
    fisico)
        cargar_estado
        tipo="${2:-}"
        modo="${3:-ASOCIAR}"
        case "$tipo" in
            CLIENTE|EMPLEADO) ;;
            *)
                echo "Indica CLIENTE o EMPLEADO para el flujo físico." >&2
                exit 2
                ;;
        esac
        case "$modo" in
            ASOCIAR|RECHAZO_HISTORICO|CANCELAR_PREVIA) ;;
            *)
                echo "Modo físico no válido: usa ASOCIAR, RECHAZO_HISTORICO o CANCELAR_PREVIA." >&2
                exit 2
                ;;
        esac
        compose --profile browser run --rm -i \
            -v "$raiz/infra/podman/testing/tarjetas-rfid-stage3/flujo_fisico.mjs:/workspace/flujo_fisico.mjs:ro" \
            browser node /workspace/flujo_fisico.mjs "$tipo" "$modo"
        ;;
    *)
        cat >&2 <<'USO'
Uso:
  bash infra/podman/testing/tarjetas-rfid-stage3/ejecutar.sh iniciar
  bash infra/podman/testing/tarjetas-rfid-stage3/ejecutar.sh estado
  bash infra/podman/testing/tarjetas-rfid-stage3/ejecutar.sh reiniciar
  bash infra/podman/testing/tarjetas-rfid-stage3/ejecutar.sh fisico CLIENTE|EMPLEADO [ASOCIAR|RECHAZO_HISTORICO|CANCELAR_PREVIA]
  bash infra/podman/testing/tarjetas-rfid-stage3/ejecutar.sh detener

`iniciar` reutiliza Compose Stage 2, ejecuta únicamente BFF/Playwright enfocados y deja arriba el stack aislado.
`reiniciar` elimina solo el volumen desechable de esta ejecución y vuelve a crear las identidades sintéticas.
`fisico` abre el flujo Web DUENO, inicia una captura real y espera una lectura del puente temporal sin mostrar UID en consola.
`detener` retira solo los recursos identificados por el nombre aleatorio guardado en runtime.
USO
        exit 2
        ;;
esac
