# Blue-Green Local Inactive Startup Plan

## Purpose

Prepare a future local-only inactive-color startup test for the blue-green
deployment path.

This plan does not start containers, stop containers, restart containers, build
images, run migrations, run collectstatic, switch traffic, or change
Cloudflare/domain routing. It does not change the active `docker-compose.yml`.
The local-test Compose example is:

```text
docker-compose.bluegreen.local-test.example.yml
```

It is marked EXAMPLE ONLY, NOT ACTIVE, NOT USED BY NORMAL `docker compose`
COMMANDS, LOCAL TEST ONLY, and MUST NOT BIND `8000`.

The local-test Compose example intentionally reuses the existing
`aftersales-web` image for `web_green_test`. It does not declare a build for
the inactive service because the gated startup runner uses `--no-build`. If the
`aftersales-web` image is missing, stop and run a separate explicit image
build/preparation task before any local inactive startup attempt.

The future test must use no production traffic, must not take over host port
`8000`, and must not restart or replace the current `web` service.
Current project commands remain unchanged; normal `docker compose` commands do
not use the local-test example unless `-f docker-compose.bluegreen.local-test.example.yml`
is explicitly supplied.

## Execution-Gated Runner

The local inactive startup runner is:

```powershell
.\scripts\blue_green_local_inactive_startup.ps1
```

Default behavior is dry-run / no-action only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_inactive_startup.ps1
```

The default run prints the future inactive startup plan, current readiness file
status, git status, and current `/healthz/` status if reachable. It does not
start containers, stop containers, restart containers, build images, run
migrations, run collectstatic, switch traffic, change proxy routing, modify
files, call Shopify/Gmail APIs, or send email.

The execution request gate requires this exact phrase:

```text
I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC
```

Real local inactive startup also requires the explicit container-action gate:

```powershell
-AllowContainerAction
```

Without `-AllowContainerAction`, the runner blocks even when the approval phrase
is correct. `-TestPort 8000` is always blocked. `-InactiveService web` is
always blocked because `web` is the current active service name. The active
`docker-compose.yml` is not a valid startup compose file for this runner.
Production remains NO-GO.

The future executable path is local-only and test-only. It validates the
local-test compose file, reuses the existing `aftersales-web` image, starts
only the inactive test service with `--no-deps` and `--no-build`, checks
`/healthz/` on the non-`8000` test port, prints logs for that inactive service
if health fails, and stops only that inactive service during cleanup. This task
must not run that executable path.

## Proposed Inactive Color

- Use one inactive test service only.
- Default service concept: `web_green_test`.
- Default local-test compose file:
  `docker-compose.bluegreen.local-test.example.yml`.
- Default image strategy: reuse existing image `aftersales-web`; do not build
  during local inactive startup.
- Use a non-production local test port such as `18080` or `18081`.
- Do not bind host port `8000`.
- Do not replace, rename, stop, restart, or scale the current `web` service.
- Do not introduce an active proxy or route production traffic to the inactive
  test service.

The inactive test service name and test port must be reviewed again in the
future execution task before any command is run.

## Future Command Groups

All commands in this section are examples for a later task and are marked:

```powershell
# NOT RUN IN THIS TASK
```

They must be reviewed again with the exact inactive service name, compose file,
test port, and cleanup path before future execution.

### Preflight

```powershell
# NOT RUN IN THIS TASK
git status --short --branch
```

```powershell
# NOT RUN IN THIS TASK
docker compose ps
```

```powershell
# NOT RUN IN THIS TASK
Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz/" -UseBasicParsing -TimeoutSec 5
```

### Config Validation

Validate only the future local inactive-startup compose/override files. Do not
validate by loading the active production compose into a changed runtime path.

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.local-test.example.yml config
```

The gated runner's future execution branch validates without printing expanded
config:

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.local-test.example.yml config --quiet
```

The config must show `web_green_test` using image `aftersales-web`. If that
image is not present locally, run a separate reviewed image preparation task
first. Do not add a build step to the inactive startup runner.

If proxy syntax is included in a future local-only test file, validate it
without changing active routing:

```powershell
# NOT RUN IN THIS TASK
docker run --rm -v "${PWD}\nginx\<inactive-test-proxy-file>:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine nginx -t
```

### Start Inactive Color On Test-Only Port

The future startup must target one inactive test service and one non-`8000`
host port, for example `18080` or `18081`. The service must reuse the existing
`aftersales-web` image and the startup command must keep `--no-build`.

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.local-test.example.yml up -d --no-deps --no-build web_green_test
```

### Check `/healthz/` On Inactive Color

```powershell
# NOT RUN IN THIS TASK
Invoke-WebRequest -Uri "http://127.0.0.1:18080/healthz/" -UseBasicParsing -TimeoutSec 5
```

### Inspect Inactive Logs

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.local-test.example.yml logs --tail=100 web_green_test
```

### Stop Inactive Color Only

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.local-test.example.yml stop web_green_test
```

### Cleanup

Cleanup must be limited to the inactive local test service from the approved
future task. It must not remove volumes, prune Docker resources, stop the
current `web`, or change active routing.

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.local-test.example.yml stop web_green_test
```

## Safety Gates Before Future Execution

- Exact approval phrase is required:
  `I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC`.
- `-AllowContainerAction` is required before any future real local startup.
- Current `/healthz/` on port `8000` must pass before inactive startup.
- Git status must be reviewed.
- Active `docker-compose.yml` must remain unchanged.
- Existing image `aftersales-web` must be present before startup, or a separate
  explicit image build/preparation task must be run first.
- Startup compose file must be the reviewed local-test example, not the active
  `docker-compose.yml`.
- Inactive service must not bind host port `8000`.
- Inactive service must not be named `web`.
- The runner blocks `-TestPort 8000` and `-InactiveService web`.
- Cleanup command must be prepared before startup.
- Current `web` must remain untouched.
- The inactive service name, compose file, and test port must be explicitly
  named in the future task.
- No production traffic, Cloudflare/domain routing change, proxy takeover, or
  active port ownership change may be included.

## Failure Handling

If the inactive color fails:

- Do not switch traffic.
- Do not touch current `web`.
- Collect inactive logs only.
- Stop the inactive service only.
- Report the failure.

Do not run migrations, collectstatic, automatic rollback, destructive Docker
cleanup, volume removal, proxy reload, Cloudflare/domain routing changes, or
external API writes as part of failure handling.

## Go / No-Go

- Plan: READY.
- Local-test Compose example: READY as a non-active local-only example.
- Execution-gated runner: READY for dry-run / no-action status checks and for a
  future local-only startup path only after all gates are supplied.
- Local inactive startup: NO-GO in this task. Future execution requires the
  exact approval phrase, `-AllowContainerAction`, a non-`8000` test port, an
  inactive service other than `web`, the reviewed local-test compose file, and
  an existing `aftersales-web` image prepared by a separate task if needed.
- Real inactive startup execution: implemented behind gates but not run in this
  task.
- Next phase: decide whether to run the gated local startup path and capture the
  output without changing production traffic.
- Production: NO-GO.
- Runtime behavior changed by this plan: no.
