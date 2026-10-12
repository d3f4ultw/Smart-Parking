# Sprint 3 Phase 5A End-to-End Integration Execution

- Project: Smart Parking
- Sprint: 3
- Mode: Execution — Phase 5A
- Date: 2026-10-07 20:55:54 America/Mexico_City
- Authoritative plan: reports/sprint-3-phase-5-end-to-end-integration-plan-20261007-203544.md
- Supporting reports: Phase 3 API reporting, Phase 4 live acceptance, Phase 4 cold-boot analysis, and parking-slot backend execution reports listed below.

## Objective and scope

Confirm the existing Cajón 1 path from GPIO26 through the ESP32, authenticated FastAPI endpoint, PostgreSQL event journal, and the existing staff SSE/Nuxt transport. This execution made no firmware, backend, Web, configuration, schema, database, network, or Git changes. It did not connect to the serial REPL, reset or power-cycle the ESP32, generate a physical transition, or start Phase 5B.

The user reported that the sensor had fallen again, then confirmed it was secured and stable. I did not handle or reposition the hardware. Database reads ran in READ ONLY transactions followed by ROLLBACK.

## Preflight and current runtime baseline

- api-dev, postgres, and web-dev were running. PostgreSQL reported healthy.
- GET http://127.0.0.1:8000/health returned {"status":"healthy"}.
- Windows PortProxy remained 192.168.137.1:8000 -> 127.0.0.1:8000; Test-NetConnection 192.168.137.1 -Port 8000 returned True. Compose still publishes the API on loopback 127.0.0.1:8000.
- Firmware API_BASE_URL remains http://192.168.137.1:8000. PARKING_SLOTS contains only (1, 26); POLL_INTERVAL_MS remains 200.
- Database migration head is 20261006_0001, matching the repository migration head.
- Final read-only database snapshot at 20:55:53 -06:00: Cajón 1 is LIBRE / DISPONIBLE / LIBRE; Cajones 2–8 are DESCONOCIDO / DISPONIBLE / DESCONOCIDO. Cajón 1 physical timestamp is 2026-10-08 02:52:47.661967+00 (20:52:47 -06:00).
- Global event high-water, highest retained event, and highest retained Cajón event are all 298. Event 298 is cajon.actualizado for Cajón 1. Its physical, operational, effective-state, and timestamp snapshot matches the persisted Cajón 1 row.

## Sensor movement and stable-state smoke

The journal contains two pairs of persisted physical changes: event 295 OCUPADO and 296 LIBRE at 20:51:47–20:51:48 -06:00; event 297 OCUPADO and 298 LIBRE at 20:52:43–20:52:47 -06:00. Each event snapshot agrees with its committed state. The user reported that the sensor had fallen; this is consistent with the transitions, but no serial observation was made to independently establish their physical cause. These alternating state changes are not classified as duplicate same-state event spam.

After the user confirmed the sensor was secured and stable, a passive 15-second observation began from high-water 298 and Cajón 1 LIBRE. At the end, the high-water remained 298, Cajón 1 remained LIBRE / DISPONIBLE, and API health remained healthy. A redacted access-log scan covering the baseline and observation found zero Cajón 1 physical PUT requests. No new event or repeated PUT was observed in this stable interval.

## Integration verdict matrix

| # | Integration link | Status | Evidence and limit |
|---:|---|---|---|
| 1 | IR output → GPIO26 | CONNECTED | Current config maps only Cajón 1 to GPIO26; Phase 4 physical acceptance is historical hardware evidence. |
| 2 | GPIO26 → ParkingSensor | CONNECTED | Current active-low read maps 0 to occupied and 1 to free; user reports the sensor is now secured. No direct electrical/serial reading was taken in 5A. |
| 3 | ParkingSensor → ParkingController | CONNECTED | Current main.py constructs a sensor per configured slot and injects them into the controller; Phase 4 cold-boot report records startup acknowledgement. |
| 4 | ParkingController → ApiClient | CONNECTED | Current source and focused CodeGraph exploration show controller-to-client wiring and per-slot pending/acknowledged state. |
| 5 | ApiClient → authenticated physical PUT | CONNECTED | Two current Cajón 1 PUT access-log entries returned HTTP 200 before the stable interval; persisted event snapshots show matching transitions. The stable interval had zero PUTs. |
| 6 | PUT → FastAPI authentication and validation | CONNECTED | Current route requires device authentication and strict Boolean ocupado; current successful requests and prior Phase 3 valid/invalid credential checks support the contract. |
| 7 | FastAPI route → state service | CONNECTED | Current route delegates to cambiar_estado_fisico; current successful requests reached the persisted state path. |
| 8 | State service → PostgreSQL | CONNECTED | Current row and timestamp are persisted; physical and operational fields remain distinct. |
| 9 | Physical transition → event journal | CONNECTED | Events 295–298 contain one matching cajon.actualizado snapshot per recorded physical state change; event 298 matches the current row. |
| 10 | Event journal → authenticated API SSE | PARTIALLY CONNECTED | Current replay, cursor, retention/resync, and ADMIN/OPERADOR role paths are present and covered by existing tests. A fresh authenticated replay was unavailable because no staff session was open. |
| 11 | API SSE → Nuxt BFF | PARTIALLY CONNECTED | Current BFF forwards the cookie and cursor, preserves no-store, and aborts upstream work on disconnect; existing tests cover this. No authenticated live BFF stream was opened. |
| 12 | Nuxt BFF → browser EventSource parser | PARTIALLY CONNECTED | Current parser validates cajon.actualizado payloads and cursor identity; existing parser/BFF tests cover stream handling. No authenticated browser stream was available. |
| 13 | Parser → alActualizarCajon | PARTIALLY CONNECTED | The callback interface and dispatch are present and covered by parser tests. A live browser callback was not observed; the Estacionamiento page has no consumer yet by design. |
| 14 | Device network path | CONNECTED | Current Windows forwarding check passed and current physical PUTs returned 200 through the API. The ESP32 DHCP address remains dynamic. |
| 15 | Staff/device authentication boundary | CONNECTED | Current source keeps the device Bearer separate from cookie-based staff access; existing Phase 3 runtime checks and backend tests cover both directions. No new negative credential probe was run in this execution. |

No integration link was found missing or blocked. Links 10–13 remain partial specifically because the live authenticated replay and callback observation were not verified in this execution.

## Firmware and API contract verification

Current firmware source confirms the single-slot GPIO26 mapping, active-low polarity, 200 ms configured polling, latest-state retention, per-slot acknowledged/pending/retry state, one due request per scan, and no repeated request after a matching acknowledgement. Wi-Fi association/reconnection is bounded and does not gate local sensor polling. ApiClient sends PUT /api/cajones/{cajon_id}/estado-fisico with Boolean ocupado, a device Bearer, a bounded timeout, and response validation for HTTP 200, matching Cajón ID/state, and Boolean cambio_aplicado.

The current FastAPI schema forbids extra fields and uses strict Boolean validation. The device-only route calls cambiar_estado_fisico; the service locks the Cajón row, changes only physical state and its timestamp, records cajon.actualizado in the same transaction, and leaves operational state untouched. Same-state reports preserve timestamps and do not add events. Effective state remains backend-derived.

## SSE, Nuxt, and role boundaries

The API stream accepts Last-Event-ID or cursor_eventos, replays retained IDs in order, revalidates the staff session, applies role filters, and closes its connection lease when the iterator ends. ADMIN receives Cajón and operator events; OPERADOR receives Cajón events; unknown roles receive none. Device authentication does not authorize staff SSE.

The Nuxt /api/eventos BFF forwards only the incoming session cookie and supported cursor information to the private API URL, sets no-store/no-buffering headers, and aborts the upstream fetch on client disconnect. The EventSource controller starts from the ADMIN layout's mounted lifecycle, validates the exact Cajón snapshot, drops non-increasing IDs, and dispatches alActualizarCajon. The protected Estacionamiento page remains a heading-only shell for Phase 6.

The available in-app browser had no existing tab/session. A read-only visit to /admin redirected to /login; I closed that check tab without entering credentials. Therefore the required fresh replay through Nuxt is recorded exactly as LIVE AUTHENTICATED SSE REPLAY NOT VERIFIED. No API-only replay was substituted, and no session was fabricated or copied.

## Tests and CodeGraph

No tests were run in this execution because no source changed and the relevant current test files and prior immutable results were available. Current tests inspected cover physical auth/strict input/no-op and rollback (test_cajones.py), SSE role-filtered replay and retention (test_eventos_operadores_sse.py), Cajón parsing/callback delivery (eventos-tiempo-real.test.ts), and cookie/cursor forwarding, streaming, and disconnect cancellation (server-proxy-security.test.ts). Historical backend execution records 55 focused Cajón/migration/journal tests, 38 focused SSE tests, and 10 focused Web parser tests passing; the Phase 3 report records 33 focused host firmware checks passing. These remain historical test results, not tests run in 5A.

codegraph status reported the index current (166 files, 2,982 nodes, 8,666 edges). Focused exploration confirmed the firmware controller/client relationship, physical route/service/event writer path, and API SSE/Nuxt BFF/EventSource callers. A broad search for main also returned unrelated API CLI symbols; current source was used as the authority. No indexed source changed, so no CodeGraph sync was needed.

## Changes, preservation, and rollback

- Source/config/schema/runtime infrastructure changes: none.
- Database mutations: none; read-only transactions ended with ROLLBACK.
- Hardware resets or serial connections: none.
- Git operations: none. Pre-existing modified and untracked files remained as found; nothing was staged, committed, reset, checked out, or cleaned.
- This new report is the only artifact created for this execution. No source rollback is required.

## Phase 5B handoff and remaining limitation

Phase 5B is not started. It may proceed with the explicit requirement to perform one bounded, authenticated replay through the existing Nuxt /api/eventos path using an already-authorized ADMIN or OPERADOR session, compare the replayed retained event to PostgreSQL, observe the existing client/parser path where available, close the stream, and verify lease cleanup. The final acceptance must include this live SSE check; source or API-only tests do not replace it. Phase 5B remains responsible for its own user-coordinated physical acceptance and final hardware/backend consistency. No new UI, stream manager, endpoint, migration, or network change is indicated.

## Final verdict

**IMPLEMENTED — READY WITH CAVEATS**

The device-to-database path is connected and stable after the user reported securing the fallen sensor. The outstanding caveat is the unverified live authenticated SSE replay through the Nuxt BFF, which Phase 5B must explicitly include.