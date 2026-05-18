# Blue-Green Non-Production Validation

## Purpose

This document tracks the non-production validation phase for the blue-green
runtime path before any production apply is considered.

Production remains NO-GO. This phase must not switch production traffic, change
Cloudflare or domain routing, replace the current production web container, or
modify active production proxy configuration.

The goal is to prove the operational path in a local-only or staging scope
before a separate production approval task reviews exact runtime commands.

## Approval Package Status

The separate approval package exists at
[BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md).
It prepares a future validation only; it does not run commands and does not
approve production.

Additional future non-production runtime validation remains NO-GO until a
separate task provides the exact approval phrase:

```text
I_APPROVE_NON_PRODUCTION_BLUE_GREEN_RUNTIME_VALIDATION_NO_PRODUCTION_TRAFFIC
```

The future validation must use a deployment lock, such as
`.deploy/bluegreen-nonprod-validation.lock`, before test-only runtime actions.
Production remains NO-GO. Normal non-deploy tasks are not blocked by this
deployment lock.

The local/test proxy routing validation approval package exists at
[BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md](BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md).
It prepares a future validation only; it does not run anything and does not
approve production. Proxy validation remains pending and requires this separate
approval phrase before any test proxy or inactive service is started:

```text
I_APPROVE_LOCAL_PROXY_ROUTING_VALIDATION_NO_PRODUCTION_TRAFFIC
```

That future proxy validation must use deployment lock path
`.deploy/bluegreen-proxy-validation.lock`, Compose project
`aftersales-bluegreen-proxy-validation`, inactive service `web_green_test` on
`18080`, and test proxy service `bluegreen_proxy_test` on `19080`. The current
`web` service and production port `8000` must remain untouched.

## Validation Result - 2026-05-18

- Validation status: PASSED.
- Scope: local/non-production only.
- Validation command:
  `scripts/blue_green_local_inactive_startup.ps1 -ExecuteInactiveStartup`.
- Approval acknowledgement used:
  `I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC`.
- Test port: `18080`.
- Target service: `web_green_test`.
- Image: `aftersales-web:latest`.
- Compose file: `docker-compose.bluegreen.local-test.example.yml`.
- Active service: current `web` on port `8000` remained healthy.
- Active service health before validation: `8000 /healthz/` returned HTTP 200
  OK.
- Inactive service health: `18080 /healthz/` initially failed while starting,
  then returned HTTP 200.
- Cleanup: `web_green_test` was stopped.
- Post-cleanup target state: `18080 /healthz/` was unable to connect, meaning
  cleanup succeeded.
- Current web protection: current `web` was not targeted.
- Port protection: port `8000` was not targeted.
- Production traffic switch: no.
- Migrations/collectstatic: no.
- External APIs: no Shopify, Gmail, Trustpilot, Kudosi, Ali Reviews, or email
  send path was requested.
- Production status: still NO-GO.

This result proves the local inactive-service startup and direct health-check
path only. It does not approve production apply, production proxy changes,
traffic switching, migrations, collectstatic, or external API workflows.
Local/test proxy routing validation is still pending and required before
production apply can be reconsidered.

## Validation Scope

The future validation should cover:

- Deployment lock acquisition and matching release.
- Target color selection.
- Inactive color startup in a non-production scope.
- Inactive color `/healthz/` check.
- Proxy configuration validation.
- Test-only proxy routing on a non-production port.
- Test-only proxy routing validation through `19080` to `web_green_test` on
  `18080`, gated by
  [BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md](BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md).
- Rollback/no-switch behavior when validation fails.
- Cleanup of test-only services.
- Confirmation that the current production web service remains untouched.

This scope does not include production deployment, production traffic switch,
production proxy replacement, migrations, collectstatic, Shopify workflows,
ticket workflows, review request automation, translation workflows, settlement
logic, Gmail, Trustpilot, Kudosi, Ali Reviews, or any external write path.

## Environment Options

Acceptable future validation environments include:

- Local-only validation on the operator machine.
- A staging environment, if one exists and is explicitly approved.
- A non-production Docker Compose project name so test resources cannot collide
  with the active production project.
- Test-only ports such as `18080`, `18081`, or `19080`.
- Test-only proxy routing on a local or staging port.

No Cloudflare, domain, tunnel, DNS, or production routing change is allowed in
this non-production validation phase.

## Required Safety Gates

Before any non-production runtime validation, confirm:

- `git status` has been reviewed.
- Current `http://127.0.0.1:8000/healthz/` is OK.
- Deployment lock helper is available.
- No existing deploy lock is present.
- Target test port is not `8000`.
- Current web service is not the target inactive service.
- Cleanup command is ready before startup.
- Rollback/no-switch plan is ready before startup.
- Production apply remains NO-GO.
- The approval package has been reviewed.
- The exact approval phrase has been provided in a separate task.
- For proxy validation, the proxy approval package has been reviewed, the
  local proxy approval phrase has been provided in a separate task, the proxy
  test port is `19080`, and production port `8000` is not used.

If any gate is uncertain, stop before starting test-only services.

## Future Command Groups

All command groups in this section are examples only.

NOT RUN IN THIS TASK:

### Lock Preflight

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock_dry_run.ps1 -Purpose "blue-green-non-production-validation" -Target "non-production" -ShowPlan
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action status
```

NOT RUN IN THIS TASK:

### Compose And Proxy Config Validation

```powershell
docker compose -p aftersales-bluegreen-test -f .\docker-compose.bluegreen.local-test.example.yml config
docker compose -p aftersales-bluegreen-test -f .\docker-compose.bluegreen.local-test.example.yml config --services
```

NOT RUN IN THIS TASK:

### Start Inactive Target In Non-Production Scope

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_inactive_startup.ps1 `
  -ExecuteInactiveStartup `
  -Ack I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC `
  -AllowContainerAction `
  -ComposeFile .\docker-compose.bluegreen.local-test.example.yml `
  -InactiveService web_green_test `
  -TestPort 18080
```

NOT RUN IN THIS TASK:

### Health Check Target

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18080/healthz/
```

NOT RUN IN THIS TASK:

### Test Proxy Routing On Non-Production Port Only

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:19080/healthz/
```

NOT RUN IN THIS TASK:

### Cleanup Target

```powershell
docker compose -p aftersales-bluegreen-test -f .\docker-compose.bluegreen.local-test.example.yml stop web_green_test
docker compose -p aftersales-bluegreen-test -f .\docker-compose.bluegreen.local-test.example.yml rm -f web_green_test
```

NOT RUN IN THIS TASK:

### Release Lock

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action release -LockId <matching-lock-id>
```

NOT RUN IN THIS TASK:

### Post-Check Current 8000 Health

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/healthz/
```

## Failure Handling

If non-production validation fails:

- Do not switch production traffic.
- Do not touch the current production web service.
- Print target logs for the test-only service.
- Stop test-only services.
- Release the matching deployment lock only.
- Report failure with the failed gate, target color, test port, and cleanup
  result.

Rollback in this phase means no production switch occurred. The expected
fallback is to leave the current production web path unchanged and remove only
the test-only resources.

## Go / No-Go

- This document: READY after review.
- Approval package:
  [BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md)
  exists for separate review.
- Non-production inactive runtime validation: PASSED on 2026-05-18.
- Local/test proxy routing validation: pending; approval package exists at
  [BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md](BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md).
- Production apply: NO-GO.
