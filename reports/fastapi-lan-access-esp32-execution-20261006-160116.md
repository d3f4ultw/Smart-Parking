# FastAPI LAN Access for ESP32 — Executor Report

Date: 2026-10-06  
Mode: **EXECUTION — BLOCKED BEFORE IMPLEMENTATION**  
Workspace: Smart Parking  
Approved plan: [Plan Builder report](fastapi-lan-access-esp32-plan-20261006-154917.md)

## Verdict

**EXECUTION BLOCKED**

The active Wi-Fi network is still categorized **Public**. The Executor requires explicit confirmation that it is the trusted development LAN before changing its category to Private or creating a Private-only inbound rule. No such confirmation was received before this report was created. Availability of an independent same-LAN client was also not confirmed.

No repository source or configuration, Windows network profile, Firewall rule, container, database, or Podman setting was changed. The approved implementation was not attempted.

## Pre-execution state

### Git and CodeGraph

- git status --short --branch: develop...origin/develop; no pre-existing staged, unstaged, or untracked changes were reported.
- CodeGraph status: index up to date. No sync was run.
- Direct Compose inspection and the live Web-to-API probe confirm that changing only the host publication would leave the internal http://api-dev:8000 path in place. CodeGraph does not model runtime host-port behavior, so no graph-only conclusion is used.

### Compose and environment

- infra/compose.dev.yml currently publishes api-dev as 127.0.0.1:8000:8000.
- api-dev command remains: uv sync --locked && exec uv run --no-sync uvicorn main:app --host 0.0.0.0 --port 8000 --reload --timeout-graceful-shutdown 3.
- web-dev remains published as 127.0.0.1:3000:3000.
- PostgreSQL remains published as 127.0.0.1:5432:5432.
- Root .env values inspected without reading or recording credentials:
  - APP_ENVIRONMENT="development"
  - APP_PUBLIC_URL="http://localhost:3000"
  - NUXT_API_INTERNAL_BASE_URL="http://api-dev:8000"
- Effective api-dev port before execution: 8000/tcp -> 127.0.0.1:8000.
- Effective web-dev port before execution: 3000/tcp -> 127.0.0.1:3000.
- The Uvicorn process command and /proc/net/tcp show an internal listener on 0.0.0.0:8000.

### Containers and PostgreSQL data

All four project containers were already running before this execution:

| Service | Container ID | State |
|---|---|---|
| api-dev | 4bd4babed73ee42469c235350f071b1520b23245a69369c3eee04512eb1b0726 | running |
| web-dev | f3efa55cd8081f323c134709a7724d39c4dcd43332af6635cacac1cf64dd556a | running |
| postgres | ec979f47e07c6097a54264096c7c1aed2fa7e057144dcca1e33329930351508 | running, healthy |
| mailpit | 28f77f6b5b580fcd924130a4831658ba182bbfb53fa03ee4c7124dfb11437508 | running, healthy |

The postgres container mounts named volume postgres_data at /var/lib/postgresql/data. No Compose operation, migration, database reset, or database write was performed, so the container and data mount were left as found.

## Windows network and Firewall

- Active interface: WiFi (interface index 12), network name AREA21.
- Current IPv4: 192.168.1.67/24; gateway 192.168.1.254; derived current subnet 192.168.1.0/24. The address is an observation and may change with DHCP.
- Original/current network category: **Public**.
- Windows Firewall is enabled for Domain, Private, and Public profiles. Each profile reports default inbound action Block.
- No existing ActiveStore rule for local TCP port 8000 was found; the planned rule name SmartParking-FastAPI-LAN-Dev-TCP8000 is not present.
- The category was not changed and no Firewall rule was added because the trusted-LAN prerequisite is unresolved.

## Baseline HTTP checks

| Probe before implementation | Result |
|---|---:|
| GET http://localhost:8000/health | HTTP 200 |
| GET http://127.0.0.1:8000/health | HTTP 200 |
| GET http://192.168.1.67:8000/health from Windows itself | No connection (000) under the current loopback-only publication |
| GET http://localhost:3000/login | HTTP 200 |
| GET http://api-dev:8000/health from web-dev | HTTP 200 |
| Unauthenticated API GET /api/autenticacion/me | HTTP 401 |
| Unauthenticated BFF GET /api/autenticacion/me | HTTP 401 |

The LAN-IP probe above is Windows connecting to itself. It is not evidence of remote LAN reachability. No independent same-LAN client or ESP32 probe was run.

## Context7 findings used

- Podman’s current publish reference documents explicit hostIP:hostPort:containerPort behavior: 0.0.0.0 binds IPv4 host addresses, while an exact 127.0.0.1 binds only that address. [Podman publish reference](https://docs.podman.io/en/latest/markdown/podman-run.1.html)
- Podman 6.1.0 release notes state that force_port_listen is needed for Windows host port forwarding with WSL. That setting and local forwarding were observed in the Plan Builder, but neither proves LAN forwarding. [Podman release notes](https://github.com/podman-container-tools/podman/blob/main/RELEASE_NOTES.md)
- Compose documents port host-IP syntax and targeted up --no-deps --force-recreate <service> behavior. The targeted recreation was not run because implementation did not pass the trusted-LAN gate. [Compose ports implementation](https://github.com/docker/compose/blob/main/pkg/compose/create.go), [Compose no-deps recreation example](https://github.com/docker/compose/blob/main/pkg/e2e/recreate_no_deps_test.go)
- Uvicorn’s settings document --host 0.0.0.0 as the server bind. Clients must use a reachable address such as the current Windows LAN IPv4, not 0.0.0.0. [Uvicorn settings](https://uvicorn.dev/settings)

These docs establish configuration semantics; they do not prove Podman/WSL Windows LAN reachability. The approved workflow requires runtime listener evidence and a separate same-LAN HTTP 200 probe after implementation.

## Changes, recreation, rollback, and remaining work

- Repository files changed: none.
- Firewall rules created or modified: none.
- Windows network profile changed: no; it remains Public.
- Containers recreated: none.
- Rollback: not applicable because no changes were applied.
- Required to resume safely: explicitly establish whether AREA21 is the trusted development LAN and whether a separate client on that LAN is available for the required HTTP probe. If trust cannot be established, the API must remain loopback-only under this plan.
- ESP32 smoke: not run; no business logic or ESP32 configuration was changed.

**Final verdict: EXECUTION BLOCKED**