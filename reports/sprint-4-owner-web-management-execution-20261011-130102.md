# Sprint 4 Dueño Web Management Execution

Date: 2026-10-11 13:01:02 -06:00 America/Mexico_City  
Scope: OWNER Phase 2 Web migration only  
Verdict: IMPLEMENTED — READY WITH CAVEATS

## 1. Initial repository and database state

- The repository already contained a broad dirty working tree across API authentication/SSE, Nuxt administration and operator views, parking configuration, employee support, firmware, and configuration. Those unrelated edits were preserved; no checkout, reset, clean, stage, commit, or push operation was used.
- The development services were running as `web-dev`, `api-dev`, `postgres`, and `mailpit`. The Web port was bound to `127.0.0.1:3000`; the named `postgres_data` volume used the local driver.
- Before the change, the development database was at Alembic revision `20261011_0003`. Counts, in order, were: 139 users, 70 normal sessions, 8 Cajones, 599 realtime events, 1 realtime state row, 27 SSE connections, 1 OWNER enrollment, 0 owner profiles, 0 employees, and 152 activation records.
- Relevant sequence values before the migration were unchanged after it: activation 338, Cajón 8, employee 2, enrollment 1, normal session 218, and user 394. The pre-existing enrollment was not opened in a browser, modified, resent, or included in this report by email address.

## 2. Files created and modified

- API session foundation: added `apps/api/alembic/versions/20261011_0004_owner_web_management_session.py`, `apps/api/app/api/rutas/gestion_propietario.py`, `apps/api/app/cli/propietario_web.py`, `apps/api/app/esquemas/gestion_propietario.py`, `apps/api/app/models/sesion_gestion_propietario.py`, and `apps/api/app/servicios/gestion_propietario.py`.
- API integration: updated `apps/api/alembic/env.py`, `apps/api/app/api/rutas/__init__.py`, `apps/api/app/models/__init__.py`, `apps/api/main.py`, and `apps/api/app/servicios/propietario.py`. The previous interactive `apps/api/app/cli/propietario.py` entry point is now a compatibility wrapper that invokes the Web access issuer; the terminal menu was retired after the API/BFF and email acceptance passed.
- API validation: added `apps/api/tests/test_gestion_propietario_web.py` and `apps/api/tests/test_migracion_gestion_propietario.py`; updated `apps/api/tests/conftest.py`, `apps/api/tests/test_mailpit_integration.py`, and `apps/api/tests/test_propietario.py` for the management-session model, synthetic email/activation flow, and new CLI entry point.
- Nuxt interface: added `apps/web/app/layouts/gestion-propietario.vue`, `apps/web/app/pages/admin/gestion-propietario/index.vue`, and the reusable components `Navegacion.vue`, `RegistrarPropietario.vue`, `ConsultarEstado.vue`, `ListaInscripciones.vue`, and `DesvincularNoDisponible.vue` under `apps/web/app/components/gestion-propietario/`; added `apps/web/app/utils/gestion-propietario.ts`.
- Nitro BFF: added `apps/web/server/utils/proxy-gestion-propietario.ts` and routes under `apps/web/server/api/gestion-propietario/` for claim, session resolve, heartbeat, status, enrollment start, and resend. Updated `apps/web/nuxt.config.ts` and `apps/web/tests/server-proxy-security.test.ts`.
- Launch and runtime wiring: updated `scripts/owner.bat`, `scripts/owner.sh`, and `infra/compose.dev.yml`.

## 3. Launcher and reusable URL behavior

- Both launchers now start the existing Compose services and invoke the same Python issuer, `app.cli.propietario_web`. They print a reusable management URL and a separate pairing code, then open the configured Web URL where supported.
- The URL is built from configured `APP_PUBLIC_URL` and places the random ticket in the fragment at `/admin/gestion-propietario#…`; the pairing code is not part of the URL. The actual synthetic issuer was invoked twice against isolated PostgreSQL: the second pending issue replaced the first, leaving one pending row and one replaced row.
- If issuance finds a live management session, both launchers report that state without printing another URL or code. The Windows `.bat` active-session branch passed against a Podman stub; its ready path was exercised in a temporary copy with only the browser opener replaced. The Linux `.sh` ready and active paths passed with stubbed Podman and `xdg-open`. `bash -n scripts/owner.sh` passed.

## 4. Pairing and management-session security

- PostgreSQL stores only hashes of the ticket, pairing code, and browser credential. The first claim requires both the fragment ticket and the separate pairing code; the code is cleared on success and five failed code attempts expire the pending link.
- The browser receives a dedicated `HttpOnly`, `SameSite=Strict` cookie, with `Secure` enabled in production. It is not the regular login cookie and carries no ADMIN/OWNER application role.
- A same-cookie claim is idempotent, including when the reusable URL is reopened. A different browser with only the copied URL has neither the browser cookie nor a usable pairing code. The ticket remains valid for its active session and is cleared when that session expires.
- A PostgreSQL advisory transaction lock and a partial unique index over pending/active rows serialize issuance and claims across workers. Pending unclaimed links expire after ten minutes; active sessions have no absolute deadline.
- Writes and claims require the configured same-origin `Origin`. Nitro forwards only the allow-listed management cookie to management API routes. Management responses use no-store/no-referrer/noindex and sanitized errors.

## 5. Heartbeat, timeout, and browser-tab behavior

- Each mounted management tab sends heartbeats every 15 seconds. PostgreSQL rejects the lease after 60 seconds without a heartbeat. There is no unload/page-close revocation and no `Salir` action; closing all tabs stops heartbeats, while any tab that continues to run the layout heartbeat renews the browser-wide cookie lease.
- The service tests cover the 59/60-second boundary, renewal, expiry, stale-link invalidation, concurrent issuance, and competing claims. The active URL is not consumed by reads, refreshes, or menu actions.
- A real multi-tab GUI session was not manually driven. Browser timer suspension during device sleep or intensive background throttling can exceed the 60-second lease and is listed as a remaining limitation.

## 6. Web registration and status functionality

- The protected-by-purpose page is `/admin/gestion-propietario`, under a dedicated layout and independent of the normal ADMIN middleware. The Spanish-visible action labels use “Dueño”: “Registrar dueño”, “Desvincular dueño”, and “Consultar estado”. Navigation selects modular panels; unlink is shown unavailable for Phase 3 and has no backend route.
- Registration requires an explicit email submission. Session recovery and status reads are read-only. The DTO presents the saved email, enrollment status, initial-send state, successful send count, remaining resends, current link deadline/validity, cooldown, fixed process deadline, remaining time, and blocked-action reasons without token/hash fields.
- The management route remains usable before a Dueño account exists. The manager cookie alone does not authorize ordinary application routes.

## 7. Email resend and enrollment preservation

- The existing enrollment service remains authoritative: one fixed 60-minute process, each email link valid for at most 15 minutes and capped by the process deadline, initial message plus at most three successful resends, five-minute cooldown, newest link only, and no process restart before expiry.
- Web page load and recovery do not send email. Start and resend are explicit operations, with eligibility rechecked by the API. SMTP failure preserves the existing valid link and counters.
- The isolated Mailpit integration delivered a synthetic enrollment message, read status without sending another message, completed activation, logged in through normal OWNER authentication, and verified that the management cookie alone received 401 from `/api/cajones`. Test-created messages and database rows were cleaned by the integration fixture.

## 8. API, BFF, SSR, and browser acceptance

- FastAPI exposes only the Phase 2 management operations: claim, session resolve, heartbeat, status, explicit registration, and resend. No unlink or exit endpoint was added. Normal application authorization dependencies and regular sessions remain separate.
- Nuxt uses same-origin Nitro routes and a dedicated layout. SSR resolves only whether the temporary session is active; it does not put ticket, code, cookie, email status, or activation token into shared state. The ticket is read from `window.location.hash` only on the client and removed after authorization. No unload handler revokes access.
- The native Windows request to `http://localhost:3000/admin/gestion-propietario` returned HTTP 200 with `no-store`, `no-referrer`, and `noindex`; the unauthenticated session BFF returned inactive. Windows `Test-NetConnection localhost:3000` succeeded through IPv4, while the IPv6 `::1` attempt reported no listener; Podman remains bound to the required IPv4 loopback.
- No real browser was used with the live database because it contains a pre-existing pending enrollment whose email must remain private. Browser-cookie isolation, copied-link denial, reusable claims, and BFF forwarding were instead exercised in isolated API/Web tests and synthetic Mailpit flow. A full GUI test across two browser profiles was not run.

## 9. Automated test and migration results

- Isolated PostgreSQL migration validation: upgrade through `20261011_0004`, verify the empty session table and partial unique predicate, downgrade to `20261011_0003`, then upgrade again.
- API OWNER/session/enrollment tests: 34 passed. ADMIN/Cajón authorization regressions: 47 passed. Mailpit integration tests: 3 passed.
- Nuxt test suite: 117 passed. ESLint, `nuxi typecheck`, and production `pnpm build` passed in `web-dev`. Ruff passed for the affected API and test files.
- Launcher checks: Windows `.bat` active and ready branches used synthetic Podman responses; Linux `.sh` ready and active branches used synthetic Podman responses and a stub opener. No real launcher created a management session in the development database.
- CodeGraph synced 35 changed files (23 added, 12 modified); status reported the index current at 242 files, 4,112 nodes, and 11,938 edges. A query resolved the new issuer, claim, and heartbeat service symbols.
- Focused `git diff --check` passed. A repository-wide check reports one pre-existing extra blank line at EOF in the already-dirty `.gitignore`; that unrelated file was not edited for this task.

## 10. PostgreSQL data preservation

- The only development-database migration was additive: `20261011_0003` to `20261011_0004`, creating `sesiones_gestion_propietario`. Afterward the table had zero rows. User, session, Cajón, SSE event/state/connection, enrollment, owner-profile, employee, activation, and existing sequence counts matched the recorded baseline. The enrollment count remained one; no live Owner account was created and the final OWNER-role count was zero.
- The original `postgres_data` named volume and `web-dev`, `api-dev`, `postgres`, and `mailpit` containers remained present. No database reset or volume recreation was performed.
- The disposable PostgreSQL test container received an anonymous volume automatically from the image. Its exact volume ID and task-time creation were verified; only that task-created container and its anonymous test volume were removed. The named `postgres_data` volume was preserved.

## 11. Remaining limitations

- Phase 3 is not implemented: “Desvincular dueño” remains unavailable, with no API endpoint. No “Salir” action was added by design.
- Service-level and BFF tests cover session reuse, separate-cookie denial, and heartbeat expiry, but an interactive browser test across tabs/profiles and physical close/reopen was not performed. Browser sleep/background throttling can delay 15-second JavaScript timers enough for the 60-second idle lease to expire.
- Full API suite and end-user GUI acceptance were not run; the report records focused regressions and a native unauthenticated route check. IPv6 loopback at `::1:3000` remains unavailable; native Windows `localhost:3000` works through `127.0.0.1`.
- The report directory is ignored by Git as configured; the report was created locally without staging it.

## Result

The Phase 2 Dueño Web management migration is implemented, the development schema is at `20261011_0004`, existing development data and the named PostgreSQL volume were preserved, and focused API/Web/email/launcher checks passed. Remaining caveats are limited to real-browser multi-tab validation, JavaScript timer suspension, and IPv6 loopback.

**IMPLEMENTED — READY WITH CAVEATS**