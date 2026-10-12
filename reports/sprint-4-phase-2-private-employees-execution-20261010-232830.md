# Sprint 4 Phase 2 — Private Employee Management Execution

Date: 2026-10-10 (America/Mexico_City)  
Primary plan: `reports/sprint-4-phase-2-private-employees-plan-20261010-230303.md`  
Previous phase record: `reports/sprint-4-phase-1-parking-modality-cli-execution-20261010-223300.md`

## Final verdict

**IMPLEMENTED — READY WITH CAVEATS**

The employee persistence, ADMIN-only API, same-origin BFF, and Nuxt page are implemented. The isolated migration tests and automated suites passed, and the additive migration is applied to development PostgreSQL. Authenticated browser checks verified the page, empty state, client navigation, and two-field registration modal. Full browser CRUD and responsive acceptance remain unverified; no employee was written to the persistent development database for browser testing.

## 1. Initial repository and database state

The repository already had unrelated uncommitted Sprint 4 parking/Cajón, SSE, firmware, and development-tooling work. It was preserved. This execution made only the employee-scope source changes listed below plus this report; no Git staging, commit, reset, checkout, or cleanup was performed.

The first read-only database check found Alembic revision `20261010_0001`, no `empleados` table, 138 users, 67 sessions, eight Cajones, 574 real-time events, one real-time event-state row, and no parking-modality configuration or history. After the user started the ADMIN session, the required immediate pre-migration recheck found 68 sessions and `sesiones_id_seq=216` (the earlier check had 67 and 215). I used the rechecked state as the migration baseline. The active parking modality remained unset.

The four existing Podman containers (`web-dev`, `api-dev`, `postgres`, and `mailpit`) were running. PostgreSQL used the existing `postgres_data` volume at `/var/lib/postgresql/data` and the same pre-existing anonymous volume at `/var/lib/postgresql`. No container or volume was reset or recreated.

## 2. Files created and modified

### Created

- Backend: `apps/api/app/models/empleado.py`, `apps/api/app/esquemas/empleados.py`, `apps/api/app/servicios/empleados.py`, `apps/api/app/api/rutas/empleados.py`, and `apps/api/alembic/versions/20261010_0002_private_employees.py`.
- Backend tests: `apps/api/tests/test_empleados.py` and `apps/api/tests/test_migracion_empleados.py`.
- Nitro BFF: `apps/web/server/utils/proxy-admin-empleados.ts` and route handlers `apps/web/server/api/admin/empleados.get.ts`, `apps/web/server/api/admin/empleados.post.ts`, `apps/web/server/api/admin/empleados/[empleadoId].get.ts`, `apps/web/server/api/admin/empleados/[empleadoId].patch.ts`, and `apps/web/server/api/admin/empleados/[empleadoId]/autorizacion.patch.ts`.
- Nuxt UI: `apps/web/app/composables/useEmpleados.ts`, `apps/web/app/utils/empleados.ts`, `apps/web/app/components/admin/CrearEmpleadoModal.vue`, and `apps/web/app/pages/admin/empleados/index.vue`.
- Web tests: `apps/web/tests/empleados.test.ts`.
- This immutable execution report.

### Modified

- Backend wiring and authorization: `apps/api/app/api/dependencias.py`, `apps/api/app/api/rutas/__init__.py`, `apps/api/app/models/__init__.py`, `apps/api/alembic/env.py`, and `apps/api/main.py`.
- Backend test cleanup: `apps/api/tests/conftest.py` now removes employees before their registering users to respect the restrictive foreign key.
- ADMIN navigation: `apps/web/app/layouts/admin.vue`.
- Existing BFF security suite: `apps/web/tests/server-proxy-security.test.ts`.

## 3. Final employee schema

The additive table contains exactly these six application fields:

| Field | PostgreSQL definition | Behavior |
|---|---|---|
| `id` | `integer` identity primary key | Database-generated internal ID |
| `nombre_completo` | `varchar(200) NOT NULL` | Trimmed and validated as non-empty |
| `numero_empleado` | `varchar(64) NOT NULL` | Trimmed and validated as non-empty |
| `autorizado` | `boolean NOT NULL DEFAULT false` | Registration always starts unauthorized |
| `registrado_por_usuario_id` | `integer NOT NULL` | Foreign key to `usuarios(id)` with `ON DELETE RESTRICT`; sourced from the authenticated ADMIN session |
| `registrado_en` | `timestamptz NOT NULL DEFAULT now()` | Database-generated registration time |

PostgreSQL enforces case-insensitive employee-number uniqueness through the unique index `uq_empleados_numero_empleado_lower` on `lower(numero_empleado)`. Thus `EMP-001` and `emp-001` conflict. Check constraints reject stored blank names or numbers. No extra employee fields, tables, login, roles, or authorization history were added.

## 4. API and authorization behavior

The FastAPI router provides:

- `GET /api/admin/empleados` for the paginated list.
- `POST /api/admin/empleados` for registration (`201`).
- `GET /api/admin/empleados/{empleado_id}` for details.
- `PATCH /api/admin/empleados/{empleado_id}` for name and employee-number edits.
- `PATCH /api/admin/empleados/{empleado_id}/autorizacion` for grant/revoke.

Every operation requires an ADMIN session. Missing or invalid sessions receive `401`; an OPERADOR receives `403`. Strict request schemas accept only the intended fields. The registration request cannot set the registering ADMIN, authorization status, or registration time. The database index is the authority for duplicate numbers; its violation maps to the duplicate response. Edit operations preserve the original registrar and timestamp. Changes are committed transactionally and commit failures roll back.

Responses avoid password, email, and session material and carry `Cache-Control: no-store`. Employee authorization only records parking permission; the UI states that it does not enable physical entry.

## 5. Nuxt interface and BFF implementation

`/admin/empleados` uses the existing ADMIN layout and session middleware. The page uses a stable `useAsyncData` key and request-aware fetch for SSR/hydration, without module-level user state. Nitro routes keep browser calls same-origin, forward the session cookie server-side, validate IDs and payload allow-lists, and preserve safe upstream status contracts.

The page provides a compact paginated directory, registration, details and original registration metadata, basic editing, and authorization/revocation controls. The registration modal has exactly two input fields. Loading, empty, success, error, and retry states are present. After successful changes it updates the affected row or refreshes the affected list; it does not refetch unrelated application data. The existing layout gained an Empleados navigation link.

## 6. Migration results

The new migration has revision `20261010_0002` and parent `20261010_0001`. The migration test suite ran against isolated PostgreSQL before the development migration: all three migration tests passed, including preservation, defaults/index/FK checks, empty downgrade, and refusal to downgrade with persisted employees.

Immediately before applying the migration, the development database still reported `20261010_0001`, no employee table, and the rechecked protected-data baseline described above. `uv run alembic upgrade head` in `api-dev` applied only `20261010_0001 -> 20261010_0002`. The database now has one Alembic head, `20261010_0002`; the new table has zero rows. No example employees were seeded.

The database migration did not modify parking-modality configuration/history, Cajón data, authentication data, or event records. The separately created browser-test database had zero active connections, was dropped after validation, and its temporary token file and directory were removed. The existing PostgreSQL volumes remain in place.

## 7. Automated test results

- Focused employee API and migration tests: 14 passed.
- Full API test suite: 503 passed, 3 skipped.
- API Ruff: passed.
- API Pyright: passed with 0 errors, 0 warnings, and 0 informations.
- Full Web test suite: 110 passed, 0 failed.
- Web lint: passed.
- `vue-tsc --noEmit -p .nuxt/tsconfig.app.json`: passed.
- Production Web build: passed and included the employee page and Nitro routes.
- Existing authentication/session and BFF regression coverage was included in the passing API/Web suites.

CodeGraph was synchronized after source changes. `codegraph status` reports the index up to date, and focused queries resolve `exigir_admin` and `proxyListarEmpleados` to the employee implementation and route.

## 8. Browser acceptance evidence

Using the user's already-authenticated ADMIN session at `http://localhost:3000` after migration:

- `/admin/empleados` opened without redirect and rendered the empty directory.
- A full page reload rendered the authenticated page and empty state.
- Client-side navigation from Dashboard to Empleados returned to the same empty state.
- The registration modal exposed exactly the `Nombre completo` and `Número de empleado` fields and was cancelled without submitting.
- The directory remained empty; no employee data was written to the development database.

The visible SSR reload and CSR route checks passed. The available browser control exposed the rendered accessibility tree, but not browser console diagnostics, so this run does not claim console-level proof that no hydration warning occurred.

## 9. Database preservation verification

Read-only snapshots immediately before and after the migration had identical row counts and table fingerprints for users, sessions, Cajones, real-time events, event-state rows, parking configuration, and modality history:

| Protected data | Before migration | After migration |
|---|---:|---:|
| Users | 138 | 138 |
| Sessions | 68 | 68 |
| Cajones | 8 | 8 |
| Real-time events | 574 | 574 |
| Real-time event-state rows | 1 | 1 |
| Parking configuration rows | 0 | 0 |
| Modality-history rows | 0 | 0 |
| Employee rows | table absent | 0 |

The table fingerprints matched across the migration snapshots. Existing sequence states also matched: `activaciones_cuenta_id_seq=337`, `cajones_id_seq=8`, `sesiones_id_seq=216`, `usuarios_id_seq=393`; the other pre-existing sequences remained uninitialized. Only `empleados_id_seq` was added, and it remains uninitialized because the new table is empty. The `postgres_data` and anonymous PostgreSQL volume identities and mount destinations matched before and after.

## 10. Remaining limitations

- Full browser registration, duplicate feedback, detail/edit, authorization/revocation, persistence-after-refresh, responsive layout, and anonymous/OPERADOR browser navigation were not exercised. Automated API, BFF, and component tests cover the relevant contracts, but they are not a substitute for those browser flows.
- The existing authenticated browser was used for read-only acceptance. A separate disposable browser stack could not be launched because `compose.dev.yml` requires root `.env` values that were not present. No employee was created in the persistent development database to work around this.
- Browser console diagnostics were not available through the selected browser-control interface; the absence of visible SSR/CSR problems is recorded, while console-level hydration verification remains open.
- Existing uncommitted work from adjacent Sprint 4 and SSE/firmware tasks remains in the repository as it was; no adjacent phase was started.
