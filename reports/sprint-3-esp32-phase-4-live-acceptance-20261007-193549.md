# Sprint 3 ESP32 Phase 4 Live Recovery Acceptance

- Project: Smart Parking
- Sprint: 3
- Phase: 4
- Mode: Live Acceptance
- Acceptance date: 2026-10-07 (America/Mexico_City)
- Authoritative executor: Sprint 3 ESP32 Phase 4 Live Recovery Acceptance
- Final verdict: `IMPLEMENTED — READY WITH CAVEATS`

## Objective and scope

Validate the already implemented Phase 4 recovery behavior on the physical ESP32. No application source, firmware file, configuration, database schema, Compose, firewall, PortProxy, router, or credential was changed. Phase 5 was not started. Controlled physical-state API calls were used to create the required backend mismatches; PostgreSQL rows and event history were never edited directly or deleted.

The user's existing unrelated worktree changes were preserved. No Git add, commit, push, reset, or checkout was performed. This acceptance made no source-file edits.

## Preflight and baseline

- USB device re-enumerated as WCH CH9102, `VID_1A86&PID_55D4`, on `COM5`.
- Device runtime: MicroPython `3.4.0; MicroPython v1.28.0 on 2026-04-06`; `mpremote` 1.29.0.
- ESP32 API endpoint: `http://192.168.137.1:8000`. A direct device `GET /health` returned HTTP 200. Final host `/health` also returned `healthy`.
- PostgreSQL remained running and queryable throughout; its container health remained healthy.
- Cajón 1 uses GPIO26, active-low (`0` = OCUPADO; `1` = LIBRE). Configured poll interval is 200 ms. The sensor read raw `0` at the end of acceptance.
- The five Phase 4 device modules matched the local source SHA-256 values before live testing:

| Device module | SHA-256 |
| --- | --- |
| `api_client.py` | `6aa06871167373f15e566f3e545609a613610fad9f3f17728178f64a569033cb` |
| `config.py` | `8843a9714bf89a5f22578e8af3e2beda0365d8a91ec6088f01973755c2e775cf` |
| `main.py` | `0e6b9fd30694f5dce190e4449c0cfeb4e72cc2b913b5edc83e540b472b70741b` |
| `parking_controller.py` | `8420a6483855d2591c7e99ed6aa862bbd2f5ead23c0a3d2b7c7b81d998bfe688` |
| `wifi_manager.py` | `e85d30ae3acef405ac6662e4f9015b901254ddf16f8b7ad2f1f34b785703b184` |

A preliminary outage attempt was aborted after unexpected state drift; its resulting events 279–280 were retained and were not counted as a pass. The clean measured baseline was Cajón 1 `LIBRE`, global event high-water 280. PostgreSQL history was preserved.

## Live acceptance results

| Scenario | Before | Observed result | Event evidence | Verdict |
| --- | --- | --- | --- | --- |
| API outage and recovery | Physical/backend `LIBRE`, high-water 280 | With only `api-dev` stopped, the user placed the object; the ESP32 detected `OCUPADO` and retained a pending retry while PostgreSQL stayed available and unchanged. After `api-dev` returned, the ESP32 retried without another physical edge and the backend converged to `OCUPADO`. | High-water advanced 280 → 281, one meaningful `cajon.actualizado`. Stable follow-up produced no new event. | PASS |
| Latest-state convergence | Synced `OCUPADO`, high-water 281 | While API was unavailable, the user changed the sensor `OCUPADO` → `LIBRE` → `OCUPADO`. After API recovery, the final truth matched the last acknowledged value; no obsolete intermediate `LIBRE` was replayed. | Backend remained `OCUPADO`; high-water stayed 281. This validates replacement/cancellation of obsolete pending truth when the final state returns to the acknowledged state. | PASS |
| Wi-Fi outage and recovery | Synced `LIBRE`, high-water 282 | The user disabled only the Windows Mobile Hotspot used by the ESP32. The device reported Wi-Fi disconnected; local sensing detected the user's `OCUPADO` change. No physical-state PUT appeared while Wi-Fi was disconnected. After the hotspot returned, Wi-Fi reconnected and the pending current state synchronized without another sensor edge. | Backend converged to `OCUPADO`; high-water advanced 282 → 283 once. | PASS |
| Soft-reboot reconciliation | Physical/backend `OCUPADO`, high-water 283 | A controlled authenticated API call made backend state `LIBRE` while the sensor stayed `OCUPADO`. A raw-REPL `soft-reset` attempt did not run `main.py` and is excluded as an invalid boot test. Context7's official MicroPython reset/boot reference confirms raw-REPL soft reset skips startup scripts. A valid friendly-REPL Ctrl-D reset then printed `MPY: soft reboot`, `Wi-Fi: conectado`, `Cajón 1: OCUPADO`, and `Cajón 1: API sincronizada`. The user did not move the sensor. | Controlled mismatch created event 284 (`LIBRE`); valid startup correction created event 285 (`OCUPADO`), exactly one correction. | PASS |
| Cold boot | Physical `OCUPADO`, backend deliberately set to `LIBRE` | The user safely disconnected and reconnected only the ESP32 USB power. The board returned on COM5 and Wi-Fi was available, but the backend stayed `LIBRE` (event 286). Inspection of device `boot.py` showed only the default stub; it does not invoke `main.py`. Therefore application auto-start on cold boot **failed**. The existing `main.py` was then launched manually with `mpremote`; it reported Wi-Fi connected, detected `OCUPADO`, and synchronized. No firmware or boot file was altered. | Manual launch corrected the backend to `OCUPADO`, creating event 287 exactly once. | COLD-BOOT AUTO-START FAIL; MANUAL RECOVERY PASS |
| Idempotency / steady state | After manual synchronization, `OCUPADO`, high-water 287 | The monitor remained quiet for 7 seconds. The API log showed no repeat physical-state PUT during the final 20-second window. PostgreSQL remained `OCUPADO`. | Global and Cajón 1 event high-water stayed 287. | PASS |

The final serial monitor remains attached to the ESP32 and the manually launched application is running. Final PostgreSQL query returned Cajón 1 `OCUPADO`, global event high-water 287, and Cajón 1 event high-water 287. API health was `healthy`.

## Additional evidence and regression checks

- Prior Phase 4 execution report records `HOST_VALIDATION_PASS checks=78`; those host checks were not repeated for this live-only acceptance.
- Local sensor reads continued while the API or Wi-Fi was unavailable. API outage recovery required no new physical edge.
- Wi-Fi loss prevented HTTP attempts until reconnection; latest pending state synchronized after reconnection.
- Stable synchronized state generated no repeated PUTs or event spam in the observed final interval.
- Device firmware source hashes matched the deployed Phase 4 modules. GPIO26 active-low mapping and 200 ms polling configuration were verified.
- The backend, Web, SSE, database schema, Compose, network forwarding/firewall, and credentials were not changed by this acceptance. Existing unrelated worktree modifications were left intact.
- Live 401/404/422 terminal-error cases were not repeated; the executor authorizes host evidence as sufficient unless a live regression requires them.
- `boot.py` and `secrets.py` were preserved. No secret values or authorization material were captured in this report.
- CodeGraph was not synchronized because no source files were changed and no graph query was used.

## Caveats and Phase 5 gate

The cold power cycle did not automatically start the application because the device's existing `boot.py` does not invoke `main.py`. Manually starting the existing Phase 4 application after power-up restored Wi-Fi operation and physical-state synchronization, but that does not satisfy the cold-boot auto-start criterion. This limitation was not changed because the live-acceptance executor prohibits firmware and boot-file modifications.

API outage recovery, latest-state convergence, Wi-Fi recovery, valid soft-reboot reconciliation, final PostgreSQL/physical-state agreement, and idempotency passed. **Phase 5 is NOT READY** until the cold-boot startup gap is resolved and cold-boot acceptance passes. Do not treat the manual launch result as an automatic cold-boot pass. Phase 5 was not started.

## Final verdict

`IMPLEMENTED — READY WITH CAVEATS`
