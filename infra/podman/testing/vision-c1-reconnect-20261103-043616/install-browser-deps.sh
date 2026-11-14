#!/usr/bin/env bash
set -euo pipefail
umask 077

qa_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project="smartparking-vision-c1-reconnect-20261103-043616"
image="c02c00ca3e255f44c470983130755c0174261817de240ed812bd4706caa30f8e"
workspace="${project}_browser_workspace"
store="${project}_browser_pnpm_store"

for volume in "$workspace" "$store"; do
  if ! podman volume exists "$volume"; then
    podman volume create --label "com.smartparking.testing.run=$project" \
      --label "com.smartparking.testing.owner=luna-integracion" "$volume" >/dev/null
  fi
done

podman run --rm --name "${project}-deps" \
  --label "com.smartparking.testing.run=$project" \
  --label "com.smartparking.testing.owner=luna-integracion" \
  --network none --memory 512m --memory-swap 512m \
  --volume "$qa_dir/web-source/tests/browser:/test-source:ro,Z" \
  --volume "$workspace:/qa-workspace:Z" \
  --entrypoint /bin/bash "$image" -lc \
  'set -euo pipefail; cmp /workspace/package.json /test-source/package.json; cmp /workspace/pnpm-lock.yaml /test-source/pnpm-lock.yaml; mkdir -p /qa-workspace; cp -a /workspace/node_modules /qa-workspace/; cp -a /test-source/. /qa-workspace/; ln -sfn .pnpm/playwright@1.64.1/node_modules/playwright /qa-workspace/node_modules/playwright; node -e "const a=require(\"/qa-workspace/node_modules/@playwright/test/package.json\"); const p=require(\"/qa-workspace/node_modules/playwright/package.json\"); const c=require(\"/qa-workspace/node_modules/.pnpm/playwright-core@1.64.1/node_modules/playwright-core/package.json\"); if (a.version!==\"1.64.1\" || p.version!==\"1.64.1\" || c.version!==\"1.64.1\") process.exit(4); console.log(\"Playwright lock/version verified: 1.64.1\")"; /qa-workspace/node_modules/.bin/playwright --version' \
  >"$qa_dir/private/browser-deps.log" 2>&1
printf 'Playwright QA deps listas; versión y lock verificados en Podman.\n'
