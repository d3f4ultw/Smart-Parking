# OWNER Phase 3: Secure Account Unlinking

Date: 2026-10-11 17:20 (America/Mexico_City)

## Objective

Implement OWNER Phase 3 as specified in the user-provided request: securely unlink the OWNER account by an emailed, one-use confirmation link, restore the prior operational role or leave the account roleless, and preserve its identity, login password, history, and the separate management session.

## Scope

Implemented the additive FastAPI/PostgreSQL/Alembic flow and its Nuxt BFF and public confirmation page. The confirmation page reads the token from the URL fragment, removes it from browser history, and submits automatically. No real OWNER unlink was performed. No email was sent to the real OWNER.

## Work performed

- Added an unlink request model and additive migration `20261011_0005_owner_unlinking.py`. The model stores only a purpose-specific SHA-256 token hash. Tokens are 256-bit, single-use, expire after 15 minutes, and are rate-limited.
- Added the OWNER unlink service and management API routes. Start requires the temporary OWNER management session, the same-origin request, and the separate administrator password. Confirmation is token-authenticated, does not require that session, locks the relevant rows, restores ADMIN/OPERADOR or sets the role to null, clears the separate administrator hash, consumes the request, and revokes regular sessions atomically. The management lease remains intact.
- Added roleless-account login handling. A correct password for a roleless account returns the generic no-access response without creating a session; protected API and SSE routes continue to deny access.
- Added the OWNER-facing unlink panel, scoped BFF proxy routes, and client-only `/confirmar-desvinculacion` page. The public confirmation proxy strips all cookies. A GET does not perform unlinking.
- Added API, migration, BFF, SSR, login, and Mailpit integration coverage. The pre-existing `20261011_0006_personal_sse.py` migration was preserved.

## Validation

- Focused API tests: **43 passed** (`test_desvinculacion_propietario.py`, `test_migracion_desvinculacion_propietario.py`, `test_gestion_propietario_web.py`, `test_inscripciones_propietario.py`). The test session fixture creates a uniquely named `smart_parking_test_<uuid>` database, upgrades that database, and drops it afterward.
- Frontend suite: **119 passed**.
- Actual Mailpit delivery and confirmation using a synthetic recipient and an isolated test database: **1 passed**.
- Pyright on changed API modules and related tests: **0 errors, 0 warnings, 0 informations**.
- Ruff on API `app` and `tests`: **passed**.
- Nuxt typecheck: **passed**. `pnpm lint`: **passed with 9 existing formatting warnings** in unrelated files; those files were left unchanged.
- Scoped `git diff --check -- apps/api apps/web`: **passed**. The repository-wide check separately reported an existing blank line at `.gitignore:56`; it was left untouched.
- CodeGraph sync: **passed**. `codegraph status` reported the index up to date (253 files); a focused query found the new unlink service functions, model, email builder, and frontend component.
- Browser smoke: opened `http://localhost:3000/confirmar-desvinculacion` with a synthetic invalid token. The page automatically submitted it, removed the fragment from the visible URL, and displayed the generic unavailable-link message. The dev backend returned no successful confirmation. The successful browser completion was not exercised against the shared database because it contains a real OWNER; successful completion was covered through the isolated API/Mailpit integration test.

## Findings

- A final read-only aggregate query found one active OWNER, zero roleless users, one OWNER profile, zero unlink requests, a non-null OWNER administrator hash, one open temporary management lease, and 72 total regular-session rows (34 unrevoked). The account was not unlinked, and the OWNER's email or other identifying details were not queried.
- The shared development database's Alembic revision was `20261011_0004` during the initial preflight and `20261011_0006` during final verification. No direct migration command was issued against that database. The test fixture uses a separate temporary database, and the `api-dev` Compose command starts Uvicorn rather than Alembic. The cause and timing of the revision change cannot be established from the available evidence. No rollback was attempted; the current database revision and `postgres_data` volume were preserved.

## Limitations / unresolved items

- The unexplained development-database revision change from `20261011_0004` to `20261011_0006` remains unresolved. Although aggregate counts show the OWNER, profile, management lease, unlink-request table, and total regular-session rows in the expected state, the earlier and final reads do not provide a complete before/after comparison of every database row.
- Browser verification covered the public page's invalid-token path only. A real success link was verified through the isolated API/Mailpit integration test, not through a browser connected to the shared development database.
- As specified, automatic confirmation may still be triggered by a link scanner that executes JavaScript; the email and page explain that risk, and the fragment keeps the token out of ordinary HTTP request URLs and referrer headers.

## Result

The OWNER unlink feature is implemented and its backend, migration, BFF, frontend, and email contracts pass focused validation. Shared development data was not intentionally mutated by the implementation or tests; however, the development database revision discrepancy prevents a clean claim that its schema remained unchanged for the entire work session.

**FINAL VERDICT: PASS WITH LIMITATIONS**
