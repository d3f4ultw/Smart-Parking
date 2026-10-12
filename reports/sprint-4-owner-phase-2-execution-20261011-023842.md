# Sprint 4 OWNER Phase 2 Execution

Date: 2026-10-11 02:38:42 America/Mexico_City  
Mode: EXECUTOR — OWNER Phase 2  
Repository: `C:\Users\Zero\Documents\Proyectos\Smart Parking`  
Plan: `reports/sprint-4-owner-seven-phase-master-plan-20261011-011502.md`

## 1. Initial repository and database state

- The checkout was on branch `develop` with a substantial pre-existing dirty worktree containing Sprint 3/4, OWNER Phase 1, parking, employee, SSE, frontend, firmware, and configuration work. Phase 2 changes were made without resetting, staging, or cleaning that worktree. Unrelated changes were preserved.
- At Phase 2 start, the source Alembic head and development PostgreSQL revision were `20261011_0001`. The database baseline was read-only. It contained 16 ADMIN and 123 OPERADOR users, 139 users total (IDs 122–394), 70 sessions (IDs 25–218), 0 employees, 8 Cajones, 0 parking-modality configuration/history rows, 599 real-time events (IDs 1–599), and event high-water mark 599. There were 0 active OWNER accounts.
- Development PostgreSQL remained on the existing container (`ec979ef47e07…`) and the existing `postgres_data` and anonymous data volumes. Existing development services were kept in place. The local browser acceptance container `sp-owner-phase2-web-accept` was retained for the user’s open page; no PostgreSQL volume was recreated or removed.

## 2. Files created and modified

Phase 2 API additions:

- `apps/api/alembic/versions/20261011_0002_owner_enrollment.py`
- `apps/api/app/api/rutas/activaciones_propietario.py`
- `apps/api/app/esquemas/activaciones_propietario.py`
- `apps/api/app/models/cuenta_propietario.py`
- `apps/api/app/models/inscripcion_propietario.py`
- `apps/api/app/servicios/propietario.py`
- `apps/api/tests/test_inscripciones_propietario.py`
- `apps/api/tests/test_migracion_owner_enrollment.py`

Phase 2 web additions:

- `apps/web/app/composables/useActivacionPropietario.ts`
- `apps/web/app/pages/activar-propietario.vue`
- `apps/web/app/utils/activacion-propietario.ts`
- `apps/web/server/api/autenticacion/activacion-propietario/completar.post.ts`
- `apps/web/server/api/autenticacion/activacion-propietario/desafio.get.ts`
- `apps/web/server/api/autenticacion/activacion-propietario/enlace.post.ts`
- `apps/web/server/middleware/owner-activation-security.ts`
- `apps/web/server/utils/proxy-activacion-propietario.ts`
- `apps/web/tests/activacion-propietario.test.ts`

Related integration and email changes:

- Updated `apps/api/app/api/rutas/__init__.py`, `apps/api/app/models/__init__.py`, and `apps/api/main.py` to register the owner activation route and models and apply no-cache/no-referrer response handling.
- Updated `apps/api/app/correo/mensajes.py` to deliver the owner enrollment message, and `apps/api/tests/test_correo_transportes.py` to verify its expiry wording.
- Updated frontend/API registration components and tests listed above. The Phase 1 launchers `scripts/owner.bat` and `scripts/owner.sh` were reused without Phase 2 changes.

## 3. OWNER registration path and database constraint

- The existing Phase 1 `RolUsuario.OWNER` role and PostgreSQL partial unique index `uq_usuarios_owner_activo` remain the database guard: at most one user can have role `OWNER` while active; zero active OWNER accounts remain valid. The Phase 1 report records the isolated single-index and concurrent activation validation.
- Migration `20261011_0002` additively creates `cuentas_propietario` and `inscripciones_propietario`, including unique enrollment token/challenge hash indexes and checks. It does not write or convert user records.
- The activation flow stores hashes rather than raw email-link or challenge tokens. A valid one-time email link lasts 60 minutes. After the link is opened and exchanged successfully, the challenge lasts the configured 15 minutes from that opening, including when the link is opened near its 60-minute expiry. The final edge case was fixed and covered by a test.
- Completing the flow is transactional. For a new account it creates the active OWNER with separate login and administrative password hashes. For an eligible existing ADMIN or OPERADOR account it preserves the login password, records the previous role and administrative password hash in the owner profile, and revokes sessions as part of promotion. Neither path was exercised against a real development user.
- The flow rejects an existing active OWNER. No registration, promotion, unlinking, or privilege change was performed in the development database.

## 4. Activation page, email, and launcher behavior

- The activation page and browser title say “Registro del propietario”. Password labels are “Contraseña” and “Confirmar contraseña”; each password input has an accessible show/hide control.
- The page shows a live pass/fail checklist for minimum length, uppercase character, printable characters, confirmation, and distinct login/administrative passwords where both apply. It does not display the technical maximum of 128 characters, while the enforced limit remains in place.
- “Activar cuenta” remains disabled until the applicable fields are present and valid. The email states both that the one-use link expires in 60 minutes and that the opened form allows 15 minutes to complete registration.
- The challenge expiry is calculated from successful link exchange, independent of the original link expiry after exchange. Verification checked the late-open case: opening at minute 55 leaves the full 15-minute form window.
- Both Phase 1 launchers were executed through their actual Windows `cmd.exe` and Linux WSL Bash entry points. They displayed the shared interactive menu and exited cleanly with code 0. They remain unchanged in Phase 2. No unlinking behavior was added.
- The local page returned HTTP 200 with the updated Spanish title and no-store/no-referrer headers. Browser password entry, submission, and sign-in to `/admin` remain under the user’s control and were not performed or observed.

## 5. Migration and automated test results

- The Phase 2 migration was tested against isolated PostgreSQL before it was applied to development. Development then advanced from `20261011_0001` to `20261011_0002`; the migration only adds empty OWNER profile/enrollment tables and indexes.
- The full backend regression selection completed with **301 passed** before the final challenge-expiry edge-case adjustment. The earlier focused OWNER, migration, authentication, and ADMIN/OPERADOR regression selection completed with **56 passed**.
- After the final expiry adjustment, `tests/test_inscripciones_propietario.py` completed with **18 passed**. Ruff passed for the changed service and test, and Pyright reported **0 errors, 0 warnings, 0 informations** across `app` and `tests`.
- The owner email wording test passed, including its plain-text and HTML 60-minute link / 15-minute form statements. The focused email and enrollment run completed with **18 passed**.
- The full web suite completed with **116 passed**. Nuxt type checking and targeted ESLint passed. The final expiry adjustment touched only the API service and API test; no web source changed afterward.
- CodeGraph was synchronized after the final source change. Sync indexed the two changed files; `codegraph.cmd status` reported **up to date** (218 files, 3,830 nodes, 11,231 edges).

## 6. Windows and Linux acceptance evidence

- Windows: `cmd.exe /c call scripts\owner.bat` ran the shared menu, exercised the phase placeholders and PostgreSQL status path against an isolated acceptance database, and exited with code 0.
- Linux: `bash /mnt/c/.../scripts/owner.sh` ran the same interaction under WSL and exited with code 0. The launchers reused the established Compose/API Python environment and did not recreate the existing PostgreSQL service or volumes.
- The page’s automated and SSR checks passed. Manual submission and post-activation `/admin` login are pending the user’s own credential entry; no credentials were read, generated, entered, or included in this report.

## 7. Database preservation verification

Read-only development snapshots immediately before and after the migration showed existing application records and sequences unchanged:

| Measure | Before | After |
|---|---:|---:|
| Alembic revision | `20261011_0001` | `20261011_0002` |
| ADMIN / OPERADOR users | 16 / 123 | 16 / 123 |
| Total users; ID range | 139; 122–394 | 139; 122–394 |
| Active OWNER accounts | 0 | 0 |
| Sessions; ID range | 70; 25–218 | 70; 25–218 |
| Employees | 0 | 0 |
| Cajones | 8; numbers 1–8 | 8; numbers 1–8 |
| Parking configuration / history rows | 0 / 0 | 0 / 0 |
| Real-time event history; ID range | 599; 1–599 | 599; 1–599 |
| Real-time event high-water mark | 599 | 599 |
| `cuentas_propietario` rows | 0 | 0 |
| `inscripciones_propietario` rows | 0 | 0 |

Existing sequence values remained unchanged (`activaciones_cuenta_id_seq=338`, `cajones_id_seq=8`, `empleados_id_seq=2`, `sesiones_id_seq=218`, `usuarios_id_seq=394`); the new OWNER table sequences remain unused. Existing volume identities and mounts remained the same. No OWNER user was created, activated, or converted in development.

The separate isolated acceptance database `sp_owner_phase2_accept_20261011` is at revision `20261011_0002`; it contains no users or owner profiles, two synthetic enrollment records, and zero active OWNER accounts. One synthetic link was exchanged for a challenge during validation. It was kept separate from development and was not deleted.

## 8. Remaining limitations

- User-controlled browser submission and `/admin` sign-in acceptance remain pending. Automated backend, frontend, email, migration, launcher, and SSR checks passed, but they do not replace that manual browser acceptance.
- Emails already delivered to the local test mailbox before the wording update retain their original content; newly generated owner enrollment emails contain the 15-minute form notice.
- No OWNER unlinking, production migration, production email, or later sprint phase was implemented.
- The repository remains on the existing `develop` checkout with the pre-existing and current uncommitted project work preserved.

## Result

Phase 2 is implemented and automated/local-runtime checks pass. Development PostgreSQL is at `20261011_0002`, the existing data and volumes are preserved, and no real OWNER account was created. Manual credential entry, form submission, and `/admin` sign-in remain pending under user control.

**IMPLEMENTED — READY WITH CAVEATS**
