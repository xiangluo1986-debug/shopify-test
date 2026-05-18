# Blue-Green Non-Production Runtime Validation Approval

## Purpose

Prepare a future non-production blue-green runtime validation run.

This document does not approve production. This document does not run
anything. It is an approval package for a later task that must still receive
the exact approval phrase before any runtime validation command is run.

## Explicit Non-Goals

- No production traffic switch.
- No Cloudflare, domain, tunnel, or DNS routing change.
- No port `8000` ownership change.
- No current `web` restart, replacement, stop, or rebuild.
- No migration.
- No collectstatic.
- No external API write or send action.
- No Shopify, Gmail, Trustpilot, Kudosi, Ali Reviews, review request,
  translation, ticket, or settlement workflow action.

## Required Approval Phrase

Future non-production runtime validation is NO-GO until a separate task
provides this exact phrase:

```text
I_APPROVE_NON_PRODUCTION_BLUE_GREEN_RUNTIME_VALIDATION_NO_PRODUCTION_TRAFFIC
```

## Fixed Future Validation Parameters

- Test port: default `18080`; `19080` is the conservative alternate. Never use
  `8000`.
- Compose project name: `aftersales-bluegreen-validation`.
- Validation lock path: `.deploy/bluegreen-nonprod-validation.lock`.
- Target service: `web_green_test` or an equivalent non-production service.
  The target service must not be `web`.
- Cleanup: stop only the test/inactive service or services started by the
  validation run.
- Current web service: must remain untouched.
- Production traffic: no switch.
- Active `docker-compose.yml`: no modification and no use as the test startup
  Compose file.

## Safety Gates Before Future Run

Before any future non-production runtime validation, confirm:

- `git status` has been reviewed.
- `http://127.0.0.1:8000/healthz/` is OK.
- `18080`, or the chosen test port, is not currently serving.
- Deployment lock helper is available.
- No existing shared deploy lock or validation lock is present.
- Test port is not `8000`.
- Target service is not `web`.
- Cleanup command is ready before startup.
- Rollback/no-switch plan is ready before startup.
- Production apply remains NO-GO.

If any gate is uncertain, stop before any container, proxy, or runtime command
is run.

## Future Command Groups

All command groups below are examples for a later separately approved task.

NOT RUN IN THIS TASK:

### Lock Status

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock_dry_run.ps1 -Purpose "blue-green-non-production-validation" -Target "aftersales-bluegreen-validation" -ShowPlan
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action status -LockPath .\.deploy\bluegreen-nonprod-validation.lock
```

NOT RUN IN THIS TASK:

### Acquire Validation Lock

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action acquire -LockPath .\.deploy\bluegreen-nonprod-validation.lock -Purpose "blue-green-non-production-validation" -Target "aftersales-bluegreen-validation:web_green_test"
```

Save the returned `lock_id`. Release must use the matching `lock_id` only.

NOT RUN IN THIS TASK:

### Validate Compose And Proxy Config

```powershell
docker compose -p aftersales-bluegreen-validation -f .\docker-compose.bluegreen.local-test.example.yml config --quiet
docker compose -p aftersales-bluegreen-validation -f .\docker-compose.bluegreen.local-test.example.yml config --services

# If a non-active test proxy Compose/config is approved for the validation:
# docker compose -p aftersales-bluegreen-validation -f .\docker-compose.bluegreen.local-test-proxy.example.yml config --quiet
```

NOT RUN IN THIS TASK:

### Start Test-Only Inactive Target

```powershell
$env:BLUE_GREEN_LOCAL_TEST_PORT = "18080"
docker compose -p aftersales-bluegreen-validation -f .\docker-compose.bluegreen.local-test.example.yml up -d --no-deps --no-build web_green_test
```

NOT RUN IN THIS TASK:

### Health Check Target Port

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18080/healthz/
```

NOT RUN IN THIS TASK:

### Optional Test Proxy Routing On Non-Production Port Only

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:19080/healthz/
```

NOT RUN IN THIS TASK:

### Stop Test-Only Target

```powershell
docker compose -p aftersales-bluegreen-validation -f .\docker-compose.bluegreen.local-test.example.yml stop web_green_test
```

NOT RUN IN THIS TASK:

### Release Matching Lock

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action release -LockPath .\.deploy\bluegreen-nonprod-validation.lock -LockId <matching-lock-id>
```

NOT RUN IN THIS TASK:

### Post-Check Current 8000 Health

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/healthz/
```

## Failure Handling

If future validation fails:

- Do not switch production traffic.
- Do not touch the current `web` service.
- Print target logs for the test-only service.
- Stop only the test-only service started by the validation run.
- Release only the matching validation lock.
- Report failure with the failed gate, target service, test port, lock status,
  and cleanup result.

Rollback in this phase means no production switch occurred. The current web
path remains the fallback and must stay untouched.

## Go / No-Go

- Approval package: READY after review.
- Non-production runtime validation: NO-GO until the exact separate approval
  phrase is provided.
- Production apply: NO-GO.
