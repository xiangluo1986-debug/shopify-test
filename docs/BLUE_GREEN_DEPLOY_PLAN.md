# Blue-Green Deploy Plan

## Scope

This document is a design and dry-run plan only. It does not apply production changes, restart containers, switch traffic, change proxy configuration, call Shopify APIs, call Gmail APIs, or write external data.

The current production-safety foundation remains:

- Public lightweight `/healthz/` endpoint.
- `scripts/safe_deploy.ps1` validation and post-restart health check.
- `scripts/safe_deploy.ps1` real-mode deployment lock enforcement plus
  dry-run/check-only lock awareness.
- Deployment lock helper, design document, and read-only dry-run helper.
- `docs/SAFE_DEPLOY.md` operational notes.
- No secrets, logs, or generated deployment output committed.

## Non-Active Draft Artifacts

The following files are drafts for future review only. They are not active,
are not referenced by the current `docker-compose.yml`, and do not switch
traffic or change current deployment commands:

- [docker-compose.bluegreen.example.yml](../docker-compose.bluegreen.example.yml)
- [docker-compose.bluegreen.local-test.example.yml](../docker-compose.bluegreen.local-test.example.yml)
- [nginx/bluegreen.example.conf](../nginx/bluegreen.example.conf)
- [BLUE_GREEN_DEPLOY_APPLY_CHECKLIST.md](BLUE_GREEN_DEPLOY_APPLY_CHECKLIST.md)
- [BLUE_GREEN_DEPLOY_DECISIONS.md](BLUE_GREEN_DEPLOY_DECISIONS.md)
- [BLUE_GREEN_DEPLOY_LOCAL_DRY_RUN_REVIEW.md](BLUE_GREEN_DEPLOY_LOCAL_DRY_RUN_REVIEW.md)
- [BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md](BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md)
- [DEPLOYMENT_LOCK.md](DEPLOYMENT_LOCK.md)
- [scripts/deploy_lock.ps1](../scripts/deploy_lock.ps1)
- [BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md](BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md)
- [scripts/deploy_lock_dry_run.ps1](../scripts/deploy_lock_dry_run.ps1)
- [scripts/blue_green_local_apply_simulation_preview.ps1](../scripts/blue_green_local_apply_simulation_preview.ps1)
- [scripts/blue_green_local_apply_simulation.ps1](../scripts/blue_green_local_apply_simulation.ps1)
- [scripts/blue_green_local_inactive_startup.ps1](../scripts/blue_green_local_inactive_startup.ps1)
- [BLUE_GREEN_NON_PRODUCTION_VALIDATION.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION.md)
- [scripts/blue_green_production_apply.ps1](../scripts/blue_green_production_apply.ps1)

The read-only planner at `scripts/blue_green_deploy_dry_run.ps1` reports
whether these draft files and review packages exist and whether the active
Compose file still appears to use the current single-web workflow. The local
apply simulation preview script is also read-only and only prints status,
approval-marker state, current `/healthz/` status, and future command examples.
The gated local simulation runner at
`scripts/blue_green_local_apply_simulation.ps1` is dry-run / no-action only in
this phase. It prints readiness and the future local simulation plan, blocks
execution requests without the exact approval phrase, and still does not
implement real local simulation execution even when the phrase is supplied.
The local inactive-color startup plan documents a local-only startup path;
inactive startup remains NO-GO unless a separate task approves one inactive
service, a non-`8000` test port, `-AllowContainerAction`, and cleanup commands.
The execution-gated local inactive startup runner at
`scripts/blue_green_local_inactive_startup.ps1` is dry-run / no-action by
default. It blocks `-TestPort 8000`, blocks `-InactiveService web`, blocks the
active `docker-compose.yml` as the startup compose file, requires the exact
phrase
`I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC` for any
execution request, and requires `-AllowContainerAction` before any future local
container action. The default compose path is the non-active local-test example
`docker-compose.bluegreen.local-test.example.yml`. That local-test example
reuses the existing `aftersales-web` image for `web_green_test` and does not
declare a build for the inactive service because the runner intentionally uses
`--no-build`. If the image is missing, run a separate explicit image
build/preparation task before attempting local inactive startup.

The production apply skeleton at
`scripts/blue_green_production_apply.ps1` is skeleton only / no-action by
default. It prints the future production apply plan, required non-production
validation gate, required deployment lock flow, and approval gate, then exits
without acquiring the production lock,
running Docker commands, running migrations, running collectstatic, switching
traffic, or modifying files. The required approval phrase for a future
execution request is:

```text
I_APPROVE_PRODUCTION_BLUE_GREEN_APPLY_WITH_DEPLOYMENT_LOCK
```

Even with the correct approval phrase, real production blue-green apply remains
blocked in this skeleton phase and prints:

```text
Real production blue-green apply is not implemented in this phase.
```

Production remains NO-GO.

The non-production validation plan exists at
[BLUE_GREEN_NON_PRODUCTION_VALIDATION.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION.md).
Production apply remains blocked until a separate non-production runtime
validation passes and manual production approval is given.

## Deployment Lock Gate

`scripts/safe_deploy.ps1` now enforces the deployment lock in real mode.
`scripts/blue_green_production_apply.ps1` now documents the future production
apply lock gates, but remains no-action and does not implement real apply.
Production blue-green apply must still not proceed until a future phase
implements and validates the same lock rule in the exact runtime-changing
blue-green path. The shared lock is documented in
[DEPLOYMENT_LOCK.md](DEPLOYMENT_LOCK.md), with the runtime-only path:

```text
.deploy/deploy.lock
```

Any future production deploy, proxy switch, restart, rolling update, or cleanup
must acquire the deployment lock before changing runtime state. If the lock is
already present, the operation should block and print sanitized lock owner
metadata for manual review.

Deployment tasks should not auto-queue behind the lock. If a second deploy task
sees the lock, it should stop and require a manual rerun after the first deploy
is complete. Normal non-deploy tasks are not blocked by this deployment lock.

The successful local inactive-color startup on non-production port `18080`
confirmed that a local inactive test service can reach `/healthz/`, but it does
not remove the need for the deployment lock. The lock addresses a separate
risk: overlapping deployment tasks racing with each other.

Runtime-changing actions covered by this rule include container start,
container stop, container restart, image build, migration, collectstatic, proxy
switch, traffic switch, blue/green cleanup, production apply, and rollback. A
future rollback is also runtime-changing if it switches proxy upstreams,
starts/stops services, restarts a service, or restores a previous runtime
target.

Every future runtime-changing blue-green script must acquire the deployment
lock before the first runtime action. If the lock exists, it must block and
exit non-zero, not auto-queue. It must release only the matching `lock_id` in
cleanup/finally handling. Stale locks require manual review before release.
Normal non-deploy tasks are not blocked.

## Deployment Lock Coverage Status

- Real helper exists: `scripts/deploy_lock.ps1`.
- Read-only helper: `scripts/deploy_lock_dry_run.ps1`.
- `safe_deploy.ps1`: enforced in real mode.
- `scripts/safe_deploy.ps1` reports lock status in `-DryRun` and supports
  `-CheckDeployLock`.
- `scripts/safe_deploy.ps1` acquires the lock in real non-dry-run mode before
  build/check/migrate/collectstatic/restart/health check, then releases only
  the matching `lock_id` in cleanup/finally handling.
- Blue-green production apply skeleton:
  `scripts/blue_green_production_apply.ps1`; no-action by default and real
  apply remains blocked.
- Proxy switch script: not implemented yet.
- Cleanup script: not implemented yet.
- Local inactive startup: separate local-only gate, not production traffic.
- Production apply: NO-GO until a future runtime-changing implementation uses
  the deployment lock before any build/start/migrate/collectstatic/proxy
  switch/cleanup action.

## Current Architecture

The current Docker Compose topology has three services:

- `db`: PostgreSQL with a named data volume and a host port mapping for database access.
- `web`: Django app built from `./backend`, using `.env` by reference, mounting backend source, read-only workflow logs, and shared media, and publishing host port `8000` to container port `8000`.
- `scheduler`: Django scheduler built from `./backend`, using `.env` by reference, sharing backend source and media, depending on `db` and `web`, and running `run_scheduler.sh`.

There is currently one `web` container. There is no nginx, Caddy, Traefik, HAProxy, or other reverse proxy service in `docker-compose.yml`. There is also no Compose service-level healthcheck.

Because `web` publishes `8000:8000`, any local Cloudflare tunnel, host-level proxy, or direct browser access that targets `127.0.0.1:8000` reaches the single Django web service directly unless another external proxy exists outside this Compose file.

The health endpoint is implemented at:

```text
/healthz/
```

It returns a simple text response and does not call Shopify, Gmail, OpenAI, Trustpilot, Kudosi, Ali Reviews, or other external services.

## Current Problem

`scripts/safe_deploy.ps1` improves safety by building first, running Django checks, optionally running migrations and collectstatic, then restarting `web` and polling `/healthz/`.

This reduces the risk of leaving the site broken after a deploy, but it cannot eliminate update-time downtime because there is only one web container serving traffic. During `docker compose up -d web`, image/container replacement can briefly make the app unavailable. Requests during that window may see server errors or connection failures even when the new container becomes healthy shortly afterward.

The main remaining deployment-time risk is therefore single-container restart downtime, plus occasional Windows Docker engine pipe instability such as `Access is denied` errors when the Docker client cannot reach the engine.

## Options Compared

### Option A: Blue-Green Web Services With A Stable Proxy

Add two web services, such as `web_blue` and `web_green`, behind a local reverse proxy. Only one color receives production traffic at a time. The inactive color is built, started, and health-checked before traffic is switched.

Benefits:

- Active color keeps serving while inactive color starts.
- Traffic switch is fast and reversible.
- Rollback is usually a proxy upstream switch back to the previous color.
- Works well with `/healthz/`.
- Can be introduced gradually with a staging or local-only proxy first.

Costs and risks:

- Requires a proxy layer and new operational commands.
- Needs a clear source of truth for the active color.
- Requires careful database migration discipline so old and new code can run during the switch window.
- Initial introduction of the proxy may require a planned one-time traffic path change.

Fit for this project: recommended target architecture.

### Option B: Rolling Deployment With Two Web Replicas And A Proxy

Run at least two equivalent web containers behind a reverse proxy and update them one at a time.

Benefits:

- Familiar pattern for horizontally scaled apps.
- No named color concept once the proxy/load balancer is in place.
- Can maintain service while one replica is replaced.

Costs and risks:

- Current `web` service publishes `8000:8000`, so it cannot simply be scaled to multiple host-published replicas without changing the port/proxy model.
- Docker Compose rolling update behavior is less complete than orchestrators such as Kubernetes or Docker Swarm.
- Requires shared/static/media behavior to be reviewed for multiple web containers.
- Database migration compatibility concerns remain.

Fit for this project: useful later if the app needs steady multi-replica capacity, but less direct than blue-green for the current single-host Compose setup.

### Option C: Short-Term Hardening Without Blue-Green

Keep the current single `web` container but improve checks and operator guidance.

Possible hardening:

- Keep using `/healthz/` before and after deploys.
- Keep using `safe_deploy.ps1`.
- Add documentation that single-container restart downtime is still expected.
- Add a read-only dry-run planner for future blue-green checks.
- Consider a future Compose healthcheck, but do not activate it in this task.
- Schedule deploys during low-traffic windows.

Benefits:

- Minimal change and low operational risk.
- Does not change current commands.

Limits:

- Does not eliminate downtime during the actual web container restart.
- Rollback still requires another restart/redeploy.

Fit for this project: appropriate short-term baseline until the proxy and blue-green plan are reviewed.

## Recommended Target Architecture

Use Option A: blue-green Django web services behind a stable local reverse proxy.

Target shape:

```text
Cloudflare / external domain
        |
        v
stable local proxy on the Docker host
        |
        +--> active: web_blue:8000
        |
        +--> standby: web_green:8000

db and scheduler remain separate services.
```

The proxy should be the only service exposed on the stable external port. The color web containers should be reachable only on the Docker network or on controlled local-only ports used for health checks.

Future deployment flow:

1. Acquire the deployment lock before any runtime-changing action.
2. Identify active color.
3. Build or start the inactive color.
4. Run Django checks against the inactive color.
5. Run a direct inactive-color `/healthz/` check.
6. Switch proxy traffic to the inactive color only after health passes.
7. Run public `/healthz/` through the stable domain.
8. Keep the previous color running briefly for rollback.
9. Stop the previous color only after the new color has been stable for an agreed observation window.
10. Release the deployment lock in cleanup/finally handling.

This reduces update-time server errors because the serving container is not replaced while it is receiving traffic. Users continue hitting the old color until the new color has already started and passed health checks.

## Phased Rollout Plan

### Phase 0: Design And Dry Run

Current task. Documentation and optional read-only planner only.

Allowed:

- Inspect Compose topology.
- Document blue-green design.
- Clarify current safe deploy limitations.
- Run read-only validation.

Not allowed:

- Restart production.
- Run `docker compose up`, `docker compose down`, or `docker compose restart`.
- Switch traffic.
- Modify live proxy configuration.
- Call external write APIs.

### Phase 1: Draft Proxy And Compose Design

Current draft artifacts for human review.

The non-active draft files propose:

- `proxy`.
- `web_blue`.
- `web_green`.
- Internal-only web networking.
- Proxy health routing.

They do not replace the current production command. Any apply work still
requires a separate approved task.

### Phase 2: Local Or Staging Validation

Future task after Phase 1 review.

Non-production validation is documented in
[BLUE_GREEN_NON_PRODUCTION_VALIDATION.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION.md).
It may be local-only or staging, must use a non-production Compose/project
scope and non-`8000` test ports, must not change Cloudflare/domain routing,
and must leave the current production web path untouched. Runtime validation
requires the deployment lock and a separate approval.

Local validation remains NO-GO unless separately approved. The current gated
runner is available only for dry-run / no-action status checks:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_apply_simulation.ps1
```

An actual inactive-color startup path now exists for future local-only use only
after
[BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md](BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md)
and
[BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md](BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md)
are reviewed, the exact local-only approval phrase is provided in a separate
task, `-AllowContainerAction` is supplied, and the exact commands, target color,
non-`8000` test port, cleanup path, and no-production-traffic constraints are
approved.
The current startup runner path is
`scripts/blue_green_local_inactive_startup.ps1`; its default behavior is
dry-run only, and the required inactive-startup phrase is
`I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC`.
`TestPort` must not be `8000`, `InactiveService` must not be `web`, the active
`docker-compose.yml` must not be used for this local startup path, and correct
Ack alone is blocked unless `-AllowContainerAction` is present. The local-test
inactive service reuses image `aftersales-web`; the startup path does not build
images. If that image is not present, image preparation must be handled by a
separate reviewed task first.

Validate the proxy and color services locally or in staging:

- Confirm both colors can start.
- Confirm `/healthz/` works directly for each color.
- Confirm proxy routes only to the active color.
- Confirm rollback switch behavior.
- Confirm scheduler behavior is unchanged.
- Confirm media and static file behavior.

### Phase 3: One-Time Traffic Path Introduction

Future task requiring explicit production approval.

Introduce the proxy as the stable traffic endpoint. This may require a planned maintenance window because the current traffic path likely targets the single `web` service on host port `8000`.

Manual decision needed: either keep the public host port stable by moving port `8000` to the proxy, or change the Cloudflare/local tunnel target to a new proxy port.

### Phase 4: Blue-Green Deploy Operation

Future task requiring explicit production approval.

Use the inactive color deployment flow and switch proxy traffic only after health checks pass.

### Phase 5: Later Rolling Scale Option

After blue-green is stable, consider whether steady two-replica rolling deployment is worth adding. This is optional and should be driven by traffic and operational needs.

## Rollback Plan

Before traffic switch:

- If inactive color build, checks, or direct `/healthz/` fails, do not switch traffic.
- Leave the active color untouched.
- Inspect logs for the inactive color.

After traffic switch:

- If public `/healthz/`, admin smoke checks, or user traffic shows errors, switch the proxy back to the previous color.
- Keep the previous color running during the observation window so rollback does not require a rebuild.
- Inspect new-color logs only after traffic has been returned to the stable color if the issue is customer-facing.

Database rollback:

- Do not depend on automatic database rollback.
- Prefer backward-compatible migrations: expand first, deploy compatible code, contract later.
- Review migrations before any deploy that changes models.
- Take backups according to the production database process before risky migrations.

## Commands For A Future Apply Task

These examples are documentation only.

NOT RUN IN THIS TASK:

```powershell
docker compose build web_green
docker compose up -d web_green
docker compose exec -T web_green python manage.py check
```

NOT RUN IN THIS TASK:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:<green-health-port>/healthz/" -UseBasicParsing
```

NOT RUN IN THIS TASK:

```powershell
# Example only. Actual command depends on the chosen proxy.
# Switch proxy upstream from web_blue to web_green, then reload proxy.
```

NOT RUN IN THIS TASK:

```powershell
Invoke-WebRequest -Uri "https://tickets.kidstoyloverapps.com/healthz/" -UseBasicParsing
```

NOT RUN IN THIS TASK:

```powershell
# If needed, switch proxy upstream back to the previous color.
```

## Manual Decisions Before Applying

The detailed manual review package is
[BLUE_GREEN_DEPLOY_DECISIONS.md](BLUE_GREEN_DEPLOY_DECISIONS.md). It now records
conservative defaults approved for local-only planning, while local runtime
changes and production apply both remain blocked until separate apply tasks
approve exact commands.

- Proxy technology default: nginx, example-only until apply phase.
- Port ownership default: current `web` service keeps host port `8000` until
  a separate approval changes it.
- Cloudflare/external routing default: no local-only routing change; production
  routing requires separate approval.
- Active color tracking default: future file-based marker, documented as
  draft/example only until an apply task creates real runtime state.
- Migration default: backward-compatible migrations only during blue-green
  switch; risky schema changes require separate planning.
- Static/media default: shared media unchanged and current safe-deploy static
  behavior retained until apply design is finalized.
- Scheduler default: singleton scheduler only; no blue/green scheduler
  replicas.
- Rollback default: manual admin approval, old color kept running, and at least
  10 minutes of local/test observation.
- First apply scope: local-only apply dry-run first; production remains NO-GO.
- Confirm Windows Docker Compose behavior on the production host.
- Confirm Cloudflare tunnel or external domain routing outside this repository without exposing tokens.

## Risks And Limitations

- Blue-green reduces web restart downtime, but it does not make incompatible database migrations safe.
- The scheduler may still need separate handling if scheduler code changes are coupled to web code or migrations.
- The first introduction of a proxy can itself require a planned traffic path change.
- Docker Desktop or Windows named pipe instability can still block Docker commands.
- Health checks only prove the health endpoint works; admin and key workflows still need smoke checks.
- This plan does not include Shopify, Gmail, Trustpilot, Kudosi, Ali Reviews, or translation write operations.

## Immediate Next Task Recommendation

Review the dry-run output from
`scripts/blue_green_local_apply_simulation.ps1`,
`scripts/blue_green_local_apply_simulation_preview.ps1`,
`scripts/blue_green_local_inactive_startup.ps1`, and
`scripts/blue_green_production_apply.ps1`.
The recommended next separate task is to review the production apply skeleton
output and decide the next non-production validation phase for exact route,
port ownership, proxy, scheduler, migration, static/media, rollback,
observation, and deployment lock handling. Production should remain NO-GO until
local or staging results are reviewed and a separate production task approves
the exact runtime path being used.
