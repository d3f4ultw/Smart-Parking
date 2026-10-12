# Sprint 3 Phase 5B Final End-to-End Acceptance

- Project: Smart Parking
- Sprint: 3
- Mode: Execution — Phase 5B
- Acceptance date: 2026-10-07 (America/Mexico_City)
- Final verdict: ACCEPTANCE BLOCKED

## Authoritative reports

- reports/sprint-3-phase-5-end-to-end-integration-plan-20261007-203544.md
- reports/sprint-3-phase-5a-integration-execution-20261007-205554.md
- reports/sprint-3-esp32-phase-4-live-acceptance-20261007-193549.md
- reports/sprint-3-esp32-cold-boot-analysis-20261007-200710.md
- reports/sprint-3-esp32-phase-4-recovery-execution-20261007-184246.md
- reports/sprint-3-parking-slots-backend-execution-20261006-232755.md

The Phase 5A work was not repeated. Historical Phase 4, backend, parser, recovery, and cold-boot evidence was reused where the task allowed it.

## Scope and preservation

This was an acceptance run only. No firmware, API, Nuxt, database schema, SSE, authentication, Compose, network, firewall, router, secret, or boot-file source was changed. No SQL mutation was performed; database inspections used BEGIN READ ONLY and ended with ROLLBACK. The two physical transitions below were initiated by the user and their resulting journal events were retained.

The worktree was already dirty before this run. Its modified, deleted, and untracked files were preserved. No Git add, commit, push, reset, or checkout was run. CodeGraph was inspected and reported current, so it was not synchronized.

No password, bearer token, cookie, session identifier, device secret, or private login identity was recorded.

## Login and authorized role

The user completed login through the existing visible Nuxt login page. The protected /admin page loaded and identified the current authorized role as ADMIN. The existing session-cookie flow was preserved; no account was created and no role was fabricated.

The ADMIN layout starts its existing event controller in onMounted. The controller uses credentialed EventSource and the same-origin /api/eventos path. API access logs recorded successful GET /api/eventos requests from that protected session.

## Preflight and runtime baseline

- api-dev, web-dev, and postgres were running; PostgreSQL was healthy.
- Windows http://127.0.0.1:8000/health returned HTTP 200 with {"status":"healthy"}. The Nuxt login page returned HTTP 200.
- The database revision was 20261006_0001, matching the repository head.
- PortProxy remained 192.168.137.1:8000 -> 127.0.0.1:8000; Windows Test-NetConnection to 192.168.137.1:8000 succeeded.
- Firmware configuration remained API_BASE_URL = http://192.168.137.1:8000, Cajón 1 -> GPIO26, active-low (0 = OCUPADO, 1 = LIBRE), with a configured 200 ms polling interval. ParkingSensor.is_occupied() still maps pin value 0 to occupied.
- SHA-256 values for the five Phase 4 runtime modules (api_client.py, config.py, main.py, parking_controller.py, wifi_manager.py) matched the Phase 4 live-acceptance report.
- CodeGraph reported current: 166 files, 2,982 nodes, 8,666 edges.

The initial user-confirmed physical position was LIBRE and stable. A read-only database snapshot showed Cajón 1 LIBRE / DISPONIBLE / LIBRE, with estado_fisico_actualizado_en = 2026-10-07 20:52:47.661967 -06:00. Cajones 2–8 were each DESCONOCIDO / DISPONIBLE / DESCONOCIDO. The global and Cajón event high-water marks were both 298. Event 298 was a retained cajon.actualizado for Cajón 1 with the same state snapshot. The last physical PUT before the test sequence returned HTTP 200 at 20:52:47.676 -06:00; no extra baseline movement or event was generated.

## Authenticated SSE and bounded replay

A single same-origin request to /api/eventos?cursor_eventos=297 was attempted in the visible authenticated browser. FastAPI access logs recorded GET /api/eventos?cursor_eventos=297 with HTTP 200 at 21:08:21.906 -06:00. The retained event immediately after that cursor was event 298. The Nuxt BFF source forwards the incoming session cookie and cursor, streams the upstream text/event-stream body, and aborts upstream work when the downstream response closes. A read-only lease query recorded the replay lease opening at 21:08:21.885948 UTC and closing at 21:08:21.922973 UTC, 37 ms later. The replay lease was closed; it did not remain as an unfinished test stream.

The browser tool returned ERR_BLOCKED_BY_CLIENT when asked to display the SSE endpoint as a page. Thus, the authenticated request, cursor, upstream HTTP 200, and cleanup are verified, but the exact response frame was not captured from the browser and could not be compared byte-for-byte with event 298. The upstream event row and snapshot are known from PostgreSQL; the API generator emits retained rows after the requested cursor. Because the live browser frame itself was not observable, acceptance criterion 11 remains NOT VERIFIED.

The existing Web parser has prior verified test evidence: the backend execution report records 86 passing Web tests, including focused cajon.actualizado parsing, validation, cursor, duplicate suppression, and alActualizarCajon dispatch/buffer replay cases. The current browser console showed zero warnings and zero errors. The current ADMIN layout does not subscribe a parking view to alActualizarCajon (that consumer is Phase 6), and safe runtime callback instrumentation was unavailable, so criterion 13 is NOT VERIFIED.

Two active SSE leases were present in the final read-only count; both predated the bounded cursor replay and corresponded to the protected layout's earlier /api/eventos requests. The bounded replay lease itself was confirmed closed.

## Physical transition acceptance

### Test A — initial LIBRE baseline

The user confirmed the sensor was secured, stable, and physically clear. PostgreSQL was LIBRE / DISPONIBLE / LIBRE, matching the latest acknowledged state. No extra physical PUT or duplicate event was generated before the deliberate movement.

### Test B — LIBRE to OCUPADO

The user placed the object once and left it in place until the transition was recorded.

- API access log: PUT /api/cajones/1/estado-fisico, HTTP 200 at 21:12:00.373 -06:00.
- PostgreSQL: Cajón 1 became OCUPADO / DISPONIBLE / OCUPADO.
- One new event was persisted: ID 299, cajon.actualizado, resource type cajon, resource ID 1.
- Event snapshot: Cajón 1, physical OCUPADO, operational DISPONIBLE, effective OCUPADO; actualizado_en = 21:12:00.356016 -06:00, matching the persisted row timestamp.
- Global/Cajón event high-water advanced 298 -> 299.

### Test C — OCUPADO to LIBRE

Only after Test B was recorded, the user removed the object once.

- API access log: PUT /api/cajones/1/estado-fisico, HTTP 200 at 21:13:02.829 -06:00.
- PostgreSQL: Cajón 1 returned to LIBRE / DISPONIBLE / LIBRE.
- One new event was persisted: ID 300, cajon.actualizado, resource type cajon, resource ID 1.
- Event snapshot: Cajón 1, physical LIBRE, operational DISPONIBLE, effective LIBRE; actualizado_en = 21:13:02.818201 -06:00, matching the persisted row timestamp.
- Global/Cajón event high-water advanced 299 -> 300.

The API logs exposed only HTTP status, not response bodies. The unchanged Phase 4 client validates the acknowledged Cajón ID and exact physical state before advancing its acknowledgement. The 200 responses, matching durable transitions, and quiet stable interval support successful acknowledgements; no raw REPL access was used to inspect device memory.

### Test D — stable state

The sensor remained unchanged for a bounded 15-second interval after event 300. During that interval:

- No additional physical PUT was logged.
- Global and Cajón event high-water stayed at 300.
- Cajón 1 stayed LIBRE / DISPONIBLE / LIBRE.
- Its physical timestamp did not change.
- Cajones 2–8 remained DESCONOCIDO / DISPONIBLE / DESCONOCIDO.

At final review, the user confirmed the sensor remained secured and physically LIBRE.

## Persistence, recovery, operational-state, and authorization evidence

Events 299 and 300 each correspond to one meaningful physical transition; each persisted snapshot agrees with its committed Cajón row. estado_operativo stayed DISPONIBLE; effective state matched the backend-derived physical state. The 15-second steady interval produced no duplicate request or event.

Prior verified evidence was reused for transaction atomicity/rollback, same-state idempotency, effective-state precedence, operational-state independence, ADMIN/OPERADOR event filtering, device/staff credential separation, and invalid-credential rejection. No current operational state was changed merely to repeat those cases. The device bearer was not read or disclosed.

Phase 4 live evidence remains valid because firmware hashes were unchanged: API outage recovery, Wi-Fi recovery, latest-state convergence, soft-reboot reconciliation, and stable-state suppression passed in the live report. The later cold-boot analysis observed normal power-on startup, connected WLAN, acknowledged initial synchronization, and no required boot.py change. Its missing initial serial transcript remains a historical limitation; this run did not repeat a power cycle, hotspot interruption, service outage, or raw-REPL inspection.

## Acceptance matrix

| # | Criterion | Status | Evidence |
|---:|---|---|---|
| 01 | Device/API connectivity | PASS | API health 200; both user-coordinated physical PUTs returned 200. |
| 02 | Physical GPIO mapping | PASS — PRIOR VERIFIED EVIDENCE | GPIO26 active-low mapping and 200 ms poll configuration; runtime module hashes match Phase 4. |
| 03 | Initial synchronization | PASS | User-confirmed LIBRE; DB LIBRE; prior physical PUT 200; no extra baseline transition/event. |
| 04 | LIBRE -> OCUPADO | PASS | User placed object; API 200; row and event 299 snapshot became OCUPADO. |
| 05 | OCUPADO -> LIBRE | PASS | User removed object; API 200; row and event 300 snapshot became LIBRE. |
| 06 | API acknowledgement | PASS | Physical PUTs returned 200; unchanged client validates matching ID/state before acknowledging. |
| 07 | PostgreSQL consistency | PASS | Rows and snapshots for events 299 and 300 agree; final row is LIBRE. |
| 08 | Atomic event persistence | PASS — PRIOR VERIFIED EVIDENCE | Backend execution tests cover transactional state/event behavior; each live transition produced one durable event. |
| 09 | Correct event snapshot | PASS | Persisted event snapshots 299 and 300 match their corresponding committed rows and timestamps. |
| 10 | Authenticated API SSE | PASS | Protected ADMIN stream requests returned 200; earlier ADMIN/OPERADOR authenticated API replay was also verified. |
| 11 | Authenticated Nuxt BFF replay | NOT VERIFIED | Cursor 297 reached the authenticated upstream through the BFF and returned 200; browser tool blocked display before the event frame could be captured and compared. |
| 12 | Browser EventSource parsing | PASS — PRIOR VERIFIED EVIDENCE | Existing Web tests cover valid cajon.actualizado parsing and rejection of invalid payloads; current protected layout opened the credentialed stream. |
| 13 | alActualizarCajon delivery | NOT VERIFIED | No Phase 6 parking subscriber exists; browser callback instrumentation was unavailable without source modification. |
| 14 | SSE cursor/replay behavior | PASS — PRIOR VERIFIED EVIDENCE | Existing cursor/replay and duplicate-cursor tests passed; live cursor 297 request was accepted with HTTP 200. |
| 15 | No duplicate persisted event | PASS | Exactly one event (299, 300) per deliberate transition; no extra event during stability. |
| 16 | Stable-state request suppression | PASS | No further physical PUT or event during the 15-second stable interval. |
| 17 | API outage recovery | PASS — PRIOR VERIFIED EVIDENCE | Phase 4 live acceptance. |
| 18 | Wi-Fi recovery | PASS — PRIOR VERIFIED EVIDENCE | Phase 4 live acceptance. |
| 19 | Latest-state convergence | PASS — PRIOR VERIFIED EVIDENCE | Phase 4 live acceptance. |
| 20 | Soft-reboot reconciliation | PASS — PRIOR VERIFIED EVIDENCE | Phase 4 live acceptance. |
| 21 | Cold power-on startup | PASS — PRIOR VERIFIED EVIDENCE | Later cold-boot analysis; initial serial transcript limitation retained. |
| 22 | Operational-state independence | PASS — PRIOR VERIFIED EVIDENCE | Prior runtime acceptance and tests; current transitions left DISPONIBLE intact. |
| 23 | Effective-state precedence | PASS — PRIOR VERIFIED EVIDENCE | Prior backend runtime/tests validated precedence rules. |
| 24 | Device/staff authentication separation | PASS — PRIOR VERIFIED EVIDENCE | Prior backend tests and live rejection cases; no bearer exposed or reused for staff SSE. |
| 25 | Unconnected slot integrity | PASS | Current read-only query confirmed Cajones 2–8 remain DESCONOCIDO / DISPONIBLE / DESCONOCIDO. |
| 26 | Final hardware/backend agreement | PASS | User confirmed final physical LIBRE; DB row and event 300 are LIBRE; matching API PUT returned 200. |

## Final state and Phase 6 readiness

Final user-confirmed sensor state: LIBRE and stable. Final PostgreSQL state: Cajón 1 LIBRE / DISPONIBLE / LIBRE, event 300, high-water 300. Cajones 2–8 remain unknown and available operationally. API health, Nuxt HTTP response, PostgreSQL health, and PortProxy reachability passed at final review. No controlled outage or test replay stream remained active.

Phase 6 is not ready to start from this acceptance record because criterion 11's actual replay frame was not visible for direct comparison with event 298. This is an observation limitation of the available browser surface, not a reproduced product defect. Criterion 13 also remains unverified because the Phase 6 subscriber does not yet exist. A follow-up should capture one bounded replay frame in a browser inspection surface that can read text/event-stream, verify its ID/type/resource/snapshot against the retained row, and, if needed, observe callback delivery through a temporary non-source runtime instrument.

## Final verdict

ACCEPTANCE BLOCKED
