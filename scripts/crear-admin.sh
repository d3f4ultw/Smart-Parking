#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
ENV_FILE="${PROJECT_ROOT}/.env"
COMPOSE_FILE="${PROJECT_ROOT}/infra/compose.dev.yml"

unset POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD DATABASE_URL \
    DATABASE_HOST DATABASE_PORT DATABASE_NAME DATABASE_USER DATABASE_PASSWORD \
    APP_ENVIRONMENT APP_PUBLIC_URL SESSION_COOKIE_NAME SESSION_DURATION_MINUTES \
    ACTIVACION_REENVIO_COOLDOWN_SEGUNDOS CORREO_TRANSPORTE SMTP_HOST SMTP_PORT \
    SMTP_USERNAME SMTP_PASSWORD SMTP_FROM_EMAIL SMTP_FROM_NAME SMTP_SECURITY \
    SMTP_TIMEOUT_SECONDS NUXT_API_INTERNAL_BASE_URL

if command -v podman >/dev/null 2>&1; then
    PODMAN=(podman)
elif command -v podman.exe >/dev/null 2>&1; then
    PODMAN=(podman.exe)
else
    printf 'Error: Podman no esta disponible en PATH.\n' >&2
    exit 127
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
    printf 'Error: no se encontro infra/compose.dev.yml en el proyecto.\n' >&2
    exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
    printf 'Error: no se encontro .env en la raiz del proyecto; copia .env.example.\n' >&2
    exit 1
fi

if ! "${PODMAN[@]}" version >/dev/null 2>&1; then
    printf 'Error: Podman no puede conectarse al motor local.\n' >&2
    exit 125
fi

if ! "${PODMAN[@]}" compose version >/dev/null 2>&1; then
    if [[ "${PODMAN[0]}" != 'podman.exe' ]] \
        && command -v podman.exe >/dev/null 2>&1 \
        && podman.exe version >/dev/null 2>&1 \
        && podman.exe compose version >/dev/null 2>&1; then
        PODMAN=(podman.exe)
    else
        printf 'Error: no hay un proveedor Compose disponible para Podman.\n' >&2
        exit 126
    fi
fi

COMPOSE_FILE_ARGUMENT="${COMPOSE_FILE}"
ENV_FILE_ARGUMENT="${ENV_FILE}"
PROJECT_ROOT_ARGUMENT="${PROJECT_ROOT}"
if [[ "${PODMAN[0]}" == 'podman.exe' ]]; then
    if command -v wslpath >/dev/null 2>&1; then
        COMPOSE_FILE_ARGUMENT="$(wslpath -w "${COMPOSE_FILE}")"
        ENV_FILE_ARGUMENT="$(wslpath -w "${ENV_FILE}")"
        PROJECT_ROOT_ARGUMENT="$(wslpath -w "${PROJECT_ROOT}")"
    elif command -v cygpath >/dev/null 2>&1; then
        COMPOSE_FILE_ARGUMENT="$(cygpath -w "${COMPOSE_FILE}")"
        ENV_FILE_ARGUMENT="$(cygpath -w "${ENV_FILE}")"
        PROJECT_ROOT_ARGUMENT="$(cygpath -w "${PROJECT_ROOT}")"
    else
        printf 'Error: no se puede convertir la ruta para Podman Windows.\n' >&2
        exit 1
    fi
fi

COMPOSE=(
    "${PODMAN[@]}" compose
    --env-file "${ENV_FILE_ARGUMENT}"
    --project-directory "${PROJECT_ROOT_ARGUMENT}"
    -f "${COMPOSE_FILE_ARGUMENT}"
)

printf 'Preparando Smart Parking...\n'
"${COMPOSE[@]}" up --detach --wait --wait-timeout 60 postgres api-dev

printf 'postgres/api-dev disponibles.\n'
printf 'Abriendo la creacion interactiva de ADMIN...\n'
exec "${COMPOSE[@]}" exec api-dev uv run python -m app.cli.crear_admin
