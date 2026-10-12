# FastAPI LAN Access for ESP32 — Public-Profile LAN Execution Report

Date: 2026-10-06 16:54:02 -06:00  
Mode: **EXECUTION — BLOCKED AT PRIVILEGE GATE**  
Workspace: Smart Parking

Authoritative references:
- [Plan Builder](fastapi-lan-access-esp32-plan-20261006-154917.md)
- [Previous blocked Executor](fastapi-lan-access-esp32-execution-20261006-163137.md)

## Final verdict

**EXECUTION BLOCKED**

The current PowerShell process does not have an elevated Administrator token. The new Executor requires stopping when the privileges needed for the Firewall rule are unavailable. No Compose change, Firewall change, container recreation, or network change was attempted in this execution.

AREA21 remains Public. The API remains published to Windows loopback at 127.0.0.1:8000. No same-LAN acceptance claim is made.

## Owner override

The new Executor explicitly overrides the previous Private-profile requirement for this task only. Its authorized policy is to keep AREA21 Public and, when execution can be completed, create one inbound rule for TCP 8000 with RemoteAddress limited to the current AREA21 subnet. This report treats that instruction as authoritative; it does not authorize RemoteAddress Any, another exposed port, or changes to unrelated Firewall rules.

## Preflight evidence

### Git, CodeGraph, and source

- Initial Git state: develop...origin/develop, with no staged, unstaged, or untracked changes.
- CodeGraph status: index up to date. No sync was needed.
- infra/compose.dev.yml still has api-dev published as 127.0.0.1:8000:8000 and web-dev as 127.0.0.1:3000:3000.
- The api-dev command still runs Uvicorn with --host 0.0.0.0 --port 8000.
- Root .env values inspected without reading or recording credentials:
  - APP_ENVIRONMENT="development"
  - APP_PUBLIC_URL="http://localhost:3000"
  - NUXT_API_INTERNAL_BASE_URL="http://api-dev:8000"

### Containers and PostgreSQL data

| Service | Container ID | State |
|---|---|---|
| api-dev | 4bd4babed73ee42469c235350f071b1520b23245a69369c3eee04512eb1b0726 | running |
| web-dev | f3efa55cd8081f323c134709a7724d39c4dcd43332af6635cacac1cf64dd556a | running |
| postgres | ec979f47e07c6097a54264096c7c1aed2fa7e057144dcca1e33329930351508 | running, healthy |
| mailpit | 28f77f6b5b580fcd924130a4831658ba182bbfb53fa03ee4c7124dfb11437508 | running, healthy |

PostgreSQL mounts named volume postgres_data at /var/lib/postgresql/data. No container was recreated, no migration ran, and no database or Mailpit data was changed.

### AREA21 and Windows Firewall

- Active interface: WiFi, index 12; network name AREA21.
- Current IPv4: 192.168.1.67/24; gateway 192.168.1.254.
- Derived current subnet: 192.168.1.0/24. The address may change through DHCP.
- Windows category: Public, as required by the owner override.
- Windows Firewall is enabled for Domain, Private, and Public profiles; default inbound action is Block.
- The exact task rule SmartParking-FastAPI-LAN-Dev-TCP8000 is absent.
- Current process elevated Administrator token: False.
- No rule creation command was attempted.

### Planned rule, not applied

| Field | Intended value |
|---|---|
| Name | SmartParking-FastAPI-LAN-Dev-TCP8000 |
| Direction | Inbound |
| Action | Allow |
| Enabled | True |
| Protocol | TCP |
| Local port | 8000 |
| Profile | Public |
| RemoteAddress | 192.168.1.0/24 |

The subnet above was derived from the current interface address and prefix, rather than copied from the earlier example.

## Baseline runtime checks

| Check | Result |
|---|---:|
| Podman api-dev mapping | 127.0.0.1:8000 |
| Windows listener | 127.0.0.1:8000 |
| GET http://localhost:8000/health | HTTP 200 |
| GET http://127.0.0.1:8000/health | HTTP 200 |
| Windows self-probe to http://192.168.1.67:8000/health | No connection (000) |
| GET http://localhost:3000/login | HTTP 200 |
| web-dev to http://api-dev:8000/health | HTTP 200 |
| Unauthenticated API /api/autenticacion/me | HTTP 401 |
| Unauthenticated BFF /api/autenticacion/me | HTTP 401 |

No separate AREA21 client or ESP32 request was run. The API is still loopback-only, so the remote path could not be accepted.

## Context7 findings used

- Podman documents host-IP publication semantics: 0.0.0.0 binds IPv4 host addresses and 127.0.0.1 is loopback-only. The documentation does not prove Windows-to-LAN reachability through WSL; runtime checks remain necessary. [Podman publish reference](https://docs.podman.io/en/latest/markdown/podman-run.1.html)
- Compose port binding uses the host-IP, published-port, container-port form. Targeted --no-deps --force-recreate behavior was already checked; no recreation was performed. [Compose port binding implementation](https://github.com/docker/compose/blob/main/pkg/compose/create.go), [Compose no-deps recreation example](https://github.com/docker/compose/blob/main/pkg/e2e/recreate_no_deps_test.go)
- Uvicorn binds the server socket with --host 0.0.0.0; clients must use a reachable host address. [Uvicorn settings](https://uvicorn.dev/settings)
- Microsoft PowerShell documentation confirms New-NetFirewallRule creates a local inbound/outbound Firewall rule and supports profile, port, protocol, and remote-address filters. The documented subnet formats support the requested LAN scope. [New-NetFirewallRule](https://github.com/microsoftdocs/windows-powershell-docs/blob/main/docset/winserver2025-ps/NetSecurity/New-NetFirewallRule.md), [RemoteAddress formats](https://github.com/microsoftdocs/windows-powershell-docs/blob/main/docset/winserver2025-ps/NetSecurity/Set-NetFirewallAddressFilter.md)

## Changes and remaining work

- Repository files changed: none.
- Firewall rule created or modified: none.
- AREA21 category changed: no; it remains Public.
- Containers recreated: none.
- Database, postgres_data, Web, Mailpit, authentication, CORS, and API routes: unchanged.
- Git staging, commit, push, reset, or checkout: none.
- To resume, run the execution in a Windows session with sufficient Administrator privileges, then repeat the required preflight and same-LAN client probe. No elevation bypass was attempted.

**Final verdict: EXECUTION BLOCKED**