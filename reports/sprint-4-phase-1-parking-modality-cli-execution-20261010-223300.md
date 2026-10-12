# Sprint 4 Phase 1 — Parking Modality CLI Execution Report

Date: 2026-10-10 22:33:00 America/Mexico_City  
Previous plan: `reports/sprint-4-phase-1-parking-modality-cli-plan-20261010-220317.md`

## Objective

Implement and validate the local parking-modality configuration flow through the existing administrative CLI and launchers. Keep the development installation unconfigured until the user selects a modality.

## Initial repository and database state

- The repository already had unrelated uncommitted Cajón, SSE, web, and firmware work. Those changes were preserved; this task did not stage, commit, reset, or clean the worktree.
- Before implementation, the source Alembic head and `smart_parking_dev` revision were both `20261008_0001`.
- `postgres`, `api-dev`, `web-dev`, and `mailpit` were running. The PostgreSQL data directory used the existing `postgres_data` volume.
- The database had eight Cajones: #1 `LIBRE / DISPONIBLE`; #2 `DESCONOCIDO / FUERA_DE_SERVICIO`; #3–#8 `DESCONOCIDO / DISPONIBLE`. No Cajón had an operational reason.
- The event journal had 574 rows, IDs 1–574, and `estado_eventos_tiempo_real.ultimo_id = 574`. Its full-row fingerprint was `1c4715886cee9473591b37c599498991`.
- The full-row Cajón fingerprint was `5ff7cb596a9397e5b5966816e090ddb7`.
- Role counts were `ADMIN=16` and `OPERADOR=122`. Existing sequence values were: `activaciones_cuenta_id_seq=337`, `cajones_id_seq=8`, `sesiones_id_seq=215`, and `usuarios_id_seq=393`; the two existing event sequences had no recorded last value.
- Neither modality table existed before this phase.

## Implementation and files

### Modified

- `apps/api/app/cli/gestionar_admins.py` — adds the local-administration menu option and delegates to the modality submenu; the existing administrator flow remains available.
- `apps/api/app/models/__init__.py` — registers the two modality models while preserving its existing Cajón/SSE registrations.
- `apps/api/tests/conftest.py` — clears modality history and configuration in the isolated test database teardown.
- `apps/api/tests/test_gestionar_admins.py` — updates expectations for the expanded main menu.
- `scripts/gestionar-admins.sh` — fixes WSL fallback detection. In this environment the Linux Podman client printed a Compose-provider error while returning status 0, so the old status-only check skipped the working `podman.exe` fallback. The script now also detects the provider error output. `scripts/gestionar-admins.bat` was not changed.

### Created

- `apps/api/app/models/configuracion_estacionamiento.py`
- `apps/api/app/servicios/configuracion_estacionamiento.py`
- `apps/api/app/cli/configuracion_estacionamiento.py`
- `apps/api/alembic/versions/20261010_0001_parking_modality_configuration.py`
- `apps/api/tests/test_configuracion_estacionamiento.py`
- `apps/api/tests/test_migracion_configuracion_estacionamiento.py`

No API route, HTTP mutation endpoint, Nuxt modality editor, staff role, authentication mechanism, actor field, history trigger, dependency, RFID feature, or firmware change was added.

## Final database schema and service behavior

The additive migration creates:

- `configuracion_estacionamiento`: integer primary key constrained to `1`, modality constrained to `PRIVADO`, `PUBLICO`, or `MIXTO`, positive `revision`, and a database-generated `actualizado_en` timestamp.
- `historial_modalidad_estacionamiento`: generated technical ID, configuration foreign key, unique configuration/revision pair, nullable previous modality, required new modality, and database-generated `cambiado_en` timestamp. Constraints require a null previous value for revision 1 and distinct supported modalities for later revisions.

The migration inserts no configuration row and selects no default. No actor or origin is recorded. The history has no normal CLI edit/delete operation. Downgrade is permitted only while both new tables are empty; it refuses to drop configured data.

The service reads an absent row as unconfigured, validates exact modality values, records the initial change as `NULL → selected mode`, and atomically commits each meaningful update with one history row. Selecting the current mode leaves the revision, timestamp, and history unchanged. It locks an existing singleton row and compares the revision shown during confirmation. Initial creation uses a conflict-safe insert; a losing concurrent CLI receives a stale-state result and must review and confirm again. SQLAlchemy failures roll back the transaction.

The CLI displays the current persisted mode, accepts only numbered choices, requires confirmation before persistence, shows the newest 20 history rows, handles cancellation/EOF, and prints safe database errors.

## Migration results

- Tested the new migration from its parent revision in isolated temporary PostgreSQL databases before touching `smart_parking_dev`.
- Isolated tests verified an empty configuration after upgrade, preservation of the eight Cajones and event journal, unchanged pre-existing sequence values, clean downgrade while empty, and refusal to downgrade after a modality was stored.
- Applied `uv run alembic upgrade head` through `api-dev`. The development database is now at `20261010_0001 (head)`.
- Both persistent modality tables contain zero rows. The development installation remains `SIN CONFIGURAR`.
- The pre-existing sequences retained their values. The new technical sequences are uncalled and have no last value.

## Automated validation

- Focused run: `tests/test_configuracion_estacionamiento.py`, `tests/test_migracion_configuracion_estacionamiento.py`, and `tests/test_gestionar_admins.py` — **54 passed** (24.30 s on the final run).
- Relevant regression and migration run: `tests/test_cajones.py`, `tests/test_eventos_operadores_sse.py`, `tests/test_operator_audit_sse.py`, `tests/test_migracion_admin_pendiente.py`, `tests/test_migracion_cajones.py`, and `tests/test_migracion_operator_audit_sse.py` — **60 passed**.
- Ruff check: **passed**. Ruff format check: **passed**. Pyright: **0 errors, 0 warnings, 0 informations**.
- Bash syntax check (`bash -n scripts/gestionar-admins.sh`): **passed**.

## Windows/Linux launcher and real CLI acceptance

- `scripts/gestionar-admins.bat` ran successfully after migration. It opened the main menu, displayed the persisted `SIN CONFIGURAR` state, showed an empty history, returned through both menus, and exited with code 0.
- `scripts/gestionar-admins.sh` ran successfully in the Debian WSL Bash environment using the supported Windows Podman fallback. The interactive terminal flow displayed the same unconfigured state and empty history, returned through both menus, and exited with code 0.
- Existing ADMIN navigation and workflows passed in the focused administrator test suite. The live launcher acceptance did not list persistent ADMIN records.
- Real change acceptance used a separate temporary database, `smart_parking_cli_acceptance_mv3bturm`: the CLI explicitly confirmed `PUBLICO`, persisted revision 1, then displayed `SIN CONFIGURAR → PUBLICO` in history. The state was verified in PostgreSQL and the temporary database was dropped.
- Both launcher runs emitted existing Compose warnings that the network and `postgres_data` volume carry the `infra` project label while Compose expected `smart-parking`. The existing `postgres_data` mount remained attached; no volume was recreated.

## Final preservation check

After migration and launcher acceptance:

- `smart_parking_dev` remained at `20261010_0001` with zero configuration rows and zero history rows.
- The eight Cajones retained fingerprint `5ff7cb596a9397e5b5966816e090ddb7`.
- All 574 journal rows retained IDs 1–574 and fingerprint `1c4715886cee9473591b37c599498991`; the high-water mark stayed at 574.
- Role counts stayed at `ADMIN=16` and `OPERADOR=122`, and existing sequence values stayed unchanged.
- `postgres_data` remained mounted at `/var/lib/postgresql/data`.
- CodeGraph sync completed successfully. Status reported the index up to date, and a focused query found `cambiar_modalidad_estacionamiento` plus its CLI and test references.

## Remaining limitations

- Launcher validation covers the existing development Compose environment. A separate production deployment or standalone native Linux host was not available in this task; the Linux launcher was exercised through the project's WSL/`podman.exe` path.
- The Compose project-label warnings remain as pre-existing environment configuration. They did not alter the volume or stored application data.

## Result

Phase 1 is implemented, migrated, and validated. The persistent development installation remains explicitly unconfigured; the only persisted mode change was performed in a temporary acceptance database that was removed after verification.

IMPLEMENTED — PHASE 1 ACCEPTED
