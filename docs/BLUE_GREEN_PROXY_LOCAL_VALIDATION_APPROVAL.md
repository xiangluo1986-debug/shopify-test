# Blue-Green Proxy Local Validation Approval

## Purpose

Record the local/test proxy routing validation for the blue-green deployment
path and keep any future rerun behind the same local-only gates.

This approval package does not approve production. It does not run commands,
start containers, start nginx, switch traffic, or change runtime behavior.

The completed validation proved only this local/test path:

- Start the inactive test service on local port `18080` with hold-open mode
  from the unified proxy validation Compose example.
- Start or validate a test-only proxy on local port `19080` from the same
  unified Compose example.
- Confirm proxy `/healthz/` routes to the inactive test service.
- Clean up only the test proxy and inactive test service.
- Leave the current `web` service and production traffic untouched.

Hold-open mode is required before proxy validation because the inactive
startup runner otherwise stops `web_green_test` immediately after its direct
health check. Hold-open mode is local/test only and does not approve
production.

A previous manual proxy validation failed because `web_green_test` and
`bluegreen_proxy_test` were launched from separate Compose projects/networks.
nginx logged `host not found in upstream "web_green_test:8000"` even though
`web_green_test` was running and healthy in its own project. The passed
validation used `docker-compose.bluegreen.proxy-validation.example.yml` so both
test services shared one Docker network and nginx could resolve
`web_green_test:8000`.

## Validation Result - 2026-05-19

- Validation status: PASSED.
- Scope: local/test proxy routing only.
- Unified Compose file:
  `docker-compose.bluegreen.proxy-validation.example.yml`.
- Inactive web test port: `18080`.
- Proxy test port: `19080`.
- Inactive service: `web_green_test`.
- Proxy service: `bluegreen_proxy_test`.
- `8000 /healthz/` before validation: HTTP 200 OK.
- `18080 /healthz/` during validation: HTTP 200 OK.
- `19080 /healthz/` during validation: HTTP 200 OK.
- `docker compose ps` during validation showed `bluegreen_proxy_test` running
  on `19080` and `web_green_test` running healthy on `18080`.
- Cleanup stopped only `bluegreen_proxy_test` and `web_green_test`.
- Cleanup succeeded; `bluegreen_proxy_test` and `web_green_test` stopped.
- `8000 /healthz/` after cleanup: HTTP 200 OK.
- `18080` after cleanup: not serving / unable to connect.
- `19080` after cleanup: not serving / unable to connect.
- `docker compose ps` after cleanup showed no running validation services.
- Current `web` was not targeted.
- Port `8000` was not targeted.
- Production traffic switch: no.
- Migrations/collectstatic: no.
- External APIs: no Shopify, Gmail, Trustpilot, Kudosi, Ali Reviews, or email
  send path was requested.
- Production status: still NO-GO.

This result records a successful local/test proxy routing validation only. It
does not approve production apply, production proxy changes, traffic switching,
migrations, collectstatic, or external API workflows.

## Explicit Non-Goals

- No production traffic switch.
- No Cloudflare, DNS, tunnel, or domain routing change.
- No port `8000` ownership change.
- No current `web` restart.
- No migration.
- No collectstatic.
- No external API write or send.
- No Shopify API call.
- No Gmail API call.
- No email send.
- No Trustpilot, Kudosi, or Ali Reviews action.

## Required Approval Phrase For Future Reruns

The 2026-05-19 local/test validation is recorded as PASSED. Any future rerun
that starts test-only services remains NO-GO until a separate task provides
this exact approval phrase:

```text
I_APPROVE_LOCAL_PROXY_ROUTING_VALIDATION_NO_PRODUCTION_TRAFFIC
```

## Fixed Future Validation Parameters

- Inactive web test port: `18080`.
- Proxy test port: `19080`.
- Compose project name: `aftersales-bluegreen-proxy-validation`.
- Unified Compose example:
  `docker-compose.bluegreen.proxy-validation.example.yml`.
- Lock path: `.deploy/bluegreen-proxy-validation.lock`.
- Target inactive service: `web_green_test`.
- Test proxy service: `bluegreen_proxy_test`.
- Current web service: must remain untouched.
- Production port `8000`: must not be used.
- Production traffic: no switch.
- Hold-open startup: required before the proxy test.
- Cleanup after proxy test: mandatory; stop only `bluegreen_proxy_test` and
  `web_green_test`.

## Safety Gates Before Future Run

Before a future local/test proxy routing validation run, confirm:

- `git status` has been reviewed.
- `http://127.0.0.1:8000/healthz/` is OK.
- `18080` is not serving before the test.
- `19080` is not serving before the test.
- Deployment lock helper is available.
- No existing deploy lock is present.
- Unified proxy validation Compose example has been reviewed.
- Inactive target is not `web`.
- Proxy test port is not `8000`.
- Inactive startup uses `-HoldOpenForProxyValidation`.
- Cleanup command is ready.
- Rollback/no-switch plan is ready.
- Production apply remains NO-GO.

If any gate is uncertain, stop before starting test-only services.

## Future Command Groups

All commands in this section are examples for a future separately approved
validation task.

NOT RUN IN THIS TASK:

### Lock Status

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action status -LockPath .\.deploy\bluegreen-proxy-validation.lock
```

NOT RUN IN THIS TASK:

### Acquire Proxy Validation Lock

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 `
  -Action acquire `
  -LockPath .\.deploy\bluegreen-proxy-validation.lock `
  -Purpose "blue-green-proxy-validation" `
  -Target "local-proxy-routing"
```

Record the printed `lock_id`. Release must use the matching `lock_id`.

NOT RUN IN THIS TASK:

### Validate Unified Proxy Validation Compose And Config

```powershell
docker compose `
  -f .\docker-compose.bluegreen.proxy-validation.example.yml `
  config
```

The rendered config must publish only `18080:8000` and `19080:80`; it must not
publish host port `8000`.

NOT RUN IN THIS TASK:

### Start Inactive Test Service On 18080 With Hold-Open

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_inactive_startup.ps1 `
  -ExecuteInactiveStartup `
  -HoldOpenForProxyValidation `
  -Ack I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC `
  -AllowContainerAction `
  -ComposeFile .\docker-compose.bluegreen.proxy-validation.example.yml `
  -InactiveService web_green_test `
  -TestPort 18080
```

Expected hold-open message after direct health passes:

```text
Hold-open mode active: web_green_test remains running for proxy validation.
docker compose -f docker-compose.bluegreen.proxy-validation.example.yml stop web_green_test
You must run cleanup after proxy validation.
```

NOT RUN IN THIS TASK:

### Start Test Proxy On 19080

```powershell
docker compose `
  -f .\docker-compose.bluegreen.proxy-validation.example.yml `
  up -d --no-deps --no-build bluegreen_proxy_test
```

NOT RUN IN THIS TASK:

### Check Proxy Health Route

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:19080/healthz/
```

NOT RUN IN THIS TASK:

### Stop Test Proxy Only

```powershell
docker compose `
  -f .\docker-compose.bluegreen.proxy-validation.example.yml `
  stop bluegreen_proxy_test

docker compose `
  -f .\docker-compose.bluegreen.proxy-validation.example.yml `
  rm -f bluegreen_proxy_test
```

NOT RUN IN THIS TASK:

### Stop Inactive Test Service Only

```powershell
docker compose `
  -f .\docker-compose.bluegreen.proxy-validation.example.yml `
  stop web_green_test

docker compose `
  -f .\docker-compose.bluegreen.proxy-validation.example.yml `
  rm -f web_green_test
```

The minimum mandatory cleanup after hold-open proxy validation is:

```powershell
docker compose -f docker-compose.bluegreen.proxy-validation.example.yml stop bluegreen_proxy_test web_green_test
```

Cleanup must stop only `bluegreen_proxy_test` and `web_green_test`. It must not
stop the current `web`, must not run `docker compose down`, and must not remove
volumes.

NOT RUN IN THIS TASK:

### Release Matching Lock ID

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 `
  -Action release `
  -LockPath .\.deploy\bluegreen-proxy-validation.lock `
  -LockId <matching-lock-id>
```

NOT RUN IN THIS TASK:

### Post-Check Current 8000 Health

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/healthz/
```

NOT RUN IN THIS TASK:

### Confirm Test Ports Are Not Serving After Cleanup

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18080/healthz/
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:19080/healthz/
```

Both commands should fail to connect after cleanup.

## Failure Handling

If future local/test proxy routing validation fails:

- Do not switch production traffic.
- Do not touch the current `web` service.
- Print target and proxy logs for manual review.
- Stop the test proxy only.
- Stop the inactive test service only.
- Release the matching deployment lock.
- Report failure with the failed gate, target service, proxy service, test
  ports, and cleanup result.

Rollback in this validation means no production switch occurred. The current
production path should remain unchanged.

## Go / No-Go

- Approval package: validation result RECORDED.
- Local/test proxy routing validation: PASSED on 2026-05-19 for local/test
  proxy routing only.
- Production apply: NO-GO.
- Next required step: production preflight design / production apply readiness
  review.
- Migration compatibility and scheduler singleton behavior still must be
  checked before any production apply.
