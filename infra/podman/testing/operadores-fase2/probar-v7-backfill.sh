#!/usr/bin/env bash
set -euo pipefail

: "${TEST_ENV_FILE:?Define TEST_ENV_FILE fuera del repositorio}"
: "${TEST_PROJECT_NAME:?Exporta el nombre único del proyecto desechable}"
: "${TEST_API_V6_IMAGE:?Define una imagen local existente de la API V6}"
[[ -r "$TEST_ENV_FILE" ]] || { echo 'No se puede leer TEST_ENV_FILE.' >&2; exit 2; }
if [[ ! "$TEST_PROJECT_NAME" =~ ^smartparking-operadores-fase2-[a-z0-9][a-z0-9_-]{7,}$ ]]; then
  echo 'TEST_PROJECT_NAME requiere el prefijo del proyecto y un sufijo único de al menos 8 caracteres.' >&2
  exit 2
fi

raiz_repositorio="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../" && pwd)"
compose=(
  podman compose
  --project-name "$TEST_PROJECT_NAME"
  --env-file "$TEST_ENV_FILE"
  -f "$raiz_repositorio/infra/podman/testing/compose.yaml"
  -f "$raiz_repositorio/infra/podman/testing/operadores-fase2/compose.yaml"
)

contenedores="$(podman ps --all --quiet --filter "label=com.smartparking.testing.run=$TEST_PROJECT_NAME")"
volumenes="$(podman volume ls --quiet --filter "label=com.docker.compose.project=$TEST_PROJECT_NAME")"
redes="$(podman network ls --quiet --filter "label=com.docker.compose.project=$TEST_PROJECT_NAME")"
if [[ -n "$contenedores$volumenes$redes" ]]; then
  echo 'El proyecto ya contiene recursos; usa un TEST_PROJECT_NAME nuevo.' >&2
  exit 3
fi

limpiar_proyecto() {
  local estado_salida=$?
  trap - EXIT
  if ! "${compose[@]}" --profile v6-bootstrap --profile backfill-replay down --volumes --remove-orphans; then
    echo "No se pudo retirar por completo el proyecto desechable $TEST_PROJECT_NAME." >&2
    if [[ "$estado_salida" -eq 0 ]]; then
      estado_salida=1
    fi
  fi
  exit "$estado_salida"
}
trap limpiar_proyecto EXIT

consulta_version="SELECT COALESCE((SELECT version FROM flyway_schema_history WHERE success ORDER BY installed_rank DESC LIMIT 1), '0');"
consulta_checksums="SELECT string_agg(version || ':' || checksum::text || ':' || success::text, ',' ORDER BY installed_rank) FROM flyway_schema_history WHERE version ~ '^[1-6]$';"
esperar_version() {
  local esperada="$1"
  local actual=''
  for intento in {1..180}; do
    if actual="$("${compose[@]}" exec -T db sh -lc \
      'psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' sh "$consulta_version" 2>/dev/null)" \
      && [[ "$actual" == "$esperada" ]]; then
      return 0
    fi
    sleep 1
  done
  echo "Flyway no llegó a V$esperada en la base desechable." >&2
  return 1
}

psql_contenedor=(sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"')
"${compose[@]}" --profile v6-bootstrap up -d db mailpit api-v6
esperar_version 6
checksums_v6="$("${compose[@]}" exec -T db sh -lc \
  'psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' sh "$consulta_checksums")"
"${compose[@]}" exec -T db "${psql_contenedor[@]}" \
  < "$raiz_repositorio/infra/podman/testing/operadores-fase2/fixture-v6-operadores.sql"
"${compose[@]}" stop api-v6
"${compose[@]}" up -d api
esperar_version 7
checksums_v7="$("${compose[@]}" exec -T db sh -lc \
  'psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' sh "$consulta_checksums")"
if [[ "$checksums_v6" != "$checksums_v7" ]]; then
  echo 'V7 cambió checksums o estados de Flyway para V1–V6.' >&2
  exit 4
fi
"${compose[@]}" exec -T db "${psql_contenedor[@]}" \
  < "$raiz_repositorio/infra/podman/testing/operadores-fase2/verificar-v7-backfill.sql"
"${compose[@]}" --profile backfill-replay run --rm api-acceptance-v6-backfill
echo "V7_BACKFILL_OK; checksums V1–V6 preservados en $TEST_PROJECT_NAME."
