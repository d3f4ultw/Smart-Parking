# Sprint 4 OWNER Phase 2 Corrections

- **Execution timestamp:** 2026-10-11 09:29:36 UTC
- **Repository:** Smart Parking, branch develop
- **Verdict:** **READY WITH CAVEATS**
- **Scope:** Phase 2 corrections only. Phase 3 and later phases were not started.

## 1. Initial repository and database state

The checkout already contained extensive modified and untracked work from earlier Smart Parking sprints. It was not a clean working tree. Existing unrelated changes were preserved; no staging, commit, reset, checkout, cleanup, PostgreSQL reset, or volume recreation was performed.

Development PostgreSQL was at Alembic revision 20261011_0002. Before the final checks, its aggregate state was:

| Data | Initial value |
|---|---:|
| Users | 139 |
| ADMIN / OPERADOR | 16 / 123 |
| Active OWNER | 0 |
| Sessions | 70 |
| Employees | 0 |
| Cajones | 8 |
| Parking configuration / modality history | 0 / 0 |
| SSE events / current event state | 599 / 1 |
| OWNER profiles / enrollment rows | 0 / 1 |

The one existing development enrollment was not inspected at the email, token, or hash level. Its status view in the early misconfigured launcher attempt was read-only: the action entered was invalid and rejected; no send, resend, or database write occurred. After that attempt, the launchers were pointed only at the isolated acceptance database.

## 2. Root cause and corrected behavior

The server already held the enrollment, resend, cooldown, and token rules, but the CLI's Option 1 did not reliably resume the pending enrollment. It could prompt for another email instead of showing the existing process and its next actions. This made resend availability and link expiry unclear.

Option 1 now reuses the pending process, displays a sorted status table, and offers a contextual resend or menu return. It does not wait silently for the cooldown. The main menu remains unchanged.

The first live terminal capture showed the resend prompt indented to the right. On POSIX, entering raw terminal mode disables the normal newline-to-carriage-return behavior. The CLI now emits CRLF explicitly in that raw-input path and redraws both timer and prompt from the left margin. Windows .bat and WSL/Linux .sh acceptance both show the prompt aligned at the left margin after timer refreshes.

## 3. OWNER and resend security behavior

- OWNER remains a supported role; ADMIN and OPERADOR permissions were not changed.
- The single-active-OWNER partial unique index remains in force. Zero active OWNER accounts are valid.
- One enrollment permits the initial email plus up to three resends (four successful sends maximum).
- A resend becomes available after five minutes from the last successful send. Failed SMTP sends do not consume a resend or corrupt enrollment state.
- Every successful send issues a new link valid for 60 minutes from that send. The initial email is the first send; each of the three resends gets its own 60-minute validity period. Issuing a new link invalidates the previous one; only the latest link can be exchanged.
- Expired, consumed, superseded, and forged links are rejected. Exhausted resends stay blocked for the enrollment process; a safely throttled restart is available after expiry.
- The 15-minute activation-form challenge starts only after a valid email link is exchanged. The captured isolated challenge interval was 900 seconds.

Automated resend coverage includes cooldown, three-resend exhaustion, expired restart, SMTP failure, invalidation/replay, and concurrent resend attempts. Role and migration regressions also passed.

## 4. Files and user-facing changes

Corrections in this work touched:

- apps/api/app/servicios/propietario.py — read-only enrollment status projection and UTC normalization used by the CLI.
- apps/api/app/cli/propietario.py — pending-enrollment reuse, contextual resend, colored status table, real-time countdown, stable left-aligned prompt redraw, and CLI-only UTC date formatting.
- apps/api/tests/test_propietario.py — enrollment reuse, countdown, redraw alignment, and visible date formatting coverage.
- apps/web/app/pages/activar-propietario.vue — concise expired-link message, lighter expired-state typography, and matching-password labels changed to “La contraseña coincide”.

The existing scripts/owner.bat and scripts/owner.sh were exercised and remain the entry points. Existing administrator-management scripts and the parking-modality CLI were not changed by this correction.

Console dates display as YYYY-MM-DD HH:MM:SS UTC, for example 2026-10-11 09:40:18 UTC. This is formatting only: it does not alter how timestamps are stored. The stored UTC values and database schema were not changed for this display adjustment.

## 5. CLI and launcher evidence

Sanitized output captured from both the actual Windows batch launcher and the WSL/Linux shell launcher:

    Enlace vigente hasta (UTC) | 2026-10-11 09:40:18 UTC
    Tiempo restante para validar la cuenta: 00:15:00
    [R] Reenviar enlace vigente  [M] Menú:

The countdown refreshed in place with the resend prompt starting at the left margin. In both launchers, Option 1 reused the existing isolated pending enrollment without asking for another email; pressing M returned to the unchanged main menu and 0 exited cleanly. These runs did not send or resend email and did not mutate the enrollment. The launchers used a temporary isolated-database adapter and --no-recreate protection; the development database was not used for launcher acceptance.

## 6. Migration, automated tests, and flow acceptance

- Isolated PostgreSQL reached Alembic head 20261011_0002; development PostgreSQL was already at the same head. No new migration was needed for these Phase 2 corrections.
- OWNER service and CLI tests after the final terminal fix: **41 passed**.
- API role, migration, user, ADMIN-management, and authentication regression pack: **141 passed**.
- Full web test suite after the activation-copy update: **116 passed**.
- Web lint: passed. Ruff: passed. Pyright: **0 errors, 0 warnings, 0 informations**.
- Synthetic initial email delivery to the development mail service was confirmed. The link exchange reached the Nuxt activation form, and its 15-minute challenge was verified in isolated PostgreSQL. The synthetic database still has zero users, zero sessions, zero OWNER profiles, and zero active OWNER accounts.
- The activation form was intentionally left before password entry or submission, following the user’s credential-entry handoff. No password was entered or stored, and no account was created.
- Unauthenticated /admin redirected to login (HTTP 302). Authenticated OWNER login and OWNER access to /admin were not performed, so they are not claimed as accepted.

## 7. Database and runtime preservation

The final development snapshot exactly matched the initial aggregate counts above. Sequence values also remained unchanged: activations 338, Cajones 8, employees 2, OWNER enrollments 1, sessions 218, and users 394. Other listed project sequences remained unused. No OWNER account was created.

The existing PostgreSQL and API development containers retained their original IDs and remained running. The postgres_data volume and the existing anonymous PostgreSQL volume remained mounted; no volumes were reset or recreated. The isolated acceptance database ended at revision 20261011_0002 with zero users, zero sessions, zero OWNER profiles, and one synthetic enrollment/challenge only.

## 8. Remaining limitations and verdict

The real browser flow stopped at the activation form because the user reserved password entry for their own handoff. Therefore, a completed browser activation, authenticated OWNER login, and authorized /admin session remain pending manual acceptance. The implementation and automated coverage are ready for that step, but it was not represented as passed.

**Final verdict: READY WITH CAVEATS**
