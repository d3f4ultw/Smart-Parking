# Sprint 3 ESP32 Phase 4 Recovery and Eventual Synchronization — Execution Follow-up

Date: 2026-10-07 18:42:46 America/Mexico_City  
Project: Smart Parking  
Sprint: 3  
Phase: 4  
Mode: Execution — Phase 4 only

## Previous execution record

The earlier immutable report, [`sprint-3-esp32-phase-4-recovery-execution-20261007-065156.md`](sprint-3-esp32-phase-4-recovery-execution-20261007-065156.md), records the initial preflight blocker: the ESP32 could not reach the loopback-only API binding, and implementation did not begin in that attempt. This follow-up preserves that history and records the later implementation and evidence after API reachability was established.

Authoritative plan: [`sprint-3-esp32-phase-4-recovery-plan-20261007-063540.md`](sprint-3-esp32-phase-4-recovery-plan-20261007-063540.md).

## Objective and scope

Implement the approved ESP32 Phase 4 retry, recovery, and eventual-synchronization behavior, then validate the host logic and the safe live-device startup path. No Phase 5 work was started. Backend, Web, database schema, SSE, firewall, PortProxy, Compose, and other network/infrastructure changes were outside this execution follow-up.

## Work performed

- Implemented the Phase 4 controller and Wi-Fi recovery behavior in the approved firmware scope.
- Uploaded the changed modules to the re-enumerated ESP32 on COM5 and verified the running firmware after clearing a stale Phase 3 REPL module cache with one soft reset. No hard reset or reflash was performed.
- Confirmed the ESP32 could connect to the configured host API endpoint and completed a normal startup synchronization.
- Ran an in-memory host fake validation harness and synchronized/checked CodeGraph after the source changes.

## Changes

Five firmware files were changed and uploaded:

- `firmware/esp32/parking_slot/parking_controller.py` — per-slot current and acknowledged state, pending synchronization, per-result retry deadlines, terminal error blocks, wrap-safe deadlines, latest-state replacement, one request per scan, post-request sensor reread, and round-robin fairness.
- `firmware/esp32/parking_slot/wifi_manager.py` — non-blocking station startup, connection-state tracking, and bounded reconnect attempts without exposing credentials.
- `firmware/esp32/parking_slot/main.py` — enters sensing/controller operation without waiting for Wi-Fi or using `/health` as a startup gate.
- `firmware/esp32/parking_slot/config.py` — 200 ms polling, 5,000 ms transport/server retry, 15,000 ms disabled/protocol/unexpected-response retry, and 5,000 ms reconnect interval.
- `firmware/esp32/parking_slot/api_client.py` — retryable-category metadata alignment; request validation and response closure remain in the client.

`parking_sensor.py`, `boot.py`, the secret files, backend, Web, database schema, and SSE code were not changed. The Phase 3 source snapshot is preserved at `tmp/esp32-baseline/phase3-20261007-064512/`. The six non-secret Phase 3 modules matched the captured source baseline before upload; the device `boot.py` matched its Phase 3 snapshot. The ignored `secrets.py` was not read or included in this report. Existing unrelated worktree changes were preserved; no Git add, commit, push, reset, or checkout was performed.

The API reachability mapping/rule visible during acceptance had already been configured by the user. This follow-up only verified its operation; it did not create or modify the firewall, PortProxy, Compose, or API binding configuration.

## Validation performed

### Host fake validation

`HOST_VALIDATION_PASS checks=78` using an inline/in-memory harness; no permanent host test framework or test file was added. The checks covered:

- initial/pending and acknowledged-state behavior, successful and idempotent acknowledgements, stable-state suppression, and physical changes;
- latest-value replacement while offline and the post-request sensor reread behavior;
- 5,000 ms transport/server retry and 15,000 ms disabled/protocol/unexpected-response retry, including not retrying before a deadline and retrying when due;
- terminal suppression for authentication, missing-slot, and contract failures, including persistence across later sensor changes;
- disconnected/reconnected WLAN behavior and continued local polling;
- independent fake slots, fairness when one slot fails, one request per scan, and tick-counter wraparound;
- response validation/closure, source syntax, absence of long retry sleeps, and absence of a Cajón 1-specific controller branch.

These are host fake checks, not substitutes for physical outage/recovery acceptance.

### ESP32 and API startup smoke

- USB identity: WCH CH9102 on COM5. Device runtime: MicroPython 1.28.0. Required WLAN status and wrap-safe tick APIs were present.
- At the time of the live check, ESP32 station IP was `192.168.137.28`, gateway `192.168.137.1`; the configured API was reachable at `192.168.137.1:8000`.
- A direct request from the ESP32 to `GET /health` returned HTTP 200 with `{"status":"healthy"}`.
- Normal firmware startup reported Wi-Fi connected, Cajón 1 `LIBRE`, and API synchronized with “sin cambio”. Serial output remained quiet for a further six seconds.
- PostgreSQL remained Cajón 1 `LIBRE`; the event high-water remained 278 during this unchanged-state startup check. No duplicate state event was observed in that interval.
- The GPIO26 raw input read 1, corresponding to `LIBRE` for the active-low sensor.

The quoted IP is a point-in-time observation and may change when the hotspot/DHCP lease changes.

### CodeGraph

`codegraph sync` reported five changed files synchronized. `codegraph status` reported the index current (166 files, 2,982 nodes, 8,666 edges). Focused inspection showed `main.py` wiring `WifiManager`, `ParkingController`, and `ApiClient`, with the controller calling the API client. No firmware dependency into backend or Web internals was found.

## Acceptance tests not performed

The implementation is present, but the following live acceptance checks remain explicitly unverified:

| Check | Status | Reason / remaining evidence |
|---|---|---|
| API outage and recovery | `NOT RUN` | `api-dev` was not stopped during this follow-up. Need to observe a physical change while unavailable, restore the API, then verify synchronization without another sensor edge. |
| Latest-state convergence through multiple physical changes during API outage | `NOT RUN` | No controlled outage with a sequence such as `OCUPADO → LIBRE` was performed. Need to prove only the final physical truth is sent after recovery. |
| PostgreSQL/event verification after recovery transitions | `NOT RUN` | No outage-recovery transition was generated; only unchanged startup state and event high-water 278 were observed. |
| Wi-Fi outage and reconnection | `NOT RUN` | No controlled, reversible hotspot outage was performed. Must verify sensing continues, no HTTP request is sent while disconnected, and the pending latest state synchronizes after reconnection. |
| Soft-reboot reconciliation against a deliberately mismatching backend state | `NOT RUN` | Backend state was not deliberately changed and no reboot reconciliation scenario was exercised. |
| Cold power-up | `NOT RUN` | No power cycle was performed; this remains a Phase 5 caveat if it cannot be safely tested. |
| Live terminal API-error suppression | `NOT RUN` | Terminal categories were exercised only with host fakes; no live 401, 404, or 422 response was induced. |
| HTTP response-body timeout behavior | `NOT RUN` | The device startup smoke did not simulate a delayed response body; this is not proven by the connection and health checks. |

The live physical test sequence also remains outstanding: begin with verified `LIBRE`, explicitly coordinate with the user, and perform one sensor transition at a time. No physical movement was inferred from serial output.

## Limitations and Phase 5 gate

- HTTP calls remain synchronous. The 200 ms polling interval does not guarantee sensing at exactly 200 ms while a request is in flight; the controller rereads the attempted sensor after the call returns.
- The 78 fake checks and startup smoke do not prove real API-outage recovery, Wi-Fi recovery, reboot reconciliation, or latest-state convergence on hardware.
- Phase 5 is **NOT READY** until the required live recovery and reboot checks in the authoritative plan pass. Any unavailable Wi-Fi outage or cold-power test must remain an explicit caveat rather than a passed criterion.

## Result

Phase 4 firmware behavior was implemented and uploaded; host validation and normal ESP32 startup synchronization passed. Live outage/recovery and reboot acceptance remain incomplete, so Phase 4 is implemented with caveats and Phase 5 remains gated.

IMPLEMENTED — READY WITH CAVEATS
