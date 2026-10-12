# Sprint 3 ESP32 Phase 2 — Reusable Sensor Architecture Execution

- Project: Smart Parking
- Sprint: 3
- Phase: 2 — Reusable Sensor Architecture
- Date: 2026-10-07 (America/Mexico_City)
- Mode: EXECUTION — PHASE 2 ONLY
- Authoritative Plan Builder: `reports/sprint-3-esp32-phase-2-reusable-sensor-plan-20261007-011640.md`
- Device baseline: `reports/sprint-3-esp32-phase-1-device-baseline-20261007-011103.md`
- Final verdict: IMPLEMENTED — READY WITH CAVEATS

## Objective and scope

Refactor the local ESP32 sensor code for configuration-driven slots while preserving Cajón 1 on GPIO26, active-low occupancy, the 200 ms polling interval, and initial/change-only serial output. No physical-state API synchronization was added. Phase 3 was not started.

No backend, Web, database, network, infrastructure, or credential changes were made. No files were staged, committed, pushed, reset, or checked out. No hard reset or MicroPython reflash occurred. One device soft reset was used for Phase 2 runtime validation.

## Preflight and baseline

- Initial Git status contained pre-existing modified and untracked Smart Parking work. It was preserved; no unrelated file was changed by this task.
- `mpremote 1.29.0` was invoked by its verified executable path. Serial enumeration identified COM5 as USB-Enhanced-SERIAL CH9102 (`1a86:55d4`).
- `os.uname()` identified `esp32`, MicroPython 1.28.0, `Generic ESP32 module with ESP32`.
- The private Phase 1 baseline at `tmp/esp32-baseline/20261007-010315/` still existed and was not modified.
- Before editing, SHA-256 comparisons showed `main.py`, `parking_sensor.py`, `parking_controller.py`, `wifi_manager.py`, and `api_client.py` matched the Phase 1 baseline on both repository and device.
- Device `API_BASE_URL` matched the repository value; no `SSID` or `PASSWORD` symbol was present in device `config.py`; importing the existing `wifi_manager` succeeded. Secret values were never displayed.
- Root `.gitignore` continues to ignore `firmware/esp32/parking_slot/secrets.py`.

## Repository changes

Exactly the four planned firmware source files were changed:

1. `firmware/esp32/parking_slot/config.py` — preserved `API_BASE_URL`; added `PARKING_SLOTS = ((1, 26),)` and `POLL_INTERVAL_MS = 200`.
2. `firmware/esp32/parking_slot/parking_sensor.py` — replaced the module singleton with `ParkingSensor(cajon_id, gpio_pin)`. Each instance owns its GPIO input and maps pin value 0 to occupied and 1 to free.
3. `firmware/esp32/parking_slot/parking_controller.py` — added `ParkingController`, per-cajon `last_states`, `scan_once()`, and one `monitor()` loop using MicroPython `time.sleep_ms()`.
4. `firmware/esp32/parking_slot/main.py` — constructs sensors from `PARKING_SLOTS`, preserves Wi-Fi and `/health` behavior, then starts one controller.

`wifi_manager.py`, `api_client.py`, `secrets.py`, `secrets.example.py`, root `requirements-dev.txt`, and non-firmware project areas were not changed. The controller has no `machine` import, GPIO construction, slot-specific branch, per-slot monitor, HTTP PUT, Bearer handling, retry state, or pending backend state. Its output uses the sensor's ID dynamically.

## Host-side validation

Using CPython 3.14 and lightweight in-memory fake sensors, with no new test framework or permanent test file:

- PASS — all four changed modules compile.
- PASS — `parking_controller` imports without importing `machine`.
- PASS — initial LIBRE appears once; unchanged LIBRE is silent; LIBRE → OCUPADO appears once; unchanged OCUPADO is silent; OCUPADO → LIBRE appears once.
- PASS — two fake sensors keep independent previous states and only the changed slot reports.
- PASS — fake Cajón ID 42 prints dynamically, proving the controller does not hard-code ID 1.
- PASS — configuration preserves the API base value and defines only `(1, 26)` with a 200 ms interval.
- PASS — source scan finds no occupancy PUT, Bearer, retry/pending state, or per-slot monitor function.

## Device upload and runtime acceptance

After host validation, COM5 was re-enumerated and the board identity reconfirmed. Immediately before upload, all five behavior modules still matched the Phase 1 device baseline. The device API base matched the repository and the device had no legacy Wi-Fi keys in `config.py`.

Uploaded only `config.py`, `parking_sensor.py`, `parking_controller.py`, and `main.py`. Post-upload hashes matched those repository files. Device `secrets.py` and `boot.py` still matched the private Phase 1 baseline; `wifi_manager.py` and `api_client.py` also remained byte-identical to that baseline. Credential values and hashes are omitted.

On the ESP32, `time.sleep_ms` was available, the updated `config`, sensor, and controller modules imported, and `ParkingSensor(1, 26)` initialized GPIO26 successfully. Its pre-sequence reading was `False` (LIBRE).

One `mpremote soft-reset repl` was performed. It opened a clean REPL with `main` not loaded, so the existing startup path was invoked explicitly from the REPL without another reset. `main.py` reported Wi-Fi already connected, `/health` returned HTTP 200 with `{"status":"healthy"}`, and local monitoring started. The first observed main-loop state was OCUPADO because the sensor was already being alternated. After the physical sequence, `main.py` was re-imported with the sensor at LIBRE; it reported the required initial `Cajón 1: LIBRE`, retained Wi-Fi connectivity, and `/health` again returned HTTP 200.

The user confirmed 21 deliberate alternating transitions during the sequence. The serial output alternated between `Cajón 1: LIBRE` and `Cajón 1: OCUPADO` without duplicate consecutive states. A later OCUPADO change while positioning the object was confirmed deliberate. The user then confirmed a 5-second stable LIBRE interval, and the second main-loop run produced no further output during an additional 6-second observation.

The MicroPython reference consulted through Context7 documents `time.sleep_ms(ms)` and its millisecond argument. No physical-state request was sent; the only HTTP request exercised was the existing `/health` GET.

## Scale-out and CodeGraph

- PASS — source constructs the sensor collection by iterating `PARKING_SLOTS`; one `ParkingSensor` class and one controller loop serve each configured entry.
- PASS — two fake sensors with independent IDs validated shared controller logic. No additional GPIO was assigned or connected; the second physical pin remains symbolic.
- PASS — CodeGraph sync completed after the source changes. Final status had zero pending added, modified, or removed files, zero pending references, and no worktree mismatch.
- PASS — focused graph queries found `ParkingSensor`, `ParkingController`, `scan_once()`, and `monitor()`. `main.py` imports the sensor and controller from firmware modules. No dependency from this firmware path into backend or Web modules appeared; the pre-existing API client is used only for the existing health check.

## Secrets, worktree, and rollback

No secret values were printed or modified. Only the four approved firmware modules were uploaded; `secrets.py` and `boot.py` were preserved and verified against the Phase 1 baseline. No rollback was needed. The Phase 1 baseline and unrelated dirty worktree state remain intact. No staging, commit, or push occurred.

The host import created an ignored `__pycache__/parking_controller.cpython-314.pyc`. A targeted removal was rejected by command policy, so the ignored cache file remains; it is not firmware source and is not listed by Git. The new report is also ignored by the repository's existing root rule for `reports/` and remains local.

## Caveats and Phase 3 readiness

- The soft-reset REPL did not automatically execute `main.py`; the full Wi-Fi, health-check, and monitor path was verified by explicitly importing `main.py` after the single soft reset. A cold power-on boot was not separately tested.
- No hard reset, reflash, or second soft reset was used.
- No new sensors or GPIO assignments were introduced.
- Phase 2 local sensing is ready to hand off to a separately authorized Phase 3 executor. No Phase 3 API work was started here.

IMPLEMENTED — READY WITH CAVEATS
