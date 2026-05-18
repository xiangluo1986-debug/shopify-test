# Blue-Green Local Inactive Startup Plan

## Purpose

Prepare a future local-only inactive-color startup test for the blue-green
deployment path.

This plan does not start containers, stop containers, restart containers, build
images, run migrations, run collectstatic, switch traffic, or change
Cloudflare/domain routing. It does not change the active `docker-compose.yml`.

The future test must use no production traffic, must not take over host port
`8000`, and must not restart or replace the current `web` service.

## Proposed Inactive Color

- Use one inactive test service only.
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
docker compose -f <inactive-startup-compose-file> config
```

If proxy syntax is included in a future local-only test file, validate it
without changing active routing:

```powershell
# NOT RUN IN THIS TASK
docker run --rm -v "${PWD}\nginx\<inactive-test-proxy-file>:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine nginx -t
```

### Start Inactive Color On Test-Only Port

The future startup must target one inactive test service and one non-`8000`
host port, for example `18080` or `18081`.

```powershell
# NOT RUN IN THIS TASK
docker compose -f <inactive-startup-compose-file> up -d <inactive-test-service>
```

### Check `/healthz/` On Inactive Color

```powershell
# NOT RUN IN THIS TASK
Invoke-WebRequest -Uri "http://127.0.0.1:<inactive-test-port>/healthz/" -UseBasicParsing -TimeoutSec 5
```

### Inspect Inactive Logs

```powershell
# NOT RUN IN THIS TASK
docker compose -f <inactive-startup-compose-file> logs --tail=100 <inactive-test-service>
```

### Stop Inactive Color Only

```powershell
# NOT RUN IN THIS TASK
docker compose -f <inactive-startup-compose-file> stop <inactive-test-service>
```

### Cleanup

Cleanup must be limited to the inactive local test service from the approved
future task. It must not remove volumes, prune Docker resources, stop the
current `web`, or change active routing.

```powershell
# NOT RUN IN THIS TASK
docker compose -f <inactive-startup-compose-file> rm -f <inactive-test-service>
```

## Safety Gates Before Future Execution

- Exact approval phrase is required:
  `I_APPROVE_LOCAL_ONLY_BLUE_GREEN_SIMULATION_NO_PRODUCTION_TRAFFIC`.
- Current `/healthz/` on port `8000` must pass before inactive startup.
- Git status must be reviewed.
- Active `docker-compose.yml` must remain unchanged.
- Inactive service must not bind host port `8000`.
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
- Local inactive startup: NO-GO until separate approval.
- Production: NO-GO.
- Runtime behavior changed by this plan: no.
