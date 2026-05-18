# Blue-Green Local Apply Simulation Approval Package

## Purpose

This document prepares a future local-only blue-green apply simulation.

It does not approve production. It does not run anything by itself. It does not
start containers, stop containers, restart containers, switch traffic, run
migrations, change Cloudflare/domain routing, or change current runtime
commands.

## Explicit Non-Goals

- No production traffic switch.
- No Cloudflare, DNS, tunnel, or domain routing change.
- No host port `8000` ownership change.
- No current `web` restart, replacement, or stop.
- No migration.
- No collectstatic.
- No external API write or send.
- No Shopify, Gmail, Trustpilot, Kudosi, Ali Reviews, ticket, translation, or
  settlement workflow change.

## Required Approval Before Future Local Simulation

A future local-only apply simulation remains blocked until a separate task
provides the exact manual approval wording below:

```text
I_APPROVE_LOCAL_ONLY_BLUE_GREEN_SIMULATION_NO_PRODUCTION_TRAFFIC
```

If a future preview or runner checks an environment variable, use:

```powershell
$env:BLUE_GREEN_LOCAL_SIMULATION_ACK = "I_APPROVE_LOCAL_ONLY_BLUE_GREEN_SIMULATION_NO_PRODUCTION_TRAFFIC"
```

The approval phrase authorizes only a future local-only simulation review path.
It does not approve production, traffic switching, port `8000` takeover,
Cloudflare/domain routing changes, migrations, external API writes, email
sends, or Shopify writes.

## Current Gated Runner

The gated local-only simulation runner is:

```powershell
.\scripts\blue_green_local_apply_simulation.ps1
```

Default behavior is dry-run / no-action only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_apply_simulation.ps1
```

The default run prints local readiness, current `/healthz/` status if
reachable, and the future simulation plan. It does not start, stop, restart, or
build containers. It does not run migrations, run collectstatic, switch traffic,
modify files, change Cloudflare/domain routing, call Shopify/Gmail APIs, or
send email.

If execution is requested without the exact approval phrase, the runner blocks
and exits non-zero:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_apply_simulation.ps1 -ExecuteLocalSimulation
```

Even when the exact `-Ack` phrase is supplied, real local simulation execution
is still blocked in this phase. The runner reports:

```text
Real local simulation execution is not implemented in this phase.
```

Production remains NO-GO.

## Current Inactive Startup Runner

The execution-gated local inactive-color startup runner is:

```powershell
.\scripts\blue_green_local_inactive_startup.ps1
```

Default behavior is dry-run / no-action only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_inactive_startup.ps1
```

The runner prints the future local inactive startup plan and exits without
starting, stopping, restarting, or building containers. It does not run
migrations, run collectstatic, switch traffic, change Cloudflare/domain routing,
modify files, call Shopify/Gmail APIs, or send email.

The inactive startup execution gate uses this separate exact approval phrase:

```text
I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC
```

Safety blocks in the runner:

- `-TestPort 8000` is always blocked.
- `-InactiveService web` is always blocked because `web` is the current active
  service.
- Missing or wrong `-Ack` blocks execution requests.
- Even the correct `-Ack` remains blocked in this phase with:

```text
Real inactive startup execution is not implemented in this phase.
```

Production remains NO-GO. The next phase would implement actual local startup
only after a separate approval of exact commands, inactive service name,
non-`8000` test port, cleanup path, and no-production-traffic constraints.

## Future Local Simulation Scope

A future simulation may only:

- Validate example compose/proxy config.
- Start an inactive test color only if separately approved.
- Bind to a non-production test port only.
- Test `/healthz/` on the inactive test color.
- Stop only the inactive test color after validation.
- Leave the current `web` service untouched.

The next phase may implement actual inactive-color startup on a local-only test
port, but only after separate approval of the exact commands, target color,
environment handling, cleanup path, and no-production-traffic constraints.
The reviewed planning artifact for that future step is
[BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md](BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md).
It is a plan only; local inactive startup remains NO-GO until a separate
execution approval task.

The current active `docker-compose.yml` must remain unchanged. The current web
service must keep serving the existing local runtime path while the simulation
is performed.

## Future Command Plan

All commands below are examples for a later approved task and are marked:

```powershell
# NOT RUN IN THIS TASK
```

They must be reviewed again before any future execution.

### Preflight Checks

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

### Example Compose Config Validation

```powershell
# NOT RUN IN THIS TASK
docker compose -f docker-compose.bluegreen.example.yml config
```

If proxy syntax validation is separately approved and does not modify active
runtime routing:

```powershell
# NOT RUN IN THIS TASK
docker run --rm -v "${PWD}\nginx\bluegreen.example.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine nginx -t
```

### Inactive Color Startup On Test-Only Port

The first local simulation should use a reviewed local simulation compose file
or override that binds only a non-production test port. It must not bind host
port `8000`.

```powershell
# NOT RUN IN THIS TASK
docker compose -f <local-simulation-compose-file> up -d web_green
```

### Health Check

Use only the inactive color's reviewed local test port or internal container
health route.

```powershell
# NOT RUN IN THIS TASK
Invoke-WebRequest -Uri "http://127.0.0.1:<inactive-test-port>/healthz/" -UseBasicParsing -TimeoutSec 5
```

```powershell
# NOT RUN IN THIS TASK
docker compose -f <local-simulation-compose-file> exec -T web_green python manage.py check
```

### Logs Inspection

```powershell
# NOT RUN IN THIS TASK
docker compose -f <local-simulation-compose-file> logs --tail=100 web_green
```

### Cleanup Inactive Test Color

Stop only the inactive test color that was started for the approved local
simulation.

```powershell
# NOT RUN IN THIS TASK
docker compose -f <local-simulation-compose-file> stop web_green
```

### Rollback / No-Switch Behavior

Before any production traffic switch is approved, rollback means no switch:

```powershell
# NOT RUN IN THIS TASK
# Leave current web running, leave port 8000 unchanged, and do not change proxy or Cloudflare routing.
```

If a local test color fails:

```powershell
# NOT RUN IN THIS TASK
docker compose -f <local-simulation-compose-file> logs --tail=100 web_green
docker compose -f <local-simulation-compose-file> stop web_green
```

## Safety Gates

Before any future local simulation:

- Git status is reviewed.
- Docker access works.
- Current `/healthz/` service is OK.
- Current `web` remains running.
- Active `docker-compose.yml` is unchanged.
- Approval phrase is present.
- No production port takeover is planned.
- Rollback/cleanup command is ready.
- The inactive color target and local-only test port are explicitly named.
- No migrations or external write/send actions are included.

## Failure Handling

If the inactive test color fails:

- Do not switch traffic.
- Do not touch current `web`.
- Collect inactive logs only.
- Stop the inactive test color only.
- Report failure.

Do not run migrations, automatic rollback, destructive cleanup, volume removal,
or production routing changes as part of failure handling.

## Go / No-Go

- Approval package: READY.
- Local inactive startup plan: READY for review in
  [BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md](BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md).
- Gated simulation runner: dry-run / no-action only.
- Gated inactive startup runner: dry-run / no-action only at
  `scripts/blue_green_local_inactive_startup.ps1`.
- Local simulation execution: NO-GO. The approval phrase is required for a
  future phase, but real execution is not implemented in this phase.
- Local inactive startup: NO-GO until separate approval of exact commands,
  inactive service name, non-`8000` test port, and cleanup path. The current
  runner blocks `-TestPort 8000`, blocks `-InactiveService web`, and still does
  not implement real startup even with the required approval phrase.
- Production: NO-GO.
- Runtime behavior changed by this package: no.
