# Sprint 4 Owner Registration Wizard — Execution Report

Date: 2026-10-12 13:25:48 America/Mexico_City
Verdict: PASS WITH LIMITATIONS

## Objective

Implement a simple Spanish-language wizard to establish the Dueño account. New accounts use three steps; returning roleless Dueño accounts use two steps and keep their existing access password.

## Scope

- Capture `nombre`, `apellido_paterno`, and optional `apellido_materno` in the existing user fields.
- Validate password rules and confirmations in FastAPI; keep account activation and challenge consumption atomic.
- Preserve progress only in the same browser while its verified challenge remains valid.
- Preserve the existing activation cookie boundary and Dueño management flows.
- No schema migration, real Dueño account mutation, or adjacent feature work.

## Work performed

- Added a 3-step new-account flow and a 2-step return flow. Returning accounts see their stored personal fields and only set an administrative password.
- Kept frontend copy short and Spanish, using “Dueño” in visible text. The edited view, composable, and utility contain no visible “Owner” or “OWNER” copy.
- Stored only personal fields, account type, step, and challenge expiry in the progress draft. The challenge is checked by the backend before restoring that draft; passwords and tokens are not included.
- Enforced password policy, confirmations, different access/administrative passwords for new accounts, and comparison of a returning account's new administrative password against its existing access-password hash.
- Kept identity updates, role assignment, administrative-password update, and challenge consumption in one transaction. Added service/API and Mailpit regression coverage.

## Changes

- `apps/api/app/esquemas/activaciones_propietario.py`
- `apps/api/app/api/rutas/activaciones_propietario.py`
- `apps/api/app/servicios/propietario.py`
- `apps/api/tests/test_inscripciones_propietario.py`
- `apps/api/tests/test_mailpit_integration.py`
- `apps/web/app/pages/activar-propietario.vue`
- `apps/web/app/composables/useActivacionPropietario.ts`
- `apps/web/app/utils/activacion-propietario.ts`
- `apps/web/tests/activacion-propietario.test.ts`

No migration was added. The existing shared PostgreSQL data, `postgres_data`, and pre-existing containers were left in place.

## Validation

- API activation tests: `25 passed` against a disposable PostgreSQL container.
- Mailpit owner enrollment and return tests: `2 passed, 3 deselected`; synthetic message cleanup remained scoped to test recipients.
- Nuxt tests: `115 passed`.
- Nuxt lint: passed. `vue-tsc --noEmit`: passed. Production build: passed.
- Targeted Ruff check: passed. Targeted Pyright check: `0 errors`.
- SSR check on the isolated local web instance: HTTP 200, stable “Establecer dueño” title and “Verificando el enlace…” placeholder; personal data was absent before challenge verification.
- Browser check against disposable data: the new flow displayed steps 1 of 3 and 2 of 3; the returning flow displayed 1 of 2 and 2 of 2 with personal fields prefilled and no access-password field. The activation token was removed from the URL after exchange.
- Responsive check at a 375 px viewport: the personal form used one column and the document width remained 375 px. No password value was entered or submitted in the browser.
- CodeGraph sync updated 9 changed files (286 nodes); status is up to date and the activation service symbol resolves to the route and test callers.
- The isolated API, PostgreSQL, and web test services and their test volume were removed. The original development containers and volumes remained running.

## Limitations / unresolved items

- Browser verification stopped before entering or submitting credentials. Password policy, confirmations, account-type rules, and transactional behavior were covered by API and frontend tests instead.
- Browser automation blocked navigation to the temporary cookie-cleanup handler, so it could not explicitly clear the HttpOnly synthetic challenge cookie. The isolated database/API were removed, leaving no matching challenge record; the cookie expires under the configured 15-minute challenge lifetime. The temporary browser tabs were closed.
- The shared `localhost:3000` instance was not used to complete an account; it has no synthetic activation challenge for this test. All successful wizard browser checks used `localhost:3100` with disposable data.

## Result

The Dueño establishment wizard and backend enforcement are implemented and pass targeted API, frontend, build, lint, type, and isolated browser checks. No real Dueño account was modified.

PASS WITH LIMITATIONS
