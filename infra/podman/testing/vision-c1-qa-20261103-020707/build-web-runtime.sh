#!/usr/bin/env bash
set -euo pipefail

qa_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
env_file="$qa_dir/private/run.env"
if [[ ! -f "$env_file" ]]; then
  printf 'Falta private/run.env; ejecuta make-private-env.sh.\n' >&2
  exit 2
fi

qa_project="$(sed -n 's/^QA_PROJECT_NAME=//p' "$env_file")"
web_image="$(sed -n 's/^QA_WEB_IMAGE=//p' "$env_file")"
if [[ "$qa_project" != smartparking-vision-c1-qa-20261103-020707 || -z "$web_image" ]]; then
  printf 'El proyecto o la etiqueta Web no coinciden con el stack aislado.\n' >&2
  exit 2
fi

podman build \
  --memory 768m \
  --memory-swap 768m \
  --label "com.smartparking.testing.run=$qa_project" \
  --label com.smartparking.testing.owner=luna-integracion \
  --tag "$web_image" \
  --file "$qa_dir/web-runtime-context/Containerfile" \
  "$qa_dir/web-runtime-context"
