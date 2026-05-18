# Blue-Green Local Dry-Run Review

## Purpose

This document is a local review package only. It lists the future commands,
checks, rollback steps, and safety gates needed before any real local
blue-green apply.

No deploy, restart, container replacement, migration, proxy reload, traffic
switch, Cloudflare change, Shopify action, Gmail action, or external write is
performed by this document.

Production remains NO-GO.

The next local-only gate is the approval package:
[BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md](BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md).
That package prepares a future simulation but still does not run it.

## Preconditions

Before a separate local apply task can run, confirm:

- Git is clean or contains only expected reviewed files.
- Latest `main` has been pulled and reviewed.
- Docker access is working on the Windows host.
- Current `/healthz/` returns OK through the existing active service.
- `python manage.py check` passes for the current active service.
- The active `docker-compose.yml` remains unchanged.
- The current active service still owns host port `8000`.
- The rollback plan below has been reviewed by the operator.
- No migration, scheduler, static/media, or proxy change is being bundled into
  the first local apply simulation.
- The local apply simulation approval package has been reviewed.
- The exact approval phrase is present before any future simulation command is
  run:

```text
I_APPROVE_LOCAL_ONLY_BLUE_GREEN_SIMULATION_NO_PRODUCTION_TRAFFIC
```

## Future Local-Only Dry-Run Command Sequence

Every command in this section is documentation only and is marked:

```powershell
# NOT RUN IN THIS TASK
```

These commands must be re-reviewed in a separate local apply task before any of
them are run.

### Inspect Current Status

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

```powershell
# NOT RUN IN THIS TASK
docker compose exec -T web python manage.py check
```

### Validate Draft Compose And Proxy Files

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.example.yml config
```

If an nginx image is already available or image use is separately approved,
validate the draft proxy syntax without changing active routing:

```powershell
# NOT RUN IN THIS TASK
docker run --rm -v "${PWD}\nginx\bluegreen.example.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine nginx -t
```

### Prepare The Inactive Color Only

Assumption for the first local simulation: current active stays `web`, and the
inactive test color is `web_green`. If a later task determines that green is
active, swap the inactive target to `web_blue`.

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.example.yml build web_green
```

The existing example compose omits production secrets and host port binding on
purpose. A separate local apply task must approve the exact local apply compose
file and environment handling before any start command is run.

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.example.yml up -d web_green
```

### Check The Inactive Color Only

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.example.yml exec -T web_green python manage.py check
```

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.example.yml exec -T web_green python -c "import urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8000/healthz/', timeout=5); print(response.status)"
```

### Confirm No Production Routing Change

```powershell
# NOT RUN IN THIS TASK
docker compose ps
```

Manual checks for the future local apply task:

- `docker-compose.yml` still owns the active `web` service and host port `8000`.
- No Cloudflare tunnel, public domain, DNS, or external proxy target is changed.
- No active production proxy config is edited, copied, or reloaded.
- No traffic is switched to `web_green`.

## Future Local-Only Apply Simulation Outline

A future local apply simulation should work without external domain traffic:

1. Confirm the active service is healthy and unchanged.
2. Start only the inactive color on the Docker network or on a reviewed
   local-only test port.
3. Do not bind production host port `8000` to the inactive color.
4. Do not change Cloudflare, public domain, tunnel, or external routing.
5. Do not stop the current `web` service.
6. Run `python manage.py check` against the inactive color only.
7. Health-check the inactive color directly through `/healthz/`.
8. Record the inactive color logs and health result.
9. End the simulation with production routing still unchanged.

## Rollback Plan

If inactive validation fails before any approved traffic switch:

- Do not switch traffic.
- Stop only the inactive test color if it was started.
- Leave the current `web` service untouched.
- Collect inactive color logs for review.
- Revert only draft or local-apply files if needed and only after confirming
  they are not active runtime files.
- Do not attempt database rollback unless a separate migration and database
  rollback plan was explicitly approved.

Future rollback commands, if the inactive color was started during a separately
approved local simulation:

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.example.yml logs --tail=100 web_green
```

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.example.yml stop web_green
```

Do not run `docker compose down -v`, volume removal, database flush, destructive
cleanup, or automatic rollback.

## Risk Notes

- Migrations can break blue-green if they are not backward-compatible with both
  old and new code during the switch window.
- The scheduler must remain singleton. Do not run separate blue and green
  scheduler instances.
- Static and media files must be shared safely before two web containers serve
  the same app release path.
- Windows Docker `Access is denied` pipe errors may block validation even when
  the plan is correct.
- Single-container downtime remains until an active apply task approves and
  implements the proxy or blue-green traffic path.
- The draft compose file intentionally avoids production secret handling; a
  future apply task must approve local environment handling without exposing
  private values.

## Go / No-Go

- Local dry-run review: READY after this document is reviewed.
- Local apply simulation approval package: READY after
  [BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md](BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md)
  is reviewed.
- Local simulation: NO-GO until a separate task provides the exact approval
  phrase and exact runtime commands.
- Production apply: NO-GO.
