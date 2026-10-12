# Sprint 3 Phase 5B SSE Acceptance Closure

- Project: Smart Parking
- Sprint: 3
- Mode: SSE Acceptance Closure
- Acceptance date: 2026-10-07 (America/Mexico_City)
- Final verdict: ACCEPTANCE BLOCKED

## Authoritative evidence

- reports/sprint-3-phase-5b-final-acceptance-20261007-211937.md
- reports/sprint-3-phase-5a-integration-execution-20261007-205554.md
- reports/sprint-3-phase-5-end-to-end-integration-plan-20261007-203544.md
- reports/sprint-3-parking-slots-backend-execution-20261006-232755.md

The completed Phase 5B physical transition cases were not repeated. This closure addresses only the two outstanding SSE criteria.

## Scope and preservation

This was a read-only acceptance closure. No firmware, API, Nuxt, SSE, authentication, database, infrastructure, network, or device source was changed. The sensor was not moved, no service was restarted, and no SQL mutation or Git write was performed. The pre-existing dirty worktree was preserved.

CodeGraph reported 166 files, 2,982 nodes, and 8,666 edges, with its index up to date. No source changes had occurred since the prior Phase 5B report, so no index synchronization was needed.

No password, cookie, session identifier, device token, or private account identity is included here.

## Preflight and authenticated role

- api-dev, web-dev, and postgres were running; PostgreSQL was healthy.
- Windows API health returned HTTP 200; the existing Nuxt login page returned HTTP 200.
- Alembic reported revision 20261006_0001 (head).
- The existing browser remained on /admin and showed the ADMIN role. Its session was still active.
- The API route, Nuxt BFF, EventSource controller, Cajón parser, and focused tests were inspected. Their file timestamps predate the authoritative Phase 5B report.

## Implementation contract inspected

FastAPI validates the staff session and cursor before reserving an SSE lease. The generator emits retained records as ServerSentEvent values: the journal ID is the SSE id, the event type is the SSE event, and the JSON data envelope contains recurso_tipo, recurso_id, ocurrido_en, and the persisted snapshot under datos. Its finally path closes the lease.

The Nuxt BFF at apps/web/server/api/eventos.get.ts delegates to proxyEventos. The BFF forwards the request cookie and cursor to FastAPI, requires a successful text/event-stream response to stream, forwards the response incrementally, and aborts the upstream fetch when the downstream connection closes.

The existing browser controller validates the decimal lastEventId, allowed event type, recurso_tipo, positive recurso_id, and Cajón snapshot schema. For cajon.actualizado, it deduplicates by cursor, buffers accepted events, and invokes the optional alActualizarCajon handler; a later subscriber can receive the buffered event.

## Selected retained database event

A read-only PostgreSQL transaction selected retained Cajón event 300 and cursor 299, which is the immediately preceding cursor. The global journal high-water was 300.

- ID: 300
- Type: cajon.actualizado
- Resource: cajon, ID 1
- occurred_en: 2026-10-08 03:13:02.817155+00:00
- Persisted snapshot: cajon_id 1, numero 1, estado_fisico LIBRE, estado_operativo DISPONIBLE, motivo_operativo null, estado_efectivo LIBRE
- estado_fisico_actualizado_en and actualizado_en: 2026-10-08T03:13:02.818201+00:00
- estado_operativo_actualizado_en: 2026-10-07T05:21:59.342494+00:00

The serialization contract implies an SSE frame with id 300, event cajon.actualizado, and the envelope and snapshot above. This is the expected comparison reference, not a captured browser frame.

## Criterion 11 — authenticated Nuxt BFF SSE replay

The previous Phase 5B report records an authenticated cursor 297 request reaching FastAPI through the BFF with HTTP 200 and a lease that closed 37 ms after opening. That proves the prior request and cleanup, but its body frame was not visible. Direct navigation to the stream had returned ERR_BLOCKED_BY_CLIENT.

For this closure, the browser stayed on its authenticated /admin page. The documented browser APIs exposed no Network or DevTools stream inspection capability. The documented page evaluator was checked for the executor-preferred same-origin fetch plus ReadableStream alternative; it reported fetchAvailable=false. No fetch request was issued by that evaluator, and no new SSE lease was created. The browser’s normal ADMIN page was left intact.

No actual text/event-stream frame for cursor 299 was captured. Therefore the live event ID, type, resource, timestamp, and snapshot cannot be compared with event 300. HTTP 200 and source serialization do not meet the executor’s required live-frame proof.

**Criterion 11: NOT VERIFIED.**

## Criteria 12 and 13 — parser and callback contract

The current focused Web test file was run inside the existing web-dev container:

- Command: node --test --experimental-strip-types tests/eventos-tiempo-real.test.ts
- Result: 10 tests passed, 0 failed.

The focused tests cover valid Cajón parsing and schema rejection, resource and snapshot consistency, duplicate-ID suppression, cursor and buffer behavior, and dispatch of cajon.actualizado to alActualizarCajon. The specific callback test confirms a valid event is delivered once despite a duplicate ID and is replayed to a later subscriber from the buffer.

This is test-based evidence using the existing test event source and fixture; it is not a live browser parser or callback observation, and it is not a replay of database event 300. The Estacionamiento page does not yet subscribe to the callback, as that consumer belongs to Phase 6.

- Criterion 12: PASS — VERIFIED BY FOCUSED TESTS.
- Criterion 13: PASS — VERIFIED BY TESTS. The reusable dispatch contract passes; no live page consumer was claimed.

## Cursor, cleanup, and database preservation

The focused tests passed cursor validation, duplicate suppression, and buffer replay cases. The prior Phase 5B bounded API replay lease remains closed. The final read-only lease query showed the same two pre-existing unexpired ADMIN layout leases as before this closure; no new lease was added and the normal page streams were not disrupted.

The final read-only database query confirmed:

- Global high-water remains 300.
- Events 299 and 300 remain intact with their original Cajón 1 snapshots.
- Exactly two journal rows exist after ID 298; both are the original transition events, with no replay-generated row or duplicate.
- Cajón 1 remains LIBRE / DISPONIBLE / LIBRE.
- Cajones 2–8 remain DESCONOCIDO / DISPONIBLE / DESCONOCIDO.

## Updated 26-criterion assessment

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 01 | Device/API connectivity | PASS — PRIOR VERIFIED EVIDENCE | Phase 5B physical API requests returned HTTP 200; API health is 200. |
| 02 | Physical GPIO mapping | PASS — PRIOR VERIFIED EVIDENCE | Phase 4 acceptance verified GPIO26, active-low mapping, and 200 ms polling. |
| 03 | Initial synchronization | PASS — PRIOR VERIFIED EVIDENCE | Phase 5B began with user-confirmed and persisted LIBRE state. |
| 04 | LIBRE to OCUPADO | PASS — PRIOR VERIFIED EVIDENCE | User-directed transition produced event 299 and matching row. |
| 05 | OCUPADO to LIBRE | PASS — PRIOR VERIFIED EVIDENCE | User-directed transition produced event 300 and matching row. |
| 06 | API acknowledgement | PASS — PRIOR VERIFIED EVIDENCE | Both physical requests returned 200 and the firmware contract validates acknowledgement identity and state. |
| 07 | PostgreSQL consistency | PASS | Final row and retained event snapshots for 299 and 300 agree. |
| 08 | Atomic event persistence | PASS — PRIOR VERIFIED EVIDENCE | Backend execution tests establish transactional state and event persistence. |
| 09 | Correct event snapshot | PASS | Event 300 snapshot remains LIBRE / DISPONIBLE / LIBRE with persisted timestamps. |
| 10 | Authenticated FastAPI SSE | PASS — PRIOR VERIFIED EVIDENCE | Prior authenticated requests and bounded replay reached FastAPI with HTTP 200. |
| 11 | Authenticated Nuxt BFF replay frame | NOT VERIFIED | No live frame could be consumed or compared; the available page evaluator has no fetch, and browser Network/DevTools inspection is unavailable. |
| 12 | Browser EventSource parser | PASS — VERIFIED BY FOCUSED TESTS | Current focused suite validates Cajón parsing, schema, resource consistency, cursor, and duplicate handling. |
| 13 | alActualizarCajon callback contract | PASS — VERIFIED BY TESTS | Current focused suite verifies delivery, deduplication, and buffered delivery; no live consumer was claimed. |
| 14 | SSE cursor and replay behavior | PASS — VERIFIED BY FOCUSED TESTS | Current focused tests cover cursor handling, duplicate suppression, and buffered replay. |
| 15 | No duplicate persisted event | PASS | High-water remains 300; only original events 299 and 300 follow ID 298. |
| 16 | Stable-state request suppression | PASS — PRIOR VERIFIED EVIDENCE | Prior 15-second physical stability interval produced no extra PUT or journal event. |
| 17 | API outage recovery | PASS — PRIOR VERIFIED EVIDENCE | Phase 4 recovery acceptance. |
| 18 | Wi-Fi recovery | PASS — PRIOR VERIFIED EVIDENCE | Phase 4 recovery acceptance. |
| 19 | Latest-state convergence | PASS — PRIOR VERIFIED EVIDENCE | Phase 4 recovery acceptance. |
| 20 | Soft-reboot reconciliation | PASS — PRIOR VERIFIED EVIDENCE | Phase 4 recovery acceptance. |
| 21 | Cold power-on startup | PASS — PRIOR VERIFIED EVIDENCE | Later cold-boot analysis; its serial transcript limitation remains documented. |
| 22 | Operational-state independence | PASS — PRIOR VERIFIED EVIDENCE | Prior backend/runtime evidence; current state remains DISPONIBLE. |
| 23 | Effective-state precedence | PASS — PRIOR VERIFIED EVIDENCE | Prior backend tests and runtime evidence. |
| 24 | Device/staff authentication separation | PASS — PRIOR VERIFIED EVIDENCE | Prior backend tests and live rejection cases; no device bearer was used for staff SSE. |
| 25 | Unconnected slot integrity | PASS | Final read-only query confirms Cajones 2–8 remain unchanged. |
| 26 | Final hardware/backend agreement | PASS — PRIOR VERIFIED EVIDENCE | User confirmed final physical LIBRE and stable; the retained database state remains LIBRE. |

## Phase 6 readiness

The callback dispatch contract is now verified by focused tests, and the missing Estacionamiento page subscriber does not independently block the gate. Phase 6 is still blocked because criterion 11 requires direct observation of the authenticated Nuxt BFF replay frame and comparison against retained PostgreSQL event 300. No product defect was reproduced. Do not begin Phase 6 from this closure record.

## Final verdict

ACCEPTANCE BLOCKED
