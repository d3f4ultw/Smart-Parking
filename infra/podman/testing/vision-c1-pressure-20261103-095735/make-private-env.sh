#!/usr/bin/env bash
set -euo pipefail

qa_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
env_file="$qa_dir/private/run.env"
project="smartparking-vision-c1-pressure-20261103-095735"

if [[ -e "$env_file" ]]; then
  printf 'El env privado ya existe; no se reemplaza.\n' >&2
  exit 2
fi
command -v openssl >/dev/null
mkdir -p "$qa_dir/private"
chmod 700 "$qa_dir/private"

postgres_password="$(openssl rand -hex 32)"
owner_password="$(openssl rand -hex 24)"
admin_password="$(openssl rand -hex 24)"
vision_token="$(openssl rand -hex 32)"
vision_token_hash="$(printf '%s' "$vision_token" | sha256sum | cut -d ' ' -f 1)"
vision_source_id="$(cat /proc/sys/kernel/random/uuid)"

cat >"$env_file" <<ENV
QA_PROJECT_NAME=$project
QA_POSTGRES_DB=smartparking_vision_pressure_qa
QA_POSTGRES_USER=sp_vision_pressure_qa
QA_POSTGRES_PASSWORD=$postgres_password
QA_OWNER_EMAIL=dueno-pressure-20261103@example.test
QA_OWNER_PASSWORD=$owner_password
QA_ADMIN_PASSWORD=$admin_password
QA_VISION_TOKEN=$vision_token
QA_VISION_TOKEN_SHA256=$vision_token_hash
QA_VISION_SOURCE_ID=$vision_source_id
QA_SESSION_TIMEOUT=15m
QA_API_IMAGE=localhost/smartparking-vision-c1-qa-api:20261103-020707
QA_WEB_IMAGE=localhost/smartparking-vision-c1-qa-web:20261103-c1fixed
ENV
chmod 600 "$env_file"
printf 'Env sintético creado en private/run.env con permisos 0600; valores omitidos.\n'
