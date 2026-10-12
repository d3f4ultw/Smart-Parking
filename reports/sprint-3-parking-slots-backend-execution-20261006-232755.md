# Sprint 3 Parking Slots Backend Foundation — Execution Report

- **Project:** Smart Parking
- **Sprint:** 3
- **Execution date:** 2026-10-06 (America/Mexico_City)
- **Approved plan:** `reports/sprint-3-parking-slots-backend-plan-20261006-222919.md`
- **Final verdict:** `IMPLEMENTED — READY WITH CAVEATS`

## Result

Implemented the backend-owned parking-slot foundation for an arbitrary number of persisted slots. The implementation keeps physical sensor state separate from staff-controlled operational state and derives effective state on reads and in durable event snapshots.

The canonical migration was applied to the local development database. It advanced the database from `20261004_0001` to repository head `20261006_0001`. PostgreSQL and its existing `postgres_data` volume were preserved; neither was recreated or reset.

## Schema and initial data

Revision `20261006_0001` creates `cajones` with:

- Identity primary key, positive unique `numero`, checked physical and operational state values, and an operational reason bounded to 250 characters.
- Timezone-aware timestamps for physical updates, operational updates, and creation.
- Initial defaults of `DESCONOCIDO` physical state, `DISPONIBLE` operational state, null reason, null initial physical timestamp, and database creation time.
- No redundant availability boolean.

The migration inserted exactly eight deterministic rows numbered 1 through 8. Immediately after migration, all eight were verified as `DESCONOCIDO / DISPONIBLE / DESCONOCIDO`; no sensor state was fabricated.

Effective state is derived with this precedence:

1. `MANTENIMIENTO` or `FUERA_DE_SERVICIO` → `NO_DISPONIBLE`.
2. `DISPONIBLE` plus physical `OCUPADO` → `OCUPADO`.
3. `DISPONIBLE` plus physical `LIBRE` → `LIBRE`.
4. `DISPONIBLE` plus physical `DESCONOCIDO` → `DESCONOCIDO`.

The event journal now stores the cajon snapshot in a nullable JSONB `datos` field. Its constraints continue to accept legacy operator events with null data and require data for `cajon.actualizado`. The downgrade refuses to discard changed slot state or cajon journal entries; downgrade behavior was tested only on disposable databases.

## API and authorization

Implemented:

- `GET /api/cajones` — persisted ADMIN or OPERADOR session; returns ordered safe slot views and the SSE high-water cursor with `Cache-Control: no-store`.
- `PATCH /api/cajones/{cajon_id}/estado-operativo` — persisted ADMIN or OPERADOR session; strict request validation, normalized reasons, and 404 for unknown slots.
- `PUT /api/cajones/{cajon_id}/estado-fisico` — dedicated ESP32 bearer only; accepts strict boolean `ocupado` and returns the device-safe physical response.

`ESP32_BEARER_TOKEN` is an optional `SecretStr` setting. An unset or invalid server configuration disables the device endpoint with controlled 503 behavior. Missing or invalid request bearers receive generic 401, `WWW-Authenticate: Bearer`, and `no-store`. A browser cookie does not authorize the device endpoint, and the device bearer does not authorize staff, ADMIN, or OPERADOR endpoints. The development Compose mapping passes the setting through; `.env.example` contains only a blank documented key. The disposable 48-byte local token was stored only in the ignored `.env` and is omitted from this report.

Operational and physical changes use row locks and update only their own state dimension. A meaningful state transition and its `cajon.actualizado` JSONB snapshot commit in one transaction. Repeating an identical normalized state is a no-op: it preserves timestamps and creates no event. The existing SSE role policy now permits cajon events to ADMIN and OPERADOR while keeping operator-management events isolated from OPERADOR.

The shared Web SSE parser validates the exact cajon snapshot shape, state consistency, timestamps, and resource identity. It dispatches through `alActualizarCajon` without invoking operator callbacks; existing cursor, replay, and resync behavior remains covered. No parking UI was added.

The live SSE response initially exposed FastAPI's default `no-cache` header despite the declared policy. The existing SSE route wrapper now normalizes the actual ASGI response to one `Cache-Control: no-store` header. The live runtime check confirmed the emitted header after the API-only restart.

## Files changed

**Added**

- `apps/api/app/models/cajon.py`
- `apps/api/app/esquemas/cajones.py`
- `apps/api/app/servicios/cajones.py`
- `apps/api/app/api/rutas/cajones.py`
- `apps/api/alembic/versions/20261006_0001_parking_slots_backend_foundation.py`
- `apps/api/tests/test_cajones.py`
- `apps/api/tests/test_migracion_cajones.py`

**Updated**

- `.env.example`
- `infra/compose.dev.yml`
- `apps/api/app/api/dependencias.py`
- `apps/api/app/api/rutas/__init__.py`
- `apps/api/app/api/rutas/eventos.py`
- `apps/api/app/core/config.py`
- `apps/api/app/models/__init__.py`
- `apps/api/app/models/eventos_tiempo_real.py`
- `apps/api/app/servicios/eventos_operadores.py`
- `apps/api/main.py`
- `apps/api/tests/conftest.py`
- `apps/api/tests/test_eventos_operadores_sse.py`
- `apps/api/tests/test_operator_audit_sse.py`
- `apps/web/app/utils/eventos-tiempo-real.ts`
- `apps/web/tests/eventos-tiempo-real.test.ts`

The pre-existing modified `apps/web/app/layouts/admin.vue` and untracked `apps/web/app/pages/admin/estacionamiento.vue` were left untouched. The local `.env` remains ignored. No files were staged, committed, pushed, reset, or checked out.

## Verification

**API**

- Focused cajon, migration, and journal coverage: 55 passed.
- Final focused SSE coverage after the ASGI header correction: 38 passed.
- Full API suite with `SP033_MAILPIT_INTEGRATION=1`: 466 passed, 1 skipped.
- `ruff check .`: passed.
- `ruff format --check .`: passed; 91 files already formatted.
- `pyright`: 0 errors, 0 warnings, 0 informations.
- Disposable migration tests verified the initial seed rows, preservation of a historic event, clean downgrade, and refusal to downgrade after slot state or cajon events changed.

**Web compatibility**

- Focused `eventos-tiempo-real` test: 10 passed.
- `pnpm test`: 86 passed.
- `pnpm lint`: passed.
- These gates ran in `web-dev` using the project-declared Node 24.21.0 and pnpm 12.6.0. The host runtime is older; no host toolchain was installed or changed.
- A Nuxt production build was not required for this isolated shared utility change.

## Local runtime acceptance

Acceptance used `127.0.0.1` and synthetic local ADMIN/OPERADOR sessions plus a disposable device token. The synthetic sessions were removed after the run; no synthetic identities remain.

- API `/health`: 200.
- Staff list: ADMIN 200, OPERADOR 200, anonymous 401; rows ordered 1–8 and response marked `no-store`.
- Initial post-migration state was verified before runtime transitions.
- Device report `ocupado=true`: 200, `OCUPADO`, `cambio_aplicado=true`; PostgreSQL matched the response.
- Repeated `ocupado=true`: `cambio_aplicado=false`, unchanged physical timestamp, and no new event.
- Operational maintenance update preserved physical state and derived `NO_DISPONIBLE`; a later physical `LIBRE` report preserved maintenance state and its effective result.
- ADMIN and OPERADOR replayed the same retained `cajon.actualizado` event and immutable snapshot. The emitted SSE cache policy was `no-store`.
- Invalid bearer, cookie-only physical request, device-to-staff list, device-to-operational mutation, and device-to-ADMIN request were denied.
- Final database state: eight rows remain; slot 1 is `LIBRE / DISPONIBLE / LIBRE`, and slots 2–8 remain `DESCONOCIDO / DISPONIBLE / DESCONOCIDO`.
- The journal contains 30 retained `cajon.actualizado` events from the controlled runtime verification passes. The final complete acceptance pass added four meaningful transitions. Earlier valid verification events were retained; no journal history was deleted.

## CodeGraph and deployment

CodeGraph was synchronized after the final source change. Final status: **up to date**, 160 files, 2,926 nodes, 8,515 edges. Impact review covered cajon routes and services, authorization dependencies, event journal and SSE role filtering, and the shared Web parser.

Only `api-dev` was restarted to load the final SSE response behavior. PostgreSQL remained healthy with its existing volume. No LAN/network configuration, VPS deployment, or ESP32 firmware was changed.

Remaining caveats are intentionally deferred integration work: real ESP32 firmware, parking frontend UI, RFID and barrier workflows, and any public availability projection. VPS deployment is not required for this Sprint 3 backend foundation.
