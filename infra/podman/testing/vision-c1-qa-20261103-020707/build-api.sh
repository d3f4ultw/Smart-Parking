#!/usr/bin/env bash
set -euo pipefail

qa_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
env_file="$qa_dir/private/run.env"
if [[ ! -f "$env_file" ]]; then
  printf 'Falta private/run.env; ejecuta make-private-env.sh.\n' >&2
  exit 2
fi

qa_project="$(sed -n 's/^QA_PROJECT_NAME=//p' "$env_file")"
api_image="$(sed -n 's/^QA_API_IMAGE=//p' "$env_file")"
if [[ "$qa_project" != smartparking-vision-c1-qa-20261103-020707 || -z "$api_image" ]]; then
  printf 'El proyecto o la etiqueta API no coinciden con el stack aislado.\n' >&2
  exit 2
fi

podman build \
  --memory 2g \
  --memory-swap 2g \
  --label "com.smartparking.testing.run=$qa_project" \
  --label com.smartparking.testing.owner=luna-integracion \
  --tag "$api_image" \
  --file "$qa_dir/api-source/Containerfile" \
  "$qa_dir/api-source"
