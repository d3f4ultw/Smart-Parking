# Sprint 3 Phase 6B — Realtime Parking Frontend Execution

Date: 2026-10-08 00:34:10 -06:00  
Project: Smart Parking  
Sprint: 3  
Mode: Execution — Phase 6B  
Plan: `reports/sprint-3-phase-6-parking-frontend-plan-20261007-224145.md`  
Phase 6A baseline: `reports/sprint-3-phase-6a-parking-frontend-execution-20261007-230520.md`  
Supporting SSE/browser evidence: `reports/sprint-3-phase-5b-playwright-sse-acceptance-20261007-222115.md`, `reports/sprint-3-phase-5b-sse-closure-20261007-220016.md`

## Objective and scope

Complete only Sprint 3 Phase 6B in the protected ADMIN page `/admin/estacionamiento`: consume Cajón snapshots from the already shared real-time controller, reconcile the initial list cursor with buffered events, update cards and counters, preserve the last confirmed snapshot while disconnected, and recover through the existing GET list endpoint. Phase 6C operational editing/PATCH remains out of scope.

The execution used the existing ADMIN layout, authentication/session mechanism, Phase 5 SSE backend, Phase 6A GET BFF, PostgreSQL schema and event history, and ESP32 firmware without changing their responsibilities. No polling, timer-based refresh, dependency, backend/API/schema/migration, infrastructure, firmware, sensor, or physical-slot behavior was added or changed. There were no SQL writes, fixture inserts, event deletions, resets, or physical transitions by this execution.

## Preflight environment and read-only baseline

`web-dev`, `api-dev`, `postgres`, and `mailpit` were already running. PostgreSQL reported healthy. The API health endpoint returned HTTP 200. No containers were restarted. `podman compose ... ps` could not resolve the project’s required `.env` substitutions through the configured Compose provider; container state was independently inspected without altering it.

Before protected browser authentication, `/admin/estacionamiento` redirected to `/login`; `/api/admin/cajones` returned HTTP 401 with `Cache-Control: no-store`. The user then signed in normally in a temporary Microsoft Edge context. The authenticated read-only list contained eight rows and cursor `404`; its response declared `no-store`. The initial UI cards and counters matched that response.

A read-only database observation earlier in preflight recorded the eight-slot baseline (Cajón 1 `LIBRE`; Cajones 2–8 `DESCONOCIDO`) and cursor `352`. A later read-only observation found the latest Cajón event at ID `402` with `LIBRE` / `DISPONIBLE` / `LIBRE`; after browser acceptance the persistent event journal high-water was `404`. Those observations changed while the existing services remained running. This execution did not write to the journal, and the available read-only evidence does not attribute intervening events to a particular external actor.

The active SSE lease count was `3` before and after the temporary browser context. The browser context closed after acceptance; its session and cookies were not saved, read, printed, or included in the report.

## Source changes

Only these Phase 6B source/test files were edited:

- `apps/web/app/pages/admin/estacionamiento.vue`
- `apps/web/app/utils/cajones.ts`
- `apps/web/tests/cajones.test.ts`
- `apps/web/tests/eventos-tiempo-real.test.ts`

The page reuses the layout-provided `usarEventosTiempoReal()` controller. It does not instantiate a page-owned `EventSource`. The initial authoritative list response remains one `useAsyncData` result containing both `cajones` and `cursor_eventos`; the page subscribes once after mount from that cursor and detaches its own subscription before unmount. The layout continues to own the single shared stream and its stop lifecycle.

The reusable `aplicarInstantaneaCajon` helper matches by stable Cajón ID, applies only the server snapshot to the matching row, and preserves list-only fields, the list cursor, and every other row. It does not manufacture a card for an unknown ID; an unknown slot requests authoritative list reconciliation. Counters derive from `estado_efectivo`, so maintenance precedence and `DESCONOCIDO` remain distinct and the row-count invariant is retained.

The existing controller continues to validate events, order decimal cursors, discard duplicates and older IDs, and buffer events received while the page loads or reconciles. A `resync` or unknown slot detaches the page subscriber and requests the existing GET list. One recovery may run at a time. On success, the response and its cursor are committed together and the page resubscribes from that exact cursor, allowing the shared controller to replay later buffered events. On failure the last confirmed rows stay visible with a sanitized error and manual retry; a failed response does not loop through its immediate attach-time resync callback.

The connection badge reports `Reconectando` until the page subscription is active and shows `Actualizando` during list reconciliation. Confirmed cards and counters remain visible through disconnects. Stream session loss detaches the page subscriber and clears its protected snapshot; the existing controller/layout remains responsible for session verification, logout, and navigation. The existing 401 path still clears protected page state and returns to login. Manual refresh remains independent of SSE and uses the same authoritative GET.

## Focused and regression validation

- Focused Cajón and real-time controller tests: **22/22 passed**.
- Full Web test suite: **99/99 passed**.
- `pnpm exec nuxi typecheck`: passed.
- `pnpm lint` (Nuxt prepare and ESLint): passed.
- Production `nuxt build` in a temporary copy of the Web source: passed. The repository’s existing `.output` was not changed.
- Phase 6A regressions: authenticated list loading, stable row rendering/order, server-derived summary counts, protected same-origin BFF, no-store response, manual refresh, and session protection remained intact.
- Automated tests exercise snapshot application, physical-state counter transitions, maintenance precedence, unknown-state counting, unknown IDs, duplicate/out-of-order events, buffered event replay across initial load and refresh, and controller reconnection/session-loss paths.
- No new test runner or dependency was added to the repository.

## Microsoft Edge acceptance

Acceptance ran in a fresh, non-persistent Playwright Microsoft Edge context. The user entered credentials normally in the browser. The harness neither captured form contents nor read or saved browser storage. One initial harness pass exposed a harness race: its synthetic stream arrived before the initial-count assertion. The harness was corrected to hold the synthetic stream until the baseline assertion completed; the final run passed.

The final browser run recorded:

- Authenticated list: eight rows, cursor `404`, `Cache-Control: no-store`; rendered cards and all four counters matched the list before the synthetic stream was released.
- Exactly one `EventSource` object on the admin layout. The page subscription remained singular after Dashboard → Estacionamiento navigation.
- A route-intercepted synthetic `cajon.actualizado` with client-only event ID `405` updated Cajón 1 from `LIBRE` to `OCUPADO`; counters changed without reload. The repeated ID `405` and older ID `404` did not regress it. A synthetic `resync` at `406` triggered the intercepted authoritative-list response and the card/counters remained consistent.
- Manual refresh independently reconciled the same confirmed snapshot.
- After the synthetic finite stream ended, the UI showed `Reconectando` while retaining the confirmed cards/counters. Releasing the retry to the real same-origin BFF established the actual authenticated SSE connection and returned the controller to its connected state.
- Direct reload passed through SSR/hydration with zero additional browser-side `/api/admin/cajones` requests, one EventSource object in the new page, zero page errors, zero hydration warnings, and zero browser console errors.

The synthetic event IDs `405` and `406` existed only in the Playwright route fixture; they were not inserted into PostgreSQL. The real BFF stream connection was observed, but no device-originated Cajón transition was induced or claimed. This respects the no-physical-transition and no-database-write boundary.

## CodeGraph and worktree preservation

After source changes, `codegraph sync` succeeded. `codegraph status` reports **170 files, 3,047 nodes, 8,967 edges**, with `[OK] Index is up to date`. Focused graph queries confirmed the page’s `suscribirCajones` path, the helper’s page/test callers, and the affected Cajón/event tests.

All modified, deleted, and untracked paths present at preflight were preserved. No unexpected source/configuration paths appeared. No files were staged; no commit, push, checkout, reset, or worktree cleanup was performed. This report is the single new immutable Phase 6B report; the earlier partial Phase 6B report was left untouched.

## Phase 6C handoff

- Reactive confirmed state remains `RespuestaListaCajones | null`, pairing rows with the list’s event cursor.
- Subscribe from `cursor_eventos` only after the authoritative list is available; keep the single EventSource in the ADMIN layout.
- Apply event snapshots by stable Cajón ID and use server `estado_efectivo`; send unknown IDs through GET reconciliation rather than rendering incomplete data.
- For resync/manual refresh, detach only the page subscriber, serialize one GET, then commit the returned rows and cursor together and resubscribe from that cursor.
- Keep `En vivo` conditional on an active page subscription, preserve confirmed data while reconnecting, and retain the existing session-loss owner and safe UI behavior.
- Phase 6C can add only its newly authorized operational mutation flow. The current page contains no PATCH or operational controls. Real device-originated movement and PostgreSQL event writes were deliberately not part of this frontend acceptance.

## Remaining caveat

The end-to-end card transition and resync were supplied by an isolated synthetic browser route fixture because this phase prohibited physical movement and database writes. The actual authenticated BFF stream was connected, and pure/controller tests passed, but no real device-originated Cajón event was observed changing the UI during this run. Browser session-expiry was not forcibly induced; authentication, 401 protection, and controller session-loss behavior were covered by the existing focused/full automated checks and anonymous-route probe.

IMPLEMENTED — READY WITH CAVEATS
