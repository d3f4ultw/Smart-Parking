#!/usr/bin/env bash
set -euo pipefail

cd /workspace
cp -a /test-source/. /workspace/
if [[ "${QA_USE_LOOPBACK_WEB_PROXY:-false}" == true ]]; then
  export BASE_URL=http://127.0.0.1:3000
  export TEST_WEB_BASE_URL=http://127.0.0.1:3000
  WEB_PROXY_TARGET=http://web:3000 TEST_PROXY_PORT=3000 node /workspace/web-proxy.mjs \
    >/results/web-proxy.log 2>&1 &
  proxy_pid=$!
  trap 'kill "${proxy_pid}" 2>/dev/null || true; wait "${proxy_pid}" 2>/dev/null || true' EXIT
  proxy_ready=0
  for _ in {1..50}; do
    if node -e "fetch('http://127.0.0.1:3000/panel').then((r) => { r.body?.cancel(); process.exit(r.status === 200 ? 0 : 1) }).catch(() => process.exit(1))" \
      >/dev/null 2>&1; then
      proxy_ready=1
      break
    fi
    sleep 0.1
  done
  if [[ "$proxy_ready" != 1 ]]; then
    printf 'El proxy loopback de Web QA no quedó listo.\n' >&2
    exit 4
  fi
fi
if [[ ! -x /workspace/node_modules/.bin/playwright ]]; then
  printf 'Falta instalar @playwright/test dentro del volumen privado del runner.\n' >&2
  exit 3
fi

specs="$(printenv QA_PLAYWRIGHT_SPECS || printf 'vision-ocupacion.spec.ts')"
read -r -a argumentos <<<"$specs"
comando=(/workspace/node_modules/.bin/playwright test --config=/workspace/playwright.config.ts --output=/results/playwright-artifacts)
filtro="$(printenv QA_PLAYWRIGHT_GREP || true)"
if [[ -n "$filtro" ]]; then
  comando+=(--grep "$filtro")
fi
comando+=( "${argumentos[@]}" )
exec "${comando[@]}"
