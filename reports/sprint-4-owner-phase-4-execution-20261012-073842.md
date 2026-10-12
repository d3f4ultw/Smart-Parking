# Sprint 4 OWNER Phase 4 Execution

**Date:** 2026-10-12  
**Verdict:** IMPLEMENTED — PHASE 4 ACCEPTED

## 1. Initial repository and database state

- The repository was on `develop` with a heavily modified working tree before Phase 4. It already contained OWNER Phase 1–3 work, parking and real-time SSE work, employee-removal work, and unrelated API/Web changes. Those changes were preserved; no checkout, reset, clean, add, commit, or push was run.
- The existing shared PostgreSQL database was at migration revision `20261011_0007`. A read-only inventory found 140 users (16 ADMIN, 123 OPERADOR, no active OWNER, and one active roleless account), one OWNER profile, two unlink-history records, one historical enrollment row with no active process, 73 login sessions (34 not revoked), 8 parking slots, 599 real-time events, and no modality-history rows.
- One roleless account had OWNER-profile and unlink metadata consistent with possible re-enrollment eligibility. That account was not inspected for identifying information, modified, or used in acceptance testing. All created users and enrollment records used disposable databases.
- The read-only employee inventory could not be completed because the `empleados` relation is absent at revision `20261011_0007`. No employee schema or data was changed.
- The project’s PostgreSQL container was stopped before work and returned to the stopped state after the read-only inspection. The existing `postgres_data` volume remained present.

## 2. Files changed for Phase 4

No new source file or migration was introduced by Phase 4. The following existing files in the already-dirty worktree were edited:

**API**

- `apps/api/app/servicios/propietario.py`
- `apps/api/app/esquemas/activaciones_propietario.py`
- `apps/api/app/api/rutas/activaciones_propietario.py`

**Web**

- `apps/web/app/composables/useActivacionPropietario.ts`
- `apps/web/app/pages/activar-propietario.vue`
- `apps/web/app/utils/activacion-propietario.ts`
- `apps/web/app/pages/admin/index.vue` (OWNER’s account heading and role now identify the authenticated role accurately.)

**Tests**

- `apps/api/tests/test_inscripciones_propietario.py`
- `apps/api/tests/test_mailpit_integration.py`
- `apps/api/tests/test_migracion_desvinculacion_propietario.py` (the expected revision was aligned with the already-present repository head `20261011_0007`; migration code was not changed.)
- `apps/web/tests/activacion-propietario.test.ts`

The required immutable report is the only newly created project file.

## 3. New OWNER registration

The existing enrollment process still creates a new account only when the email has no account. The verified challenge exposes `nueva`; completion requires a full name, a login password, and an independent administrative password. Account, OWNER profile, verified state, hashes, and consumed challenge are committed together. The partial PostgreSQL uniqueness constraint remains the final guard against multiple active OWNER accounts.

## 4. Returning OWNER re-enrollment

Re-enrollment now accepts only an active, email-verified, roleless account with a login hash, an existing OWNER profile whose administrative hash and `rol_anterior` are null, and a consumed, non-invalidated unlink record tied to that same user and profile. The eligibility is checked again during completion.

After fresh email verification, completion restores OWNER on the existing user and profile. It does not create a duplicate user or replace the account ID, email, login hash, or unlink history. ADMIN, OPERADOR, disabled, unverified, temporary-password, and roleless accounts without the required OWNER history remain ineligible. Existing pending enrollment state is not automatically restarted or resent.

## 5. Full-name field

`Nombre completo` was added to the existing activation form. New accounts must provide it. Returning accounts receive their saved name after the email link is exchanged for the short-lived challenge and may correct it; if a saved name exists, they can retain it without re-entering it. A return account with no usable saved name must enter one.

The implementation maps the value into the existing `nombre`, `apellido_paterno`, and `apellido_materno` fields. It adds no duplicate identity field, profile table, or migration. The page fetches the saved name after challenge validation, so it is not included in the activation page’s initial SSR payload.

## 6. Account and password preservation

- New accounts receive independent login and administrative hashes; equal passwords are rejected.
- Returning accounts retain their original login password and replace only the administrative hash. The prior administrative hash is never reused, and administrative passwords do not authenticate normal login.
- The returning profile keeps `rol_anterior = NULL`, preserving the roleless fallback for a later unlink.
- Existing user sessions are revoked at the role transition according to the current policy. OWNER Web-management sessions continue to use their separate cookie and session store.
- Request schemas use secret-valued types for activation tokens and passwords. Tests verify that malformed token and short-password validation errors do not echo their values.

## 7. Email verification and security rules

The existing enrollment timing and delivery rules remain in place: one fixed 60-minute process, each email link limited to 15 minutes and capped by the process deadline, the initial send plus at most three successful resends, a five-minute cooldown, prior-link invalidation after a successful resend, no attempt consumption on SMTP failure, and single-use links. The OWNER challenge cookie remains HttpOnly, SameSite=Lax, path-scoped, and its responses remain `no-store` and `no-referrer`.

Coverage includes expiry boundaries, resend count and cooldown, SMTP rollback, stale-link replay, challenge replacement, simultaneous starts, simultaneous activations, active-OWNER blocking, and the PostgreSQL uniqueness guard.

## 8. Migration, API, Web, and browser validation

- Isolated PostgreSQL migration and OWNER enrollment suites: **33 passed**. Migrations ran against a disposable PostgreSQL instance through `20261011_0007`.
- Isolated Mailpit integration suite: **5 passed**, including delivery and completion of a synthetic returning-OWNER flow.
- ADMIN/OPERADOR, account creation, login, activation, password, and auth regressions: **216 passed, 1 skipped**.
- OWNER management and Phase 3 unlink regression suites: **20 passed**.
- Nuxt/Web tests, including activation, session routing, and Nitro BFF security: **114 passed**.
- `pnpm lint`, `vue-tsc --noEmit`, production `pnpm build`, focused Ruff, and focused Pyright all passed. Pyright reported **0 errors, 0 warnings**. The production build completed client, SSR server, and Nitro output.
- On Windows `localhost:3000`, `/activar-propietario` returned SSR HTML with `no-store` and `no-referrer` headers and no password field names in its payload. Hydration then queried the BFF challenge endpoint and rendered the expected unavailable-link state without a challenge.
- The normal login/BFF path authenticated a synthetic OWNER and opened `/admin`; the hydrated dashboard showed the OWNER name and role. The dashboard’s role label was corrected to “Propietario”. The synthetic session was logged out and its cookie cleared before the temporary services were stopped.
- CodeGraph synced 11 changed files (280 nodes modified); a follow-up status showed the index up to date at 4,112 nodes and 12,047 edges. A query resolved `obtener_datos_desafio_propietario` and its API/test references.

## 9. ADMIN/OPERADOR regression results

The API tests verify that an email already assigned to ADMIN or OPERADOR cannot start OWNER enrollment and that no account, OWNER profile, enrollment row, or email is created. Existing role, account creation, login, password activation, and resend contracts passed their regression suite. No ADMIN/OPERADOR authorization or enrollment flow was modified.

## 10. PostgreSQL data preservation

Migration and acceptance tests used the temporary `sp-owner-phase4-db` container and disposable databases only. Temporary API, Mailpit, web, and PostgreSQL containers were stopped and removed after validation. No shared PostgreSQL reset, migration, or write occurred. The project’s original PostgreSQL, API, Mailpit, and Web containers remain stopped, `postgres_data` remains present, and the existing volume inventory was not recreated. The temporary browser login was revoked before cleanup.

## 11. Remaining limitations

- Email delivery was verified through isolated Mailpit, not through an external SMTP provider. No real OWNER account or external recipient was used.
- The browser verified SSR, challenge hydration/BFF behavior, normal synthetic OWNER login, and `/admin`. The token-bearing enrollment form itself was validated through API/Mailpit integration and Web tests, rather than entering a live emailed token into the browser.
- One optional test was skipped, and Starlette emitted its existing TestClient/httpx deprecation warning. The role-regression runtime synchronized the locked `httpx2` dependency inside its disposable container; no dependency lockfile change was made.
- No Phase 5 account-management or invitation work was started.
