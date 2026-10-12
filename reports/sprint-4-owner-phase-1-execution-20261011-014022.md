# Sprint 4 OWNER Phase 1 Execution

Date: 2026-10-11 01:40:22 America/Mexico_City  
Mode: EXECUTOR — OWNER Phase 1  
Repository: `C:\Users\Zero\Documents\Proyectos\Smart Parking`

## 1. Initial repository and database state

- The checkout was on `develop...origin/develop` with pre-existing uncommitted changes spanning API/SSE work, Cajones, employees, parking modality, Nuxt, firmware, and configuration. Existing changes in `apps/api/app/cli/gestionar_admins.py` and `scripts/gestionar-admins.sh` were present at baseline. They and the other unrelated changes were preserved.
- Alembic source head and development database revision were both `20261010_0002` before this work. The development snapshot was read within a PostgreSQL `READ ONLY` transaction.
- Baseline roles: 16 ADMIN, 123 OPERADOR, and zero OWNER. There were 139 users, 70 sessions, 0 employees, 8 Cajones, 592 real-time events with high-water mark 592, and no parking-modality configuration or history rows.
- PostgreSQL used the existing `postgres_data` volume at `/var/lib/postgresql/data` and the existing anonymous volume `825ea8186338efd367542fd8b42df351c0fbaf91c3b90381229d58677fae5892` at `/var/lib/postgresql`. All four development containers were running; the API health endpoint returned `healthy`.

## 2. Files created and modified

Created:

- `apps/api/alembic/versions/20261011_0001_owner_foundation.py`
- `apps/api/app/cli/propietario.py`
- `apps/api/tests/test_migracion_propietario.py`
- `apps/api/tests/test_propietario.py`
- `scripts/owner.bat`
- `scripts/owner.sh`

Modified:

- `apps/api/app/models/usuario.py`
- `apps/api/tests/test_usuarios.py`
- `apps/api/tests/test_sp027.py`

The `test_sp027.py` authentication regression parameters now name ADMIN and OPERADOR explicitly. OWNER login and Web authorization remain outside Phase 1; no authentication implementation or existing ADMIN/OPERADOR permissions were changed. The administrator-management launchers and the parking-modality CLI were not modified by this work.

## 3. OWNER role and database constraint

- Added `RolUsuario.OWNER` while retaining the ADMIN and OPERADOR values and behavior.
- Added the ORM metadata index `uq_usuarios_owner_activo` and additive Alembic revision `20261011_0001`.
- PostgreSQL definition: unique index on `usuarios (rol)` with predicate `rol = 'OWNER' AND esta_activo IS TRUE`. Zero active OWNER rows remain valid; inactive OWNER rows are outside the predicate.
- The migration changes schema only. It does not create, activate, convert, or update any user account.

## 4. CLI and launcher behavior

`app.cli.propietario` is the shared Python menu for both launchers:

```text
1. Registrar OWNER
2. Desvincular OWNER
3. Consultar estado
0. Salir
```

- Option 1 displays `Disponible en Fase 2`; option 2 displays `Disponible en Fase 3`. Both are placeholders and perform no database mutation.
- Option 3 queries PostgreSQL for an active OWNER and reports either `Existe un OWNER activo.` or `No existe un OWNER activo.`
- Invalid input keeps the menu open. Ctrl+C, EOF, clean exit, and database errors return controlled exit codes; database details are not printed.
- The new `.bat` and `.sh` scripts reuse the project Compose startup, environment-clearing, interactive `api-dev` execution, and exit-code conventions. The existing administrator launchers remain separate.

## 5. Migration and automated test results

- The migration was first tested against isolated PostgreSQL databases at the pre-OWNER revision. Tests verified zero and one active OWNER, rejection of a second active OWNER, multiple inactive OWNER rows, downgrade removal of the index without deleting users, and two concurrent activation attempts yielding one commit and one unique-index rejection.
- Focused role, CLI, migration, authentication, and ADMIN/OPERADOR regression selection: **256 passed**. It included `test_propietario.py`, `test_usuarios.py`, `test_gestionar_admins.py`, the OWNER and pending-ADMIN migration tests, and SP-008/009/010/013/014/015/025/026/027/028/029/031.
- Final OWNER CLI and migration rerun: **11 passed**.
- Ruff lint and format checks passed for the changed Python files. Pyright reported **0 errors, 0 warnings, 0 informations** for the changed Python files and the focused role/authentication tests.
- After the isolated migration and regression gates passed, development PostgreSQL was upgraded from `20261010_0002` to `20261011_0001`. The live index definition matches the intended predicate.

## 6. Windows and Linux acceptance evidence

- Executed `scripts/owner.bat` through Windows `cmd.exe`; entered registration placeholder, unlink placeholder, status, and exit. Both exact phase messages appeared, status reported no active OWNER, and the launcher exited with code 0.
- Executed `scripts/owner.sh` under Debian/WSL Bash with the same interaction. Both phase messages and the PostgreSQL status appeared; the launcher exited with code 0.
- Before launcher acceptance, Compose dry-run showed `api-dev` and `postgres` already Running. Both real launcher runs reported the services Running/Healthy and did not recreate them.
- Compose emitted existing network and `postgres_data` project-ownership warnings. They did not prevent either launcher from working; the same volumes remained mounted afterward.

## 7. Database preservation verification

Read-only before/after snapshots matched for application data and sequence values. Only the Alembic revision and the new index changed.

| Measure | Before | After |
|---|---:|---:|
| Alembic revision | `20261010_0002` | `20261011_0001` |
| ADMIN / OPERADOR users | 16 / 123 | 16 / 123 |
| Total users; ID range | 139; 122–394 | 139; 122–394 |
| Active OWNER accounts | 0 | 0 |
| Sessions; ID range | 70; 25–218 | 70; 25–218 |
| Employees | 0 | 0 |
| Cajones | 8, numbers 1–8 | 8, numbers 1–8; states unchanged |
| Real-time events; ID range | 592; 1–592 | 592; 1–592 |
| SSE event high-water mark | 592 | 592 |
| Parking modality / history rows | 0 / 0 | 0 / 0 |

Public sequence values were unchanged: `activaciones_cuenta_id_seq=338`, `cajones_id_seq=8`, `configuracion_estacionamiento_id_seq=NULL`, `empleados_id_seq=2`, `estado_eventos_operadores_id_seq=NULL`, `eventos_operadores_id_seq=NULL`, `historial_modalidad_estacionamiento_id_seq=NULL`, `sesiones_id_seq=218`, and `usuarios_id_seq=394`.

The `postgres_data` and anonymous PostgreSQL volume identities and mount points were the same before and after migration and launcher execution. No OWNER account was created. Production was not touched.

CodeGraph was synchronized after source changes: 7 changed files indexed (4 added, 3 modified). Final status reported up to date with 201 files, 3,579 nodes, and 10,494 edges; post-sync queries found `RolUsuario`, the new migration, and the OWNER CLI entry point.

## 8. Remaining limitations

- OWNER registration and unlinking are intentionally unavailable until Phases 2 and 3. No OWNER password, email flow, Web route, or `/admin` permission change was implemented.
- OWNER is not yet a supported login/Web role. Existing ADMIN and OPERADOR login coverage remains explicit and passed.
- Validation was performed against the local development Podman/PostgreSQL stack only. No production migration or deployment was performed.
- The Compose project-name warnings for the existing network and `postgres_data` volume remain; neither resource was recreated or removed.

## Result

Phase 1 is implemented and accepted. Existing application records, sequences, and PostgreSQL volumes were preserved, and development PostgreSQL is at Alembic head `20261011_0001` with zero active OWNER accounts.

**IMPLEMENTED — PHASE 1 ACCEPTED**
