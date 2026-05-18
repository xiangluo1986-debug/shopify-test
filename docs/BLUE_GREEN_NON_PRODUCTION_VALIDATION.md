# Blue-Green Non-Production Validation

## Purpose

This document defines a future non-production validation phase for the
blue-green runtime path before any production apply is considered.

Production remains NO-GO. This phase must not switch production traffic, change
Cloudflare or domain routing, replace the current production web container, or
modify active production proxy configuration.

The goal is to prove the operational path in a local-only or staging scope
before a separate production approval task reviews exact runtime commands.

## Validation Scope

The future validation should cover:

- Deployment lock acquisition and matching release.
- Target color selection.
- Inactive color startup in a non-production scope.
- Inactive color `/healthz/` check.
- Proxy configuration validation.
- Test-only proxy routing on a non-production port.
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
- Non-production runtime validation: separate approval required.
- Production apply: NO-GO.
