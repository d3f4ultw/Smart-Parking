# Sprint 4 OWNER Phase 2 Expiration and Resend Correction

- **Execution timestamp:** 2026-10-11 03:51:18 America/Mexico_City
- **Previous report:** [sprint-4-owner-phase-2-corrections-20261011-092936.md](sprint-4-owner-phase-2-corrections-20261011-092936.md)
- **Verdict:** **READY WITH CAVEATS**
- **Scope:** Correct the enrollment and link expiration interpretation and confirm resend invalidation. No Phase 3 work was started.

## Objective and corrected timing

The previous report described each link as valid for 60 minutes and described a 15-minute form window after opening. Those timing statements are superseded by this correction.

The verified implementation now follows the clarified rule:

- The enrollment process has one fixed 60-minute window beginning with the initial email.
- The initial email plus at most three successful resends are allowed within that same window, with at least five minutes between successful sends.
- Each link expires 15 minutes after its own send time, capped by the original process deadline. Opening or exchanging the link does not restart or extend that expiration.
- A successful resend replaces the stored token hash. The prior link can no longer be exchanged; only the most recently sent, unexpired link is accepted.
- A failed SMTP send rolls back the tentative token replacement, resend count, and send timestamp, so the previously delivered link remains usable.
- Once the original 60-minute process expires, the CLI permits starting a new enrollment process.

## Changes

- apps/api/app/servicios/propietario.py: separates link expiry from the fixed enrollment-process deadline, limits both link exchange and any resulting challenge to the remaining absolute validity, and replaces the saved token hash on successful resend.
- apps/api/app/models/inscripcion_propietario.py and apps/api/alembic/versions/20261011_0003_owner_enrollment_window.py: persist the fixed process expiration. The additive migration backfills existing rows from their creation time and does not create or activate a user.
- apps/api/app/correo/mensajes.py: explains the link's 15-minute maximum, the fixed 60-minute process, and resend limits.
- apps/api/app/cli/propietario.py: presents the link deadline separately from the process deadline, displays dates as DD/MM/YYYY HH:mm:ss UTC, and only requests a new enrollment after the current process has ended.
- OWNER service, CLI, email, and migration tests cover the clarified deadlines, successful resend invalidation, failed-send rollback, cooldown, limits, and migration.

## Validation

- Focused test for cooldown, all three resends, and rejection of the original link after a later send: **1 passed** during this supplemental verification.
- The focused OWNER/API test run after the timing correction: **53 passed**.
- Ruff formatting/lint and Pyright completed successfully; Pyright reported 0 errors, 0 warnings, and 0 informations.
- The isolated PostgreSQL migration and resend tests passed before migration 20261011_0003 was applied to development PostgreSQL.
- CodeGraph status: **index up to date** (219 indexed files).
- Existing Windows batch and WSL/Linux launcher acceptance remains as recorded in the previous report. The launchers were not rerun for this supplemental timing clarification; launcher files were not changed here.
- No new SMTP message or credential entry was performed during this supplemental verification. The browser activation, completed account creation, authenticated OWNER login, and authenticated /admin acceptance remain unverified pending the user's credential handoff.

## Database preservation

Development PostgreSQL advanced additively from Alembic revision 20261011_0002 to 20261011_0003. The captured before/after aggregate counts remained unchanged: 139 users, 0 active OWNER users, 70 sessions, 0 employees, 8 parking slots, 599 realtime events, 1 current realtime-event state, 27 SSE connections, and 1 existing OWNER enrollment. OWNER profiles remained at 0. Recorded sequences and the existing PostgreSQL volumes were preserved. No account was created or activated.

## Limitations

The new link deadline and invalidation rules have automated coverage. This supplemental change did not repeat end-to-end mail delivery or authenticated browser acceptance. The prior report is immutable and remains unchanged; its 60-minute-per-link and post-open 15-minute descriptions are historical and are not the current behavior.

**Final verdict: READY WITH CAVEATS**