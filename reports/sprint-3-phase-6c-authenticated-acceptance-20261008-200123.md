# Sprint 3 Phase 6C Authenticated Acceptance Retry

Date: 2026-10-08 20:01:23 America/Mexico_City (UTC-06:00)

## Objective and authentication

Validate a real reasonless operational-state save through an authenticated ADMIN Nuxt page, FastAPI, and the persistent development PostgreSQL database; verify the event journal and restore the original state.

The user completed sign-in manually. The browser reached `/admin` and `/admin/estacionamiento` in the authenticated ADMIN interface. No credentials, cookies, or session tokens were requested, read, captured, logged, or stored.

## Environment and baseline

- `api-dev`, `web-dev`, and `postgres` were running; PostgreSQL reported healthy. API and Web do not declare container health checks. The services were published on loopback, including PostgreSQL at `127.0.0.1:5432`.
- `GET /health` returned HTTP 200. A PostgreSQL `psql` connection succeeded. Alembic reported `20261008_0001 (head)`.
- The authenticated ADMIN page loaded the authoritative eight-cajón list. API access logs showed authenticated `GET /api/cajones` requests returning HTTP 200.
- Cajón 1 was excluded because the local ESP32 slot configuration maps it to GPIO26. Cajón 2 had no physical timestamp and was not mapped in that local slot configuration. This was the lowest-risk configured development target available; no physical state was changed and no hardware was contacted.
- Immediately before the operation, Cajón 2 was `FUERA_DE_SERVICIO`, reason `NULL`, physical state `DESCONOCIDO`, physical timestamp `NULL`, effective state `NO_DISPONIBLE`. Its operational timestamp was `2026-10-08 08:18:42.664267+00`.
- The event journal high-water cursor and row count were both 562. Events 549–562 were background `cajon.actualizado` events for Cajón 1; Cajón 2 had no event after the recorded baseline cursor.

## Authenticated browser flow and HTTP results

In the ADMIN `/admin/estacionamiento` page, the “Administrar el lugar 2” modal showed the physical state as read-only. The operational state was changed from `FUERA_DE_SERVICIO` to `MANTENIMIENTO`; Motivo was left empty and the normal “Guardar estado” action was used.

- The UI reported that the operational change was confirmed and the current list synchronized. Cajón 2 displayed `Mantenimiento` and effective state `No disponible`.
- API access logs showed `PATCH /api/cajones/2/estado-operativo` returning HTTP 200, followed by `GET /api/cajones` returning HTTP 200. No HTTP 500 occurred.
- The original state was restored in the same modal through the normal authenticated flow. The state was set to `FUERA_DE_SERVICIO`, Motivo remained empty, and the UI again reported a confirmed change and synchronized list. The second PATCH and its following GET both returned HTTP 200.
- After restoration, the main ADMIN page displayed Cajón 2 as `Fuera de servicio`, physical `Desconocido`, and effective `No disponible`.

## PostgreSQL persistence and event journal

The persistent database confirmed the first save as `MANTENIMIENTO` with `motivo_operativo = NULL`; the physical state stayed `DESCONOCIDO` and its physical timestamp stayed `NULL`. Backend precedence yielded `NO_DISPONIBLE`.

Exactly one Cajón 2 event followed the baseline for the test transition:

| Event ID | Type | Operational state | Reason | Physical state |
|---:|---|---|---|---|
| 563 | `cajon.actualizado` | `MANTENIMIENTO` | `NULL` | `DESCONOCIDO` |

The restoration persisted `FUERA_DE_SERVICIO` with reason `NULL`, preserving the same physical state and yielding `NO_DISPONIBLE`. It generated the expected restoration event:

| Event ID | Type | Operational state | Reason | Physical state |
|---:|---|---|---|---|
| 564 | `cajon.actualizado` | `FUERA_DE_SERVICIO` | `NULL` | `DESCONOCIDO` |

After restoration, the journal cursor and row count were both 564. The only two events after cursor 562 were the expected Cajón 2 transition and restoration; no duplicate or additional event for that resource was present. Event history was not deleted.

Final persistent operational and physical state snapshot:

| Cajón | Operational state | Reason | Physical state | Effective state |
|---:|---|---|---|---|
| 1 | `DISPONIBLE` | `NULL` | `LIBRE` | `LIBRE` |
| 2 | `FUERA_DE_SERVICIO` | `NULL` | `DESCONOCIDO` | `NO_DISPONIBLE` |
| 3–8 | `DISPONIBLE` | `NULL` | `DESCONOCIDO` | `DESCONOCIDO` |

## SSE delivery evidence

Two authenticated `/api/eventos` requests returned HTTP 200 and the separate ADMIN observer page displayed “En vivo”. However, after event 563 was recorded, that observer continued displaying Cajón 2 as `Fuera de servicio` instead of `Mantenimiento`. The main page’s new state followed the successful mutation and authoritative GET reconciliation; it does not establish SSE receipt. The observer likewise did not provide evidence of receiving event 563. Therefore delivery of the transition to the existing authenticated SSE subscriber is **not verified**, despite the event being present in PostgreSQL and the SSE streams being established.

## Regression and scope results

- **PASS — optional reason for `MANTENIMIENTO` and `FUERA_DE_SERVICIO`:** both the real operational save and the real restoration used an empty reason, returned HTTP 200, and persisted `NULL` reason values.
- **PASS — physical state remained read-only in the live modal:** the UI labeled it “solo lectura”; PostgreSQL confirmed it remained `DESCONOCIDO` with a `NULL` physical timestamp before and after.
- **PASS IN THE PREVIOUS ACCEPTANCE RUN; NOT RERUN IN THIS RETRY — API regression:** 19 targeted tests covered optional reasons, rejection of non-null reasons for `DISPONIBLE`, precedence, event/no-op behavior, and migration behavior.
- **PASS IN THE PREVIOUS ACCEPTANCE RUN; NOT RERUN IN THIS RETRY — Web regression:** 40 targeted tests covered optional-reason normalization, available-state validation, event snapshot reconciliation, proxy allow-listing, and the layout-owned single EventSource subscription architecture.
- No application source, test, configuration, firmware, or database schema changes were made by this retry. The pre-existing dirty working tree was preserved. No Git staging, commit, push, reset, or checkout was performed. No CodeGraph index sync was needed because no indexed source file changed.

## Remaining limitation

SSE event-delivery evidence is a required acceptance condition. The established stream returned HTTP 200, but the separate observer remained stale across event 563, so the event’s arrival at the authenticated SSE subscriber could not be confirmed. The reasonless save, authoritative persistence, effective-state calculation, event journal entry, and safe restoration succeeded; full Phase 6C acceptance is blocked only by the missing delivery evidence.

## Final verdict

ACCEPTANCE BLOCKED
