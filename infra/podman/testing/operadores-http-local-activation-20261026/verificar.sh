#!/usr/bin/env bash
set -Eeuo pipefail

API_CONTENEDOR="${API_CONTENEDOR:-smartparking-api-1}"
BD_CONTENEDOR="${BD_CONTENEDOR:-smartparking-db-1}"
BASE_WEB="${BASE_WEB:-http://localhost:3000}"
BASE_API="${BASE_API:-http://localhost:8080}"
BASE_MAILPIT="${BASE_MAILPIT:-http://localhost:8025}"

fallar() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

pasar() {
  printf 'PASS: %s\n' "$1"
}

codigo_http() {
  local metodo="$1"
  local url="$2"
  shift 2
  curl --silent --show-error --max-time 8 --output /dev/null \
    --write-out '%{http_code}' --request "$metodo" "$@" "$url"
}

api_env() {
  local clave="$1"
  podman inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$API_CONTENEDOR" \
    | awk -F= -v clave="$clave" '
        $1 == clave {
          print substr($0, index($0, "=") + 1)
          encontrados++
        }
        END { if (encontrados != 1) exit 1 }
      '
}

exigir_env() {
  local clave="$1"
  local esperado="$2"
  local obtenido
  if ! obtenido="$(api_env "$clave")"; then
    fallar "no se pudo leer exactamente una variable permitida: $clave"
  fi
  if [[ "$obtenido" != "$esperado" ]]; then
    fallar "$clave no coincide con el valor local esperado"
  fi
  printf 'PASS: config %s=%s\n' "$clave" "$esperado"
}

command -v podman >/dev/null || fallar 'Podman no está disponible'
command -v curl >/dev/null || fallar 'curl no está disponible'

# Lee exclusivamente nombres de variables aprobados; nunca muestra el entorno completo.
exigir_env SPRING_PROFILE local
exigir_env OPERADORES_ORIGEN_ACTIVACION http://localhost:3000
exigir_env OPERADORES_PERMITIR_HTTP_LOCAL true
exigir_env SMTP_ENABLED true
exigir_env SMTP_HOST mailpit
exigir_env SMTP_PORT 1025
exigir_env SESSION_TIMEOUT 30m
exigir_env SESSION_COOKIE_SECURE false
exigir_env POSTGRES_HOST db
exigir_env POSTGRES_PORT 5432

estado_api="$(curl --silent --show-error --max-time 8 "$BASE_API/actuator/health")" \
  || fallar 'el endpoint de salud de API no respondió'
if [[ "$estado_api" != *'"status":"UP"'* && "$estado_api" != *'"status": "UP"'* ]]; then
  fallar 'el estado de salud de API no es UP'
fi
pasar 'API health UP'

estado_flyway="$(podman exec "$BD_CONTENEDOR" sh -lc \
  'psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT (count(*) = 7 AND bool_and(success) AND min(version::integer) = 1 AND max(version::integer) = 7)::text FROM flyway_schema_history"')" \
  || fallar 'no se pudo consultar el historial Flyway de forma read-only'
[[ "$estado_flyway" == true ]] || fallar 'Flyway no tiene exactamente V1–V7 exitosas'
pasar 'Flyway V1–V7 exitosas; solo lectura'

estado_web="$(codigo_http GET "$BASE_WEB/")" || fallar 'Web no respondió en localhost:3000'
case "$estado_web" in
  200|301|302|303|307|308) pasar "Web disponible en localhost:3000 (HTTP $estado_web)" ;;
  *) fallar "Web devolvió HTTP $estado_web en localhost:3000" ;;
esac

estado_admin="$(codigo_http GET "$BASE_WEB/admin/operadores")" \
  || fallar 'la ruta protegida de operadores no respondió'
[[ "$estado_admin" == 302 ]] \
  || fallar "la ruta DUENO de operadores debía redirigir (HTTP 302), recibió $estado_admin"
pasar 'admin/operadores continúa protegido para una sesión anónima (HTTP 302)'

estado_csrf_get="$(codigo_http GET "$BASE_API/api/v1/csrf")" \
  || fallar 'el endpoint CSRF no respondió'
[[ "$estado_csrf_get" == 200 ]] || fallar "GET CSRF devolvió HTTP $estado_csrf_get"
pasar 'GET /api/v1/csrf responde HTTP 200'

# Token deliberadamente inválido: sin CSRF, el filtro debe rechazar el POST antes del controlador.
# Si el filtro faltara, la validación solo podría fallar por token inválido y no crea ni cambia cuentas.
estado_csrf_post="$(codigo_http POST "$BASE_API/api/v1/operadores/activacion/validar" \
  --header 'Content-Type: application/json' --data '{"token":"invalid"}')" \
  || fallar 'la comprobación CSRF no respondió'
[[ "$estado_csrf_post" == 403 ]] \
  || fallar "POST sin X-CSRF-TOKEN debía devolver HTTP 403, recibió $estado_csrf_post"
pasar 'CSRF rechaza POST sin X-CSRF-TOKEN (HTTP 403; sin cuenta ni correo)'

estado_mailpit="$(codigo_http GET "$BASE_MAILPIT/")" \
  || fallar 'Mailpit local no respondió'
[[ "$estado_mailpit" == 200 ]] || fallar "Mailpit local devolvió HTTP $estado_mailpit"
pasar 'Mailpit está disponible en su UI local (HTTP 200)'

printf 'SMOKE_READ_ONLY_PASS\n'
