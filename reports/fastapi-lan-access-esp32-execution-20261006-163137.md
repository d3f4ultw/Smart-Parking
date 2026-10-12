# FastAPI LAN Access for ESP32 — Executor Report

Date: 2026-10-06 16:31:37 -06:00  
Mode: **EXECUTION — BLOCKED**  
Workspace: Smart Parking  
Approved plan: [Plan Builder report](fastapi-lan-access-esp32-plan-20261006-154917.md)  
Prior blocked attempt: [Executor report](fastapi-lan-access-esp32-execution-20261006-160116.md)

## Final verdict

**EXECUTION BLOCKED**

The API LAN publication was not deployed. Windows rejected the attempt to change the active Wi-Fi profile from Public to Private. The current PowerShell process does not have an elevated Administrator token; Windows also reports that Network List Manager policy can prohibit user-initiated category changes. The exact cause beyond the non-elevated token was not independently determined.

The Executor prohibits a Public-profile exception, so no firewall rule was created. The Compose change was restored, and the running containers were not recreated.

## Operator intent and LAN state

The reissued task described the destination as “the trusted LAN.” I treated the currently active Wi-Fi, AREA21, as the intended development LAN for this attempt. Before any network change, the active interface was:

- Interface: WiFi, index 12
- Network: AREA21
- IPv4: 192.168.1.67/24
- Gateway: 192.168.1.254
- Derived subnet: 192.168.1.0/24
- Original and final Windows category: Public

The IPv4 address is a current DHCP observation and may change. A separate same-LAN client was not confirmed or tested, and the ESP32 smoke was not run.

## Preflight state

### Git, CodeGraph, and Compose

- Initial Git state: develop...origin/develop with no pre-existing staged, unstaged, or untracked changes.
- CodeGraph was up to date before the attempt. After the temporary Compose edit it reported one changed file; the normal sync completed for that file with zero graph nodes changed. After restoring the source, CodeGraph reports up to date.
- Only infra/compose.dev.yml was edited, temporarily changing services.api-dev.ports[0] from 127.0.0.1:8000:8000 to 0.0.0.0:8000:8000. The file was restored to 127.0.0.1:8000:8000.
- Compose config validation succeeded with the temporary value and again after restoration.
- Final Git status is clean.
- Uvicorn command stayed at --host 0.0.0.0 --port 8000. Web/BFF stayed at http://api-dev:8000. Root .env values remained APP_ENVIRONMENT="development", APP_PUBLIC_URL="http://localhost:3000", and NUXT_API_INTERNAL_BASE_URL="http://api-dev:8000".
- Web publication remained 127.0.0.1:3000:3000; PostgreSQL publication remained 127.0.0.1:5432:5432.

### Container identities and data

| Service | Container ID | Final state |
|---|---|---|
| api-dev | 4bd4babed73ee42469c235350f071b1520b23245a69369c3eee04512eb1b0726 | running, unchanged |
| web-dev | f3efa55cd8081f323c134709a7724d39c4dcd43332af6635cacac1cf64dd556a | running, unchanged |
| postgres | ec979f47e07c6097a54264096c7c1aed2fa7e057144dcca1e33329930351508 | running and healthy, unchanged |
| mailpit | 28f77f6b5b580fcd924130a4831658ba182bbfb53fa03ee4c7124dfb11437508 | running and healthy, unchanged |

PostgreSQL still mounts named volume postgres_data at /var/lib/postgresql/data. No container recreation, database write, migration, reset, or Mailpit operation occurred.

## Windows profile and Firewall

- All Windows Firewall profiles remain enabled with default inbound action Block.
- No suitable narrow existing TCP 8000 rule was found. The planned rule SmartParking-FastAPI-LAN-Dev-TCP8000 remains absent.
- Planned rule details, not applied: Inbound Allow, TCP local port 8000, Profile Private, RemoteAddress 192.168.1.0/24.
- The current process reports that its Administrator token is not elevated. Set-NetConnectionProfile returned a failure; the category remained Public.
- Preflight also found 41 enabled inbound Allow rules assigned to Private or Domain+Private but not Public; 24 of those have RemoteAddress Any. These are existing Windows rules and were not modified. If AREA21 is later changed to Private, those existing profile rules also become applicable to that Wi-Fi connection. This effect should be reviewed in the elevated execution before changing the category.

## Baseline and final runtime checks

| Check | Result |
|---|---:|
| GET http://localhost:8000/health | HTTP 200 |
| GET http://127.0.0.1:8000/health | HTTP 200 |
| Windows self-probe to http://192.168.1.67:8000/health | No connection (000) |
| GET http://localhost:3000/login | HTTP 200 |
| web-dev to http://api-dev:8000/health | HTTP 200 |
| Unauthenticated API /api/autenticacion/me | HTTP 401 |
| Unauthenticated BFF /api/autenticacion/me | HTTP 401 |
| Final Podman mapping for api-dev | 127.0.0.1:8000 |
| Final Windows listener | 127.0.0.1:8000 |

The Windows self-probe does not prove reachability from another LAN device. No remote device request was run because the API publication remained loopback-only.

## Context7 findings used

- Podman documents that explicit host IP 0.0.0.0 binds IPv4 addresses, while 127.0.0.1 is loopback-only. Podman’s WSL release notes describe force_port_listen as required for Windows host forwarding; neither establishes LAN reachability without runtime proof. [Podman publish reference](https://docs.podman.io/en/latest/markdown/podman-run.1.html), [Podman release notes](https://github.com/podman-container-tools/podman/blob/main/RELEASE_NOTES.md)
- Compose documents host-IP port syntax and that --no-deps with --force-recreate targets the selected service without recreating dependencies. The API recreation command was not run. [Compose port binding implementation](https://github.com/docker/compose/blob/main/pkg/compose/create.go), [Compose no-deps recreation example](https://github.com/docker/compose/blob/main/pkg/e2e/recreate_no_deps_test.go)
- Uvicorn documents --host 0.0.0.0 as its bind setting; clients must connect to a reachable host address. [Uvicorn settings](https://uvicorn.dev/settings)
- Microsoft PowerShell documentation confirms Set-NetConnectionProfile can select an interface index and set NetworkCategory Private. New-NetFirewallRule supports a specific profile, TCP local port, and remote subnet scope. The local profile change was denied by the Windows process/policy state, so the firewall rule was not attempted. [Set-NetConnectionProfile](https://github.com/microsoftdocs/windows-powershell-docs/blob/main/docset/winserver2025-ps/NetConnection/Set-NetConnectionProfile.md), [New-NetFirewallRule](https://github.com/microsoftdocs/windows-powershell-docs/blob/main/docset/winserver2025-ps/NetSecurity/New-NetFirewallRule.md)

## Rollback and remaining work

- Compose source was restored to the original loopback mapping and validates successfully.
- No Firewall rule or Windows profile change was applied; there was nothing to remove or restore.
- No API recreation was required during rollback because the runtime container had not been recreated and still used the original loopback mapping.
- PostgreSQL identity, postgres_data, Web, Mailpit, authentication behavior, and database state were preserved.
- To continue, the profile change must be performed in an elevated Windows session if allowed by local policy. Recheck the Private-profile rule impact, rerun the full Executor preflight, then validate from a separate same-LAN device while Windows Firewall remains enabled.

**Final verdict: EXECUTION BLOCKED**