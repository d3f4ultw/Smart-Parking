# Sprint 4 Phase 2 — Employee Functional Acceptance

Date: 2026-10-11 (America/Mexico_City)

## 1. Environment and initial database state

- The development stack was running in Podman: `web-dev`, `api-dev`, `postgres`, and `mailpit`.
- PostgreSQL database: `smart_parking_dev`; Alembic revision: `20261010_0002`.
- At the recorded baseline for the browser acceptance, the database contained 1 controlled employee QA record, 139 users (including the QA OPERADOR account, ID 394), 70 sessions, and 8 Cajones. The employee record was cleaned up after its browser workflow; the operator account and its active session were retained for inspection.
- The PostgreSQL volumes remained mounted: `postgres_data` at `/var/lib/postgresql/data`, plus the existing anonymous volume at `/var/lib/postgresql`. No volume was reset, recreated, or removed.
- Existing unrelated working-tree changes were preserved. No Git staging, commit, push, reset, checkout, or worktree cleanup was performed.

## 2. Employee browser operations and results

Using the authenticated ADMIN session at `http://localhost:3000/admin/empleados`:

- Registered a synthetic test employee and verified that the employee was unauthorized by default.
- Verified that the record retained the registering ADMIN ID and a database-generated registration timestamp.
- Attempted a duplicate employee number using different letter casing; PostgreSQL-backed case-insensitive uniqueness rejected it.
- Edited the employee name and number, authorized parking, then revoked authorization.
- Reloaded the page and confirmed the edits and revoked state persisted. The original registrar and registration timestamp remained unchanged.
- The synthetic employee record (ID 1) was removed with a narrowly matched cleanup after verifying its test values, unauthorized state, registrar, and timestamp. The delete affected exactly one row. The employee identity sequence was left at `last_value=2, is_called=true`; it was not reset.

As OPERADOR, direct navigation to `/admin/empleados` redirected to `/operador` before an employee form was rendered. No employee registration request was submitted from the OPERADOR browser session and no employee was created by that account.

## 3. OPERADOR account and login

The controlled OPERADOR account, ID 394, had been created through the existing supported operator-management workflow and was used for browser acceptance. The account was activated and logged in for this test. Its active session was retained so the user can inspect `/operador`. No password, activation token, or session cookie is recorded here.

## 4. ADMIN, OPERADOR, and anonymous authorization checks

- ADMIN could use employee registration, listing/details, editing, and authorization controls in the browser.
- The ADMIN-only route guard redirected OPERADOR away from `/admin/empleados`; the operator sidebar contains no Empleados link.
- Targeted API tests confirmed OPERADOR employee mutations return HTTP 403. Anonymous and invalid sessions return HTTP 401.
- The employee API's ADMIN authorization is enforced server-side; hiding the route or menu is not the only control.
- Existing Cajón access remained available to OPERADOR through the existing staff-protected endpoints. The operator panel did not add a new role, authentication flow, or employee capability.

## 5. SSR, CSR, operator panel, responsiveness, and hydration

The operator panel was added by adapting the existing parking-control view and using a dedicated operator layout. It uses the existing same-origin Nitro BFF routes and the existing operator session middleware. The operator navigation contains only “Estacionamiento”; it has no employee link, page, or registration form.

Files changed:

- `apps/web/app/layouts/operador.vue`
- `apps/web/app/pages/operador.vue`

Browser evidence: `/operador` rendered the operator identity, parking summary, all 8 Cajones, and existing operational controls. The “Administrar lugar 1” modal opened and was cancelled without submitting a change. A hard reload rendered the panel again. Direct access to `/admin/empleados` while logged in as OPERADOR returned to `/operador`. The browser console had no new hydration errors after the successful reload. One Vite HMR reload warning occurred while replacing the layout and was cleared by a full-page reload.

Validation completed:

- Web tests: 110 passed, 0 failed.
- Employee backend tests: 11 passed.
- Targeted employee/Cajón authorization and operational tests: 3 passed.
- ESLint for both changed Vue files: passed.
- Nuxt typecheck: passed.
- Nuxt production build: completed.
- `git diff --check` for the two changed files: passed; Git printed only line-ending conversion warnings.
- CodeGraph sync reported 2 changed files; subsequent status reported the index up to date (197 files, 3,516 nodes, 10,375 edges).

The employee ADMIN flow had been exercised in the browser. The new operator page was verified by direct navigation and hard reload; a separate in-app CSR transition into that page was not exercised. The attempted browser viewport change did not alter the actual viewport, so a narrow-screen visual check remains unverified.

## 6. Test data cleanup and PostgreSQL preservation

The synthetic employee row was removed with a value-constrained delete; the employee table was then empty. The test OPERADOR account and its active session were deliberately retained for the user's inspection. A Mailpit QA invitation message also remains: its single-message delete endpoint returned HTTP 405, and no bulk deletion was attempted. The activation had already been consumed; message contents and credentials were not read into this report.

Protected-data snapshots taken immediately around employee cleanup matched for the non-test data:

| Data | Count | Fingerprint |
|---|---:|---|
| Users excluding QA account 394 | 138 | `445b4f4e4fef44c5c4426a671533f583` |
| Sessions excluding QA account 394 | 68 | `0d419b8c133fe2d1f8c6af1b4fd83e9a` |
| Cajones | 8 | `6ab20f867afc327dfac081d0a8e2817e` |
| SSE rows through baseline ID 574 | 574 | `31b4e85dbf2d926ead563a8b0adc5e7e` |
| SSE history at the final snapshot | 578 | `644a2f31a885fe9b8ea220350f2e4566` |

Parking configuration and modality history remained empty (0 rows); the database revision remained `20261010_0002`. The event cursor/head was 578 at the final snapshot. SSE events 577 and 578 appeared during the acceptance window and remained preserved; the event schema has no actor field, so their actor cannot be attributed from the available evidence. Cajón 1 was `LIBRE` / `DISPONIBLE` in the final state. No parking configuration, modality history, existing user, unrelated session, Cajón, or PostgreSQL volume was deleted or reset. The previously requested ADMIN logout revoked that ADMIN session as requested.

## 7. Defects and remaining limitations

- The browser's viewport-control attempt did not change its actual dimensions, so responsive behavior at mobile width was not visually verified.
- A separate client-side navigation check for the new operator panel was not performed; direct navigation, route guarding, reload, and hydration console state were checked.
- The OPERADOR browser was redirected before an employee form appeared, so no UI registration attempt could be submitted. Server-side denial was instead confirmed by targeted API tests (403), alongside route redirection.
- SSE events 577 and 578 appeared during the acceptance window, but their actor cannot be determined from the stored event schema. They were preserved.
- One Mailpit QA invitation remains because its per-message delete endpoint returned 405. No broader cleanup was attempted.

## Result

**PHASE 2 ACCEPTED WITH CAVEATS**