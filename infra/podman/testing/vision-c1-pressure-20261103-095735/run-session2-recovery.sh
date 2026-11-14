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
  printf 'timeout esperando marca: %s\n' "$nombre" >&2
  return 1
}

crear_marca() {
  local nombre="$1" contenido="$2"
  printf '%s\n' "$contenido" >"$qa_dir/results/$nombre"
  chmod 600 "$qa_dir/results/$nombre"
}

esperar_marca session2-ready-open.json
python3 "$qa_dir/stats-qa.py" antes-restart-sesion-focal >"$qa_dir/private/stats-session2-before.log" 2>&1
set +e
python3 "$qa_dir/term-api.py" diagnostico-sesion-focal 30 >"$qa_dir/private/api-term-session2.json" 2>&1
codigo=$?
set -e
crear_marca session2-term-finished.json "exit=$codigo"
if [[ "$codigo" == 0 ]]; then
  if "${compose[@]}" up --no-build --no-deps --detach api >"$qa_dir/private/api-restart-session2.log" 2>&1 && \
    podman exec "${project}-vision-counter-1" node /qa/wait-ready.mjs api >"$qa_dir/private/api-health-session2.log" 2>&1; then
    crear_marca session2-api-restarted.json 'health=200'
  else
    crear_marca session2-api-restart-failed.json 'health=not-confirmed'
  fi
else
  crear_marca session2-api-restart-skipped.json "termExit=$codigo"
fi
python3 "$qa_dir/stats-qa.py" post-restart-sesion-focal >"$qa_dir/private/stats-session2-after.log" 2>&1
