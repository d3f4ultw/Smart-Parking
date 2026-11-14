#!/usr/bin/env bash
set -euo pipefail
umask 077

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
proyecto="smartparking-vision-c1-qa-20261103-020707"
imagen="c02c00ca3e255f44c470983130755c0174261817de240ed812bd4706caa30f8e"
volumen_workspace="${proyecto}_browser_workspace"
volumen_store="${proyecto}_browser_pnpm_store"
registro="$raiz/private/browser-deps.log"
estado="$raiz/private/browser-deps.exit"

for volumen in "$volumen_workspace" "$volumen_store"; do
  if ! podman volume exists "$volumen"; then
    podman volume create \
      --label "com.smartparking.testing.run=$proyecto" \
      --label "com.smartparking.testing.owner=luna-integracion" \
      "$volumen" >/dev/null
  fi
done

set +e
podman run --rm \
  --name "${proyecto}-deps" \
  --label "com.smartparking.testing.run=$proyecto" \
  --label "com.smartparking.testing.owner=luna-integracion" \
  --network none \
  --memory 512m \
  --memory-swap 512m \
  --volume "$raiz/web-source/tests/browser:/test-source:ro,Z" \
  --volume "$volumen_workspace:/qa-workspace:Z" \
  --entrypoint /bin/bash \
  "$imagen" -lc 'set -euo pipefail; cmp /workspace/package.json /test-source/package.json; cmp /workspace/pnpm-lock.yaml /test-source/pnpm-lock.yaml; mkdir -p /qa-workspace; cp -a /workspace/node_modules /qa-workspace/; cp -a /test-source/. /qa-workspace/; ln -sfn .pnpm/playwright@1.64.1/node_modules/playwright /qa-workspace/node_modules/playwright; node -e "const a=require(\"/qa-workspace/node_modules/@playwright/test/package.json\"); const p=require(\"/qa-workspace/node_modules/playwright/package.json\"); const c=require(\"/qa-workspace/node_modules/.pnpm/playwright-core@1.64.1/node_modules/playwright-core/package.json\"); if (a.version!==\"1.64.1\" || p.version!==\"1.64.1\" || c.version!==\"1.64.1\") process.exit(4); console.log(\"Playwright lock/version verified: 1.64.1\")"; /qa-workspace/node_modules/.bin/playwright --version' \
  >"$registro" 2>&1
codigo=$?
set -e
printf '%s\n' "$codigo" >"$estado"
exit "$codigo"
