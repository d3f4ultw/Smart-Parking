#!/usr/bin/env bash
set -euo pipefail
umask 077

qa_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project="smartparking-vision-c1-pressure-20261103-095735"
env_file="$qa_dir/private/run.env"
compose=(podman compose -p "$project" --env-file "$env_file" -f "$qa_dir/compose.yaml")

esperar_marca() {
  local nombre="$1" limite="${2:-90}" inicio="$SECONDS"
  while (( SECONDS - inicio < limite )); do
    [[ -f "$qa_dir/results/$nombre" ]] && return 0
    sleep 0.2
  done
  printf 'timeout esperando marca de control: %s\n' "$nombre" >&2
  return 1
}

crear_marca() {
  local nombre="$1" contenido="$2"
  printf '%s\n' "$contenido" >"$qa_dir/results/$nombre"
  chmod 600 "$qa_dir/results/$nombre"
}

esperar_marca load-v2-started.json
python3 "$qa_dir/stats-qa.py" durante-carga >"$qa_dir/private/stats-load-v2.log" 2>&1
esperar_marca ready-open-v2.json
python3 "$qa_dir/stats-qa.py" antes-sigterm-con-sse >"$qa_dir/private/stats-open-v2-before.log" 2>&1
set +e
python3 "$qa_dir/term-api.py" con-sse-v2 30 >"$qa_dir/private/api-term-open-v2.json" 2>&1
codigo=$?
set -e
crear_marca open-term-finished-v2.json "exit=$codigo"
if [[ "$codigo" == 0 ]]; then
  if "${compose[@]}" up --no-build --no-deps --detach api >"$qa_dir/private/api-restart-open-v2.log" 2>&1 && \
    podman exec "${project}-vision-counter-1" node /qa/wait-ready.mjs api >"$qa_dir/private/api-health-open-v2.log" 2>&1; then
    crear_marca api-restarted-v2.json 'health=200'
  else
    crear_marca api-restart-failed-v2.json 'health=not-confirmed'
  fi
else
  crear_marca api-restart-skipped-v2.json "termExit=$codigo"
fi
if ! esperar_marca open-case-observed-v2.json 60; then
  esperar_marca closed-case-skipped-v2.json 3 || true
  exit 1
fi
if [[ "$codigo" != 0 ]]; then
  exit 124
fi
if [[ -f "$qa_dir/results/api-restart-failed-v2.json" ]]; then
  esperar_marca closed-case-skipped-v2.json 10 || true
  exit 1
fi

esperar_marca ready-closed-v2.json
python3 "$qa_dir/stats-qa.py" antes-sigterm-sin-sse >"$qa_dir/private/stats-closed-v2-before.log" 2>&1
set +e
python3 "$qa_dir/term-api.py" sin-sse-v2 30 >"$qa_dir/private/api-term-closed-v2.json" 2>&1
codigo=$?
set -e
crear_marca closed-term-finished-v2.json "exit=$codigo"
if [[ "$codigo" == 0 ]]; then
  if "${compose[@]}" up --no-build --no-deps --detach api >"$qa_dir/private/api-restart-closed-v2.log" 2>&1 && \
    podman exec "${project}-vision-counter-1" node /qa/wait-ready.mjs api >"$qa_dir/private/api-health-closed-v2.log" 2>&1; then
    crear_marca api-recovered-final-v2.json 'health=200'
  else
    crear_marca api-recovery-final-failed-v2.json 'health=not-confirmed'
  fi
fi
python3 "$qa_dir/stats-qa.py" final >"$qa_dir/private/stats-final-v2.log" 2>&1
if [[ "$codigo" != 0 ]]; then exit 124; fi
