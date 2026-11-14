#!/usr/bin/env bash
set -Eeuo pipefail

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$raiz"

proyecto="sp-operadores-http-local-20261026-105333-6cb9"
compose_file="infra/podman/testing/operadores-http-local/compose.yaml"
credencial_sql="infra/podman/testing/operadores-http-local/verificar-credencial.sql"
env_file=""
log_file=""
componer() {
  podman compose --project-name "$proyecto" --env-file "$env_file" -f "$compose_file" "$@"
}

prefijo="${proyecto}_"
if podman ps -aq --filter "label=com.smartparking.testing.run=${proyecto}" | rg -q .; then
  echo "Ya existen contenedores para el proyecto asignado; se cancela sin tocarlos." >&2
  exit 2
fi
if podman volume ls --format '{{.Name}}' | rg -q "^${prefijo}"; then
  echo "Ya existen volúmenes para el proyecto asignado; se cancela sin tocarlos." >&2
  exit 2
fi
if podman network ls --format '{{.Name}}' | rg -q "^${prefijo}"; then
  echo "Ya existen redes para el proyecto asignado; se cancela sin tocarlas." >&2
  exit 2
fi

env_file="$(mktemp "${TMPDIR:-/tmp}/${proyecto}.XXXXXX.env")"
log_file="$(mktemp "${TMPDIR:-/tmp}/${proyecto}.XXXXXX.log")"
chmod 600 "$env_file" "$log_file"

limpiar() {
  estado=$?
  trap - EXIT
  set +e
  if [[ -s "$env_file" ]]; then componer down --volumes --remove-orphans >/dev/null 2>&1; fi

  contenedores="$(podman ps -aq --filter "label=com.smartparking.testing.run=${proyecto}")"
  if [[ -n "$contenedores" ]]; then podman rm -f $contenedores >/dev/null 2>&1; fi

  while IFS= read -r recurso; do
    [[ -n "$recurso" ]] && podman volume rm "$recurso" >/dev/null 2>&1
  done < <(podman volume ls --format '{{.Name}}' | rg "^${prefijo}" || true)
  while IFS= read -r recurso; do
    [[ -n "$recurso" ]] && podman network rm "$recurso" >/dev/null 2>&1
  done < <(podman network ls --format '{{.Name}}' | rg "^${prefijo}" || true)

  imagenes="$(podman images -q --filter "label=com.smartparking.testing.run=${proyecto}" | sort -u)"
  if [[ -n "$imagenes" ]]; then podman rmi -f $imagenes >/dev/null 2>&1; fi
  rm -f "$env_file" "$log_file"

  if podman ps -aq --filter "label=com.smartparking.testing.run=${proyecto}" | rg -q . \
      || podman volume ls --format '{{.Name}}' | rg -q "^${prefijo}" \
      || podman network ls --format '{{.Name}}' | rg -q "^${prefijo}"; then
    echo "CLEANUP_INCOMPLETE: quedan recursos del proyecto ${proyecto}." >&2
    estado=1
  else
    echo "CLEANUP_PASS: contenedores, volúmenes, red, imagen local y datos temporales retirados."
  fi
  exit "$estado"
}
trap limpiar EXIT

sufijo="$(openssl rand -hex 5)"
contrasena_bd="$(openssl rand -hex 24)"
correo_dueno="dueno-${sufijo}@example.test"
contrasena_dueno="Dueno-${sufijo}-2026!"
contrasena_admin_dueno="Admin-${sufijo}-2026!"
correo_operador="operador-${sufijo}@example.test"
contrasena_inicial="Operador-${sufijo}-Inicial!"
contrasena_final="Operador-${sufijo}-Nueva!"
cat >"$env_file" <<EOF
TEST_PROJECT_NAME=${proyecto}
TEST_POSTGRES_DB=smartparking_http_local_test
TEST_POSTGRES_USER=operador_test
TEST_POSTGRES_PASSWORD=${contrasena_bd}
TEST_OWNER_EMAIL=${correo_dueno}
TEST_OWNER_PASSWORD=${contrasena_dueno}
TEST_OWNER_PASSWORD_ADMIN=${contrasena_admin_dueno}
TEST_OPERATOR_EMAIL=${correo_operador}
TEST_OPERATOR_PASSWORD_INITIAL=${contrasena_inicial}
TEST_OPERATOR_PASSWORD_FINAL=${contrasena_final}
EOF

componer config >/dev/null
componer up -d db mailpit api web

for intento in $(seq 1 120); do
  if componer exec -T web node -e '
    (async()=>{for(let i=0;i<2;i++){try{const r=await fetch("http://api:8080/actuator/health");if(r.ok)process.exit(0)}catch{}await new Promise(r=>setTimeout(r,500))}process.exit(1)})()
  ' >/dev/null 2>&1; then
    break
  fi
  if [[ "$intento" -eq 120 ]]; then
    echo "API_NOT_READY: la API aislada no alcanzó el estado disponible." >&2
    exit 1
  fi
  sleep 2
done

versiones="$(componer exec -T db sh -lc 'psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT string_agg(version || chr(58) || success::text, chr(44) ORDER BY version::integer) FROM flyway_schema_history WHERE success"')"
if [[ "$versiones" != "1:true,2:true,3:true,4:true,5:true,6:true,7:true" ]]; then
  echo "FLYWAY_FAIL: migraciones V1–V7 no confirmadas en la base aislada." >&2
  exit 1
fi
echo "FLYWAY_PASS: ${versiones}"

web_listo=0
for intento in $(seq 1 120); do
  if componer exec -T web node -e '
    (async()=>{try{const r=await fetch("http://localhost:3000/panel");process.exit(r.ok?0:1)}catch{process.exit(1)}})()
  ' >/dev/null 2>&1; then
    web_listo=1
    break
  fi
  sleep 2
done
if [[ "$web_listo" -ne 1 ]]; then
  echo "WEB_NOT_READY: Nuxt no respondió dentro del espacio de red de prueba." >&2
  exit 1
fi

if ! componer --profile browser run --rm browser-http-local >"$log_file" 2>&1; then
  sed -E 's/[A-Za-z0-9_-]{43}/[token redactado]/g' "$log_file" | tail -n 90 >&2
  exit 1
fi
rg '1 passed|passed \(.*\)' "$log_file" | tail -n 1

hash_versionado="$(componer exec -T db sh -lc 'psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <"$credencial_sql")"
if [[ "$hash_versionado" != "t" ]]; then
  echo "PASSWORD_HASH_FAIL: no se persistió el formato PBKDF2 configurado para la cuenta." >&2
  exit 1
fi
echo "PASSWORD_FORMAT_PASS: hash PBKDF2 versionado y sin contraseña en claro tras completar recuperación."

mensajes="$(componer exec -T web node -e '
  fetch("http://mailpit:8025/api/v1/messages?limit=100").then(async r=>{if(!r.ok)process.exit(1);const j=await r.json();console.log(j.messages?.length ?? 0)}).catch(()=>process.exit(1))
' | tail -n 1)"
if [[ "$mensajes" != "3" ]]; then
  echo "MAILPIT_FAIL: se esperaban una bienvenida sintética y un mensaje por cada enlace." >&2
  exit 1
fi
echo "MAILPIT_PASS: bienvenida sintética, invitación y recuperación recibidas por SMTP aislado."

api_migraciones="$(componer logs --no-color --tail 300 api | rg -c 'Successfully applied 7 migrations' || true)"
if [[ "$api_migraciones" -lt 1 ]]; then
  echo "FLYWAY_LOG_FAIL: no se encontró confirmación de Flyway V1–V7 en el log API." >&2
  exit 1
fi
echo "API_LOG_PASS: el arranque confirmó Flyway V1–V7; API y SMTP apuntaron a la red temporal."
