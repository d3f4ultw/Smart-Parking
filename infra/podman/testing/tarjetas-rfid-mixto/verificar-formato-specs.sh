#!/usr/bin/env bash
set -euo pipefail
umask 077

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$raiz"

compose_file="infra/podman/testing/tarjetas-rfid-stage2/compose.yaml"
proyecto="smartparking-rfid-mixto-formato-$(tr -d '-' < /proc/sys/kernel/random/uuid | cut -c1-12)"
run_id="$(tr -d '-' < /proc/sys/kernel/random/uuid)"

unset POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
unset NUXT_API_INTERNAL_BASE TEST_OWNER_EMAIL TEST_OWNER_PASSWORD TEST_CLIENT_EMAIL
unset TEST_CLIENT_PASSWORD TEST_DEVICE_TOKEN TEST_API_BASE_URL TEST_WEB_BASE_URL

export RFID1_STAGE2_PROJECT_NAME="$proyecto"
export RFID1_STAGE2_POSTGRES_DB="smartparking_rfid1_stage2"
export RFID1_STAGE2_POSTGRES_USER="smartparking_rfid1_stage2"
export RFID1_STAGE2_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export RFID1_STAGE2_DEVICE_TOKEN="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
export RFID1_STAGE2_TOKEN_SHA256
RFID1_STAGE2_TOKEN_SHA256="$(printf '%s' "$RFID1_STAGE2_DEVICE_TOKEN" | sha256sum | cut -d ' ' -f1)"
export RFID1_STAGE2_OWNER_EMAIL="dueno-rfid-formato-$run_id@example.invalid"
export RFID1_STAGE2_OWNER_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
export RFID1_STAGE2_ADMIN_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
export RFID1_STAGE2_CLIENT_EMAIL="cliente-rfid-formato-$run_id@example.invalid"
export RFID1_STAGE2_CLIENT_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
export TEST_OWNER_EMAIL="$RFID1_STAGE2_OWNER_EMAIL"
export TEST_OWNER_PASSWORD="$RFID1_STAGE2_OWNER_PASSWORD"
export TEST_CLIENT_EMAIL="$RFID1_STAGE2_CLIENT_EMAIL"
export TEST_CLIENT_PASSWORD="$RFID1_STAGE2_CLIENT_PASSWORD"
export TEST_DEVICE_TOKEN="$RFID1_STAGE2_DEVICE_TOKEN"

limpiar() {
    podman compose --project-name "$proyecto" -f "$compose_file" down --volumes --remove-orphans \
        >/dev/null 2>&1 || true
    podman image rm "localhost/$proyecto-web-checks:stage2" >/dev/null 2>&1 || true
}
trap limpiar EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

podman compose --project-name "$proyecto" -f "$compose_file" config --quiet
podman compose --project-name "$proyecto" -f "$compose_file" --profile checks build web_checks
podman compose --project-name "$proyecto" -f "$compose_file" --profile checks run --rm web_checks \
    pnpm exec vp fmt -c tooling/vite.config.ts \
    tests/browser/tarjetas-rfid/07-mixto.spec.ts \
    tests/browser/tarjetas-rfid/08-conexion-rfid1.spec.ts --check

limpiar
trap - EXIT INT TERM

contenedores_restantes="$(podman ps -a --filter label=com.smartparking.testing.run="$proyecto" --format '{{.ID}}')" || exit 1
volumenes_restantes="$(podman volume ls --filter label=com.smartparking.testing.run="$proyecto" --format '{{.Name}}')" || exit 1
redes_restantes="$(podman network ls --filter label=com.smartparking.testing.run="$proyecto" --format '{{.Name}}')" || exit 1
imagenes_restantes="$(podman images --format '{{.Repository}}:{{.Tag}}')" || exit 1

if [[ -n "$contenedores_restantes" || -n "$volumenes_restantes" || -n "$redes_restantes" ]] \
    || printf '%s\n' "$imagenes_restantes" | rg -Fxq "localhost/$proyecto-web-checks:stage2"; then
    echo "La limpieza del formato dejó recursos desechables." >&2
    exit 1
fi

unset RFID1_STAGE2_DEVICE_TOKEN RFID1_STAGE2_TOKEN_SHA256 RFID1_STAGE2_POSTGRES_PASSWORD
unset RFID1_STAGE2_OWNER_PASSWORD RFID1_STAGE2_ADMIN_PASSWORD RFID1_STAGE2_CLIENT_PASSWORD
unset TEST_DEVICE_TOKEN TEST_OWNER_PASSWORD TEST_CLIENT_PASSWORD

echo "PASS: formato de los specs MIXTO y conexión RFID1 verificado; recursos temporales retirados."
