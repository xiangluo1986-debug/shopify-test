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
- [BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md)
- [BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md](BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md)
- [BLUE_GREEN_PRODUCTION_PREFLIGHT.md](BLUE_GREEN_PRODUCTION_PREFLIGHT.md)
- [BLUE_GREEN_PRODUCTION_APPLY_READINESS.md](BLUE_GREEN_PRODUCTION_APPLY_READINESS.md)
- [BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md](BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md)
- [BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md)
- [BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md)
- [BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md](BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md)
- [docker-compose.bluegreen.proxy-validation.example.yml](../docker-compose.bluegreen.proxy-validation.example.yml)
- [docker-compose.bluegreen.proxy-test.example.yml](../docker-compose.bluegreen.proxy-test.example.yml)
- [nginx/bluegreen.local-test.example.conf](../nginx/bluegreen.local-test.example.conf)
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
build/preparation task before attempting local inactive startup. Hold-open mode
is now available behind the same gates for local/test proxy validation only:
after direct `18080 /healthz/` passes, `web_green_test` remains running so the
test proxy on `19080` can route to it. Cleanup after proxy validation is
mandatory and must stop only test services:

```powershell
docker compose -f docker-compose.bluegreen.proxy-validation.example.yml stop bluegreen_proxy_test web_green_test
```

The current `web`, port `8000`, production traffic, active Compose file,
Cloudflare/domain routing, migrations, collectstatic, Shopify/Gmail/API paths,
and email sending remain out of scope.

The production apply command path skeleton at
`scripts/blue_green_production_apply.ps1` is implemented but blocked. It
prints structured planned phases for preflight, lock, target color preparation,
switch, observe, rollback, and cleanup, then exits without acquiring the
production lock, running Docker commands, running migrations, running
collectstatic, switching traffic, or modifying files. The draft readiness
phrase used only to prove blocked skeleton behavior is:

```text
I_APPROVE_PRODUCTION_BLUE_GREEN_APPLY_AFTER_PREFLIGHT_REVIEW
```

This phrase is NOT ACTIVE for real production apply in this phase. Even with
the draft phrase and valid parameters, real production blue-green apply remains
blocked in this skeleton phase and prints:

```text
Real production blue-green apply command path is implemented as a skeleton only and remains blocked in this phase.
```

Production remains NO-GO.

The final runtime approval design exists at
[BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md](BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md).
It is READY after review, but runtime command execution remains NOT ENABLED,
the documented future approval phrase is inactive, and production apply remains
NO-GO.

The non-production validation plan exists at
[BLUE_GREEN_NON_PRODUCTION_VALIDATION.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION.md).
The separate non-production runtime validation approval package exists at
[BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md).
It records that local inactive runtime validation PASSED on 2026-05-18 for
`web_green_test` on test port `18080` using image `aftersales-web:latest`.
It does not approve production. Local/test proxy routing validation also PASSED
on 2026-05-19. Production apply remains blocked until the production preflight
document is reviewed,
[BLUE_GREEN_PRODUCTION_APPLY_READINESS.md](BLUE_GREEN_PRODUCTION_APPLY_READINESS.md)
is reviewed for exact command readiness, and manual production approval is
given.

The production preflight readiness review exists at
[BLUE_GREEN_PRODUCTION_PREFLIGHT.md](BLUE_GREEN_PRODUCTION_PREFLIGHT.md).
It records the required production checks for deployment lock behavior,
migration compatibility, scheduler singleton behavior, media/static/uploads,
proxy and port ownership, active/target color tracking, health checks,
rollback, observation, cleanup, and data loss prevention. The preflight
document is READY after review, but production apply remains NO-GO.

The production apply readiness checklist and exact command review package
exists at
[BLUE_GREEN_PRODUCTION_APPLY_READINESS.md](BLUE_GREEN_PRODUCTION_APPLY_READINESS.md).
It records the future command groups, safety gates, draft approval phrase, and
remaining production decisions. It is READY after review; the production
command path skeleton is implemented but blocked, production implementation is
NOT READY, exact runtime command implementation is still not enabled, and
production apply remains NO-GO.

The dedicated production runtime command review exists at
[BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md](BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md).
It records the exact future command groups for preflight, deployment lock,
target color preparation, proxy switch, observation, rollback, and cleanup.
It is READY after review, but production implementation is NOT READY, exact
runtime command implementation is still not enabled, and production apply
remains NO-GO.

The production runtime details document exists at
[BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md).
It records conservative defaults for nginx as the proxy candidate, current
`web` ownership of host port `8000` until final approval, production service
names `web_blue`, `web_green`, and `bluegreen_proxy`, active-color state under
`.deploy/active-color.json`, controlled proxy switch shape, rollback to
`previous_color`, at least 10 minutes of first-apply observation,
backward-compatible migration policy, singleton scheduler policy, and shared
media/uploads requirements. Runtime details are READY after review, but active
color state under `.deploy/` must not be committed or contain secrets, exact
runtime commands are still not implemented, and production apply remains
NO-GO.

The production switch/rollback review document exists at
[BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md).
It records the future proxy switch flow, active-color state shape including
`proxy_config_version` and `notes`, atomic state write rule, rollback flow,
cleanup boundaries, and remaining blockers. Switch/rollback review is READY
after review, but exact proxy switch/reload and rollback commands are still
not implemented and production apply remains NO-GO.

The local/test proxy routing validation approval package exists at
[BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md](BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md).
It records that the local/test proxy path used deployment lock path
`.deploy/bluegreen-proxy-validation.lock`, Compose project
`aftersales-bluegreen-proxy-validation`, inactive service `web_green_test` on
port `18080`, test proxy service `bluegreen_proxy_test` on port `19080`, and
the unified Compose file
`docker-compose.bluegreen.proxy-validation.example.yml`. The proxy validation
returned HTTP 200 on `19080 /healthz/`, kept `8000 /healthz/` HTTP 200 before
and after validation, and cleaned up only `bluegreen_proxy_test` and
`web_green_test`. This does not approve production, does not transfer port
`8000`, and does not block normal non-deploy tasks.

A previous manual proxy validation failed because `bluegreen_proxy_test` and
`web_green_test` were launched from separate Compose projects/networks, leaving
nginx unable to resolve `web_green_test:8000`. The passed validation used the
unified proxy validation Compose example to keep both services in one Compose
project/network while leaving port `8000`, production traffic, and active proxy
configuration untouched.

## Deployment Lock Gate

`scripts/safe_deploy.ps1` now enforces the deployment lock in real mode.
`scripts/blue_green_production_apply.ps1` now documents the future production
apply lock gates as a structured skeleton, but remains no-action and blocked.
Production blue-green apply must still not proceed until a future phase
approves and validates exact runtime-changing commands behind the same lock
rule. The shared lock is documented in
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
confirmed that a local inactive test service can reach `/healthz/`, and the
manual non-production inactive runtime validation is recorded as PASSED on
2026-05-18. This does not remove the need for the deployment lock. The lock
addresses a separate risk: overlapping deployment tasks racing with each other.

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
  `scripts/blue_green_production_apply.ps1`; command path skeleton implemented
  but blocked, no-action by default, and real apply remains blocked.
- Proxy switch script: not implemented yet.
- Cleanup script: not implemented yet.
- Local inactive startup: separate local-only gate, not production traffic.
- Non-production inactive runtime validation: PASSED on 2026-05-18.
- Local/test proxy routing validation: PASSED on 2026-05-19.
- Non-production validation chain: PASSED for inactive runtime plus local/test
  proxy routing.
- Production apply: NO-GO until a future runtime-changing implementation is
  explicitly approved and uses the deployment lock before any
  build/start/migrate/collectstatic/proxy switch/cleanup/rollback action.
- Local proxy routing validation approval package: READY after review; future
  validation still requires the exact approval phrase and deployment lock.

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

Current phase after Phase 1 review.

Non-production validation is documented in
[BLUE_GREEN_NON_PRODUCTION_VALIDATION.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION.md).
The future approval package is documented in
[BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md).
It may be local-only or staging, must use a non-production Compose/project
scope and non-`8000` test ports, must not change Cloudflare/domain routing,
and must leave the current production web path untouched. Runtime validation
requires the deployment lock and a separate approval phrase. Normal non-deploy
tasks are not blocked by this deployment lock.

Status: local inactive runtime validation PASSED on 2026-05-18 for
`web_green_test` on test port `18080`. The active `web` service on port `8000`
remained healthy, the inactive service eventually returned HTTP 200 on
`18080 /healthz/`, cleanup stopped `web_green_test`, and production remained
NO-GO.

Additional local validation remains gated unless separately approved. The
current gated runner is available only for dry-run / no-action status checks:

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

Status: local/test proxy routing validation PASSED on 2026-05-19 through
`19080` to `web_green_test` on `18080`, using
[BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md](BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md)
and `docker-compose.bluegreen.proxy-validation.example.yml`. Cleanup stopped
only `bluegreen_proxy_test` and `web_green_test`; production port `8000` and
current `web` remained untouched.

Next phase: use the conservative production proxy, active-color, and rollback
details listed in
[BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md),
[BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md),
and
[BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md](BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md)
for a future exact implementation review. Production remains NO-GO. Migration
compatibility, scheduler singleton behavior, media/static/uploads, proxy
ownership, active/target color tracking, rollback, observation, cleanup, and
data safety still must be checked before any production apply.

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

Production-specific conservative defaults are documented in
[BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md).
They resolve design direction only. Production implementation remains NOT
READY, production apply remains NO-GO, and exact proxy switch/reload plus
rollback commands still require a later implementation and final approval.
The exact switch/rollback design is reviewed at
[BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md)
and remains no-action.

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

Use the production runtime details document at
[BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md),
the switch/rollback review document at
[BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md),
and the command review document at
[BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md](BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md)
to design the future implementation without touching production traffic. The
next separate task should implement and review the exact proxy config path,
active-color state update behavior, proxy switch/reload command, rollback
command, observation checks, migration gate, scheduler singleton confirmation,
and media/static confirmation. Production remains NO-GO until implementation
is added in a later task and a separate production task approves the exact
runtime path being used.

## Runtime Command Helper Status

- `scripts/blue_green_runtime_commands.ps1` now exists for plan-only runtime
  command review.
- It does not deploy, start/stop/restart/build containers, run migrations, run
  collectstatic, reload proxy, switch traffic, write active-color state, or run
  rollback.
- Proxy switch execution: NOT ENABLED.
- Active-color state write: NOT ENABLED.
- Rollback execution: NOT ENABLED.
- Production apply remains NO-GO.
- Final runtime implementation still needs a separate approval task before the
  future helper behavior can become executable.
