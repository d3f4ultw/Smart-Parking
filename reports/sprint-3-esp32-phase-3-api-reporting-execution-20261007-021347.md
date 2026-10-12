# Sprint 3 ESP32 Phase 3 — Physical State API Reporting Execution

Date: 2026-10-07 (America/Mexico_City)

## Objective

Connect the verified GPIO26 sensor state for configured Cajón 1 to the existing FastAPI physical-state endpoint. Validate the device acknowledgement and persisted cajon.actualizado events while preserving the existing sensor and Wi-Fi behavior.

## Scope

- Phase 3 firmware reporting for the single configured slot, Cajón 1 on GPIO26.
- Live verification on the ESP32, the existing local API, and PostgreSQL.
- Phase 4 retry, offline recovery, pending-state storage, and eventual convergence remain out of scope.
- No backend, Web, SSE, schema, infrastructure, router, firewall, or network configuration changes were made for this phase.
- No database reset or event deletion was performed. No Git stage, commit, push, reset, or checkout was performed.

## Work performed

- Rechecked the existing device and backend before reporting. The ESP32 runs MicroPython 1.28.0, Wi-Fi connected using the configured local URL, the device reached GET /health with HTTP 200, and migration 20261006_0001 was at repository head.
- Inspected the board's installed urequests/ujson capabilities. The board supports put, generic request, JSON serialization/parsing, response status, and response close. The device client uses a two-second request timeout.
- Reconciled the development device bearer without printing the credential. The ignored local secrets.py, API configuration, and board copy matched using in-memory fingerprints. The valid bearer was accepted by the physical-state route; an invalid synthetic bearer returned 401. The device bearer was also rejected by the staff route with 401.
- Implemented the reusable API client, injected one client into the configuration-driven controller, and connected startup in main.py. The controller reports the initial state and physical transitions, continues local monitoring after a request failure, and does not resend on unchanged scans.
- Preserved the Phase 2 source snapshot at tmp/esp32-baseline/phase2-20261007-015656. Existing sensor, slot configuration, Wi-Fi manager, and device boot.py were left unchanged.
- Uploaded only the intended firmware source files and the ignored local device credentials. The uploaded sources were compared against the repository copies.

## Changes

- firmware/esp32/parking_slot/api_client.py now sends authenticated JSON PUT requests to /api/cajones/{cajon_id}/estado-fisico, validates the returned slot ID, state, and Boolean cambio_aplicado, classifies success and safe error categories, and closes responses in all paths.
- firmware/esp32/parking_slot/parking_controller.py sends one report for an initial reading or actual state transition and prints synchronization only after a matching acknowledgement.
- firmware/esp32/parking_slot/main.py loads the local bearer, creates one API client, and injects it into the existing configured sensor/controller startup.
- firmware/esp32/parking_slot/secrets.pyi declares ESP32_BEARER_TOKEN for editor type checking.
- firmware/esp32/parking_slot/secrets.py was updated locally with the device credential. It is ignored by Git; its contents are not included here.
- secrets.example.py already contained the blank token placeholder and was not changed. parking_sensor.py, config.py, wifi_manager.py, boot.py, backend source, Web source, and infrastructure were not changed for this phase.

## Validation

### Host checks

- PASS: 33 focused host-side checks covering URL and Boolean body construction, authorization/content-type headers, matching OCUPADO/LIBRE acknowledgements including cambio_aplicado=false, malformed or mismatched responses, HTTP status classification, transport failures, response closure, and controller initial/transition/unchanged behavior.
- PASS: Generic slot ID behavior was checked with an ID other than 1. No retry/pending-state behavior or direct HTTP dependency was added to the controller.
- PASS: CodeGraph was synchronized after the firmware changes. codegraph status reported the index up to date (166 files, 2,963 nodes, 8,575 edges); focused queries confirmed the main.py → ParkingController → ApiClient call path and no firmware imports into backend or Web internals.

### Device and API checks

- PASS: Device /health returned HTTP 200 using the configured API URL.
- PASS: Initial LIBRE report was acknowledged with no state change; Cajón 1 remained LIBRE and the event high-water remained 272.
- PASS: The real API authenticated the device route and kept the staff/device authentication boundary: invalid device bearer on the device route returned 401, and device bearer on the staff route returned 401.
- PASS: Local source and uploaded device files matched for the intended firmware modules. Wi-Fi settings were preserved.

### Physical acceptance

The user deliberately moved the object during the sensor sequence. Every recorded state transition was acknowledged by the API:

| Event ID | Reported state |
|---:|---|
| 273 | OCUPADO |
| 274 | LIBRE |
| 275 | OCUPADO |
| 276 | LIBRE |
| 277 | OCUPADO |
| 278 | LIBRE |

- PASS: Final Cajón 1 state in PostgreSQL is LIBRE; latest event ID is 278.
- PASS: In the guided final check, the ESP32 printed Cajón 1: LIBRE followed by Cajón 1: API sincronizada.
- PASS: After the user held the sensor steady for five seconds, the serial monitor produced no additional line and the database remained at LIBRE with event high-water 278.
- The monitor remains connected on COM5 so the user can continue observing the board.

## Limitations / unresolved items

- The board returned a transport OSError after approximately 2.316 seconds when connecting to a non-responsive local test port. This supports bounded connect-failure behavior for the tested path. A delayed response-body timeout against a reachable stalled HTTP server was not verified; an attempted temporary listener did not accept the board connection. No network settings were changed.
- A cold power-up was not tested; the firmware was started with one controlled soft reset.
- Phase 3 is synchronous and has no retry or startup reconciliation. If an API request fails, the controller retains local sensor state and reports again only on a later physical transition. Phase 4 must implement recovery before claiming eventual convergence.
- The configured bearer travels over plain HTTP on the local development network. Keep it on a trusted network; this setup is not suitable for an untrusted network.
- Acceptance covered Cajón 1 only.

## Result

The ESP32 now reports physical state changes to the existing API, receives and validates acknowledgements, and leaves both device and API in LIBRE after the guided physical sequence. All six deliberate state transitions produced the expected persisted event, and the final five-second stability check produced no duplicate report.

IMPLEMENTED — READY WITH CAVEATS
