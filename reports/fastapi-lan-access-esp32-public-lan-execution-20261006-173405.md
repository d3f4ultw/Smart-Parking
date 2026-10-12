# FastAPI LAN Access for ESP32 — Public-profile Execution

Date: 2026-10-06 (America/Mexico_City)

Final verdict: EXECUTION BLOCKED

## Objective

Enable the development FastAPI service on AREA21 for a same-LAN ESP32 or other client at the current Windows LAN IPv4 address, while keeping AREA21 Public, limiting the Windows Firewall exception to TCP 8000 from the current LAN subnet, preserving Web/BFF and authentication behavior, and preserving PostgreSQL data.

## Previous records

- Plan: reports/fastapi-lan-access-esp32-plan-20261006-154917.md
- Previous blocked execution: reports/fastapi-lan-access-esp32-execution-20261006-163137.md

The owner explicitly authorized the single Public-profile firewall exception for AREA21. The network category was kept Public throughout this execution.

## Scope

Included the canonical development Compose file, the targeted api-dev container recreation, the owner-run firewall rule, Windows host listener checks, focused HTTP probes, service identity checks, and CodeGraph status.

Excluded source-code changes, authentication or CORS changes, database migrations or resets, Web and PostgreSQL exposure, router/NAT forwarding, VPN or tunnel setup, broad Windows networking changes, and machine recreation.

## Work performed

- Confirmed the active Wi-Fi connection was AREA21 / WiFi, category Public, IPv4 192.168.1.67/24, gateway 192.168.1.254, and derived subnet 192.168.1.0/24.
- Confirmed the owner-run firewall script created and verified SmartParking-FastAPI-LAN-Dev-TCP8000. The active rule is enabled, Inbound / Allow, TCP local port 8000, Public profile, RemoteAddress 192.168.1.0/255.255.255.0. Windows Firewall Public remained enabled with default inbound action Block.
- Confirmed Podman client/server version 6.1.2, the existing podman-machine-default WSL machine, UserModeNetworking enabled, and force_port_listen=true in the active containers.conf.
- Temporarily changed only services.api-dev.ports[0] in infra/compose.dev.yml from 127.0.0.1:8000:8000 to 0.0.0.0:8000:8000. Compose validation passed. Recreated only api-dev with --no-deps --force-recreate.
- Podman reported 0.0.0.0:8000 for api-dev, and the FastAPI/Uvicorn process continued listening internally on 0.0.0.0:8000. However, Windows still listened only on 127.0.0.1:8000, and the Windows self-probe to 192.168.1.67:8000/health returned HTTP code 000.
- Because LAN access could not be demonstrated, restored api-dev to 127.0.0.1:8000:8000 and recreated only api-dev again. Compose validation passed after restoration.
- Created Desktop helper SmartParking-FastAPI-AREA21-TCP8000-ROLLBACK.ps1 to remove only the exact task rule after verifying its fields. The helper passed PowerShell static parsing. It has not been executed because the current Codex PowerShell process is not elevated.

## Final state and preservation

- infra/compose.dev.yml is restored to its original loopback-only API publication. Git status is clean on develop...origin/develop.
- Final api-dev container ID: 32168fc8564a332d9bb104d098dc3146b9c971f3341471f6cdebe03b7ce8a0b9.
- web-dev remained f3efa55cd8081f323c134709a7724d39c4dcd43332af6635cacac1cf64dd556a.
- postgres remained ec979ef47e07c6097a54264096c7c1aed2fa7e057144dcca1e33329930351508.
- mailpit remained 28f77f6b5b580fcd924130a4831658ba182bbfb53fa03ee4c7124dfb11437508.
- PostgreSQL still mounts postgres_data at /var/lib/postgresql/data. The postgres container and volume were not recreated, reset, or migrated.
- Web remains published on 127.0.0.1:3000; PostgreSQL remains published on 127.0.0.1:5432. Mailpit was not modified.
- CodeGraph reported its index up to date after restoration. No sync was needed because the repository content returned to its indexed state.
- Compose emitted existing project-label warnings for smart-parking-development and postgres_data; these resources were reused and not relabeled or recreated.

## Validation

| Check | Result |
|---|---|
| Compose config before temporary change | PASS |
| Compose config after restoring loopback | PASS |
| Temporary Podman publication | 0.0.0.0:8000 |
| Windows listener during temporary publication | 127.0.0.1:8000 only |
| Windows LAN-IP self-probe during temporary publication | FAIL, HTTP code 000 |
| Final Podman API publication | 127.0.0.1:8000 |
| FastAPI health at localhost and 127.0.0.1 after rollback | PASS, HTTP 200 |
| Web login | PASS, HTTP 200 |
| Web-dev to api-dev health | PASS, HTTP 200 |
| Unauthenticated direct API /api/autenticacion/me | PASS, HTTP 401 |
| Unauthenticated BFF /api/autenticacion/me | PASS, HTTP 401 |
| AREA21 final category | PASS, Public |
| Windows Firewall Public profile | PASS, enabled; inbound default Block |
| Separate AREA21 client | NOT RUN; the Windows LAN-IP self-probe failed first |
| ESP32 hardware smoke | NOT RUN |
| CodeGraph final status | PASS, up to date |
| Git status | PASS, clean |

## Findings and unresolved items

FastAPI itself was not the failing layer: Uvicorn retained its 0.0.0.0:8000 container listener, and internal Web-to-API traffic passed. The observed gap is between Podman's published port and the Windows host interfaces: Podman reported an all-IPv4 mapping while the Windows socket remained loopback-only. The inference is that the unresolved boundary is Podman Machine/WSL host forwarding. No additional Podman, WSL, Windows networking, router, or firewall settings were changed.

The scoped firewall rule remains present until the owner runs the rollback helper in an elevated PowerShell. Run:

& "$env:USERPROFILEDesktopSmartParking-FastAPI-AREA21-TCP8000-ROLLBACK.ps1"

The helper checks the rule name and exact TCP 8000 / Public / AREA21-subnet configuration before removing it. It does not change the firewall profile or other rules.

## References

- Podman port publication documentation: https://docs.podman.io/en/latest/markdown/podman-run.1.html
- Docker Compose targeted service recreation example: https://github.com/docker/compose/blob/main/pkg/e2e/recreate_no_deps_test.go

## Result

LAN reachability was not established, so no end-to-end acceptance is claimed. The API remains available locally at localhost:8000. AREA21 remains Public, the scoped firewall rule awaits owner-run removal, and the persistent database state remains intact.

EXECUTION BLOCKED