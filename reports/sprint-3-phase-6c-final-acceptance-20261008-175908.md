# Sprint 3 Phase 6C Final Acceptance

Date: 2026-10-08 17:59:08 America/Mexico_City (UTC-06:00)

## Objective

Validate a real operational-state transition with an empty reason through the authenticated Nuxt ADMIN page, FastAPI, and persistent development PostgreSQL; verify the event journal and restore the original state.

Previous reports reviewed:

- reports/sprint-3-phase-6c-operational-management-execution-20261008-013842.md
- reports/sprint-3-phase-6c-optional-reason-live-database-fix-20261008-020009.md

## Environment and initial database state

- Podman showed api-dev and web-dev running and postgres healthy. PostgreSQL accepted connections on 127.0.0.1:5432. The API /health endpoint returned HTTP 200.
- API and Web containers have no configured container healthcheck, so their state is reported as running rather than healthcheck-healthy. Host publications were loopback-only: Web 127.0.0.1:3000, API 127.0.0.1:8000, PostgreSQL 127.0.0.1:5432.
- Alembic reported 20261008_0001 (head).
- The authenticated GET /api/cajones could not be completed: a direct unauthenticated request returned HTTP 401 with the safe detail “No autenticado”. The database snapshot below is a direct read of the persistent development database and is not presented as a substitute for the protected API response.
- Initial persistent database snapshot:

| Cajón | Operational state | Reason | Physical state | Effective state |
|---:|---|---|---|---|
| 1 | DISPONIBLE | NULL | LIBRE | LIBRE |
| 2 | FUERA_DE_SERVICIO | NULL | DESCONOCIDO | NO_DISPONIBLE |
| 3–8 | DISPONIBLE | NULL | DESCONOCIDO | DESCONOCIDO |

The journal high-water cursor was 548; the event table contained 548 rows and event 548 was cajon.actualizado for Cajón 1. The effective states above follow the backend precedence in which any non-DISPONIBLE operational state yields NO_DISPONIBLE; otherwise the physical state determines the effective state.

The firmware configuration maps Cajón 1 to GPIO26. Cajones 3–8 had no physical-state timestamp, but neither the static configuration nor an unknown physical reading proves that no hardware is connected. No cajón was selected as the test target because the authenticated authoritative list and physical connection status could not be confirmed.

## Browser interaction and HTTP results

- The Codex in-app browser navigated to http://127.0.0.1:3000/admin/estacionamiento and was redirected to http://127.0.0.1:3000/login. The browser showed the Smart Parking login form, not an authenticated ADMIN page. The Edge browser provider was unavailable in this session.
- An unauthenticated HTTP request to /admin/estacionamiento returned HTTP 302; /api/cajones returned HTTP 401.
- No credentials, cookies, or tokens were read or exposed. No modal was opened, no state was selected, and no PATCH was sent.

## Operational flow, persistence, events, and restoration

The required live flow is **BLOCKED** at authentication. Consequently:

- No live PATCH result is claimed.
- No persistent operational transition or NULL-reason write was attempted.
- Authoritative GET reconciliation and live effective-state display were not verified.
- No authenticated SSE stream was opened, so delivery of a new event to a live subscriber could not be verified.
- No restoration call was needed because this execution made no persistent state change.

After the isolated regression checks, the persistent database still had the same eight operational and physical states, reason values, effective states, and timestamps as the initial snapshot. Cursor 548, event count 548, and latest event ID 548 were unchanged. This verifies that the checks added no event or state change to the persistent development database; it does not verify a transition event.

## Focused regression checks

- **PASS — API, 19 tests:** podman exec api-dev /opt/venv/bin/pytest -q tests/test_cajones.py tests/test_migracion_cajones.py. Coverage includes reasonless MANTENIMIENTO and FUERA_DE_SERVICIO mutations, rejection of a non-null reason for DISPONIBLE, effective-state precedence, event/no-op behavior, and the optional-reason migration. API test fixtures create and remove isolated temporary databases; the persistent development database remained unchanged.
- **PASS — Web, 40 tests:** podman exec web-dev pnpm exec node --test --experimental-strip-types tests/cajones.test.ts tests/eventos-tiempo-real.test.ts tests/server-proxy-security.test.ts. Coverage includes optional-reason normalization, available-state validation, event snapshot reconciliation, proxy allow-listing, and the layout-owned single EventSource subscription architecture.
- **PASS WITH LIMITATION — physical state is read-only in the ADMIN UI source:** the modal renders “Estado físico · solo lectura”; source inspection found no physical-state input or select binding. An authenticated browser check of the rendered UI was blocked.
- No repository source, configuration, or test files were changed by this execution. The working tree was already dirty; its pre-report status matched the post-test status, and those pre-existing changes were preserved. The only repository file created by this execution is this report. No staging, commit, push, reset, or checkout was performed.
- CodeGraph was not synchronized because no indexed repository files were changed and no post-change graph query was needed.

## Remaining limitations

A real authenticated ADMIN browser session is required to retrieve the authoritative list, select a safe cajón, submit a blank-reason operational change, verify FastAPI and persistent PostgreSQL behavior, observe exactly one meaningful event through the existing SSE subscription, and restore the original operational state. Those actions remain unperformed. The focused regression tests pass but do not substitute for that live acceptance.

## Result

The development database and event history remain intact, and the focused API and Web regressions pass. Phase 6C final acceptance cannot be completed without the authenticated browser flow, live persistence verification, event delivery evidence, and restoration.

ACCEPTANCE BLOCKED

