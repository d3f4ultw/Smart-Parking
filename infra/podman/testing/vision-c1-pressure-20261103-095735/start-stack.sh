#!/usr/bin/env bash
set -euo pipefail
umask 077

qa_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project="smartparking-vision-c1-pressure-20261103-095735"
env_file="$qa_dir/private/run.env"
compose=(podman compose -p "$project" --env-file "$env_file" -f "$qa_dir/compose.yaml")

"${compose[@]}" up --no-build --detach db mailpit api vision-counter web >"$qa_dir/private/stack-up.log" 2>&1
podman exec "${project}-vision-counter-1" node /qa/wait-ready.mjs api >"$qa_dir/private/api-ready.log" 2>&1
"${compose[@]}" --profile browser up --no-build --detach vision-fixture vision-fixture-db >"$qa_dir/private/fixtures-up.log" 2>&1
"${compose[@]}" --profile browser run --rm --no-deps bootstrap >"$qa_dir/private/bootstrap.log" 2>&1
podman exec "${project}-vision-counter-1" node /qa/wait-ready.mjs web >"$qa_dir/private/web-ready.log" 2>&1
printf 'Stack QA preparado; credenciales y tokens no se imprimieron.\n'
