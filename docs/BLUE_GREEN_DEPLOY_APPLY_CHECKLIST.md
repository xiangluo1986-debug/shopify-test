# Blue-Green Deploy Apply Checklist

This checklist is for a future reviewed apply task only. Do not use it to
switch production traffic, restart production, run migrations, or change
Cloudflare routing until that task is explicitly approved.

Related non-active drafts:

- [docker-compose.bluegreen.example.yml](../docker-compose.bluegreen.example.yml)
- [docker-compose.bluegreen.local-test.example.yml](../docker-compose.bluegreen.local-test.example.yml)
- [nginx/bluegreen.example.conf](../nginx/bluegreen.example.conf)
- [BLUE_GREEN_DEPLOY_PLAN.md](BLUE_GREEN_DEPLOY_PLAN.md)
- [BLUE_GREEN_DEPLOY_DECISIONS.md](BLUE_GREEN_DEPLOY_DECISIONS.md)
- [BLUE_GREEN_DEPLOY_LOCAL_DRY_RUN_REVIEW.md](BLUE_GREEN_DEPLOY_LOCAL_DRY_RUN_REVIEW.md)
- [BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md](BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md)
- [DEPLOYMENT_LOCK.md](DEPLOYMENT_LOCK.md)
- [scripts/deploy_lock.ps1](../scripts/deploy_lock.ps1)
- [BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md](BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md)
- [scripts/deploy_lock_dry_run.ps1](../scripts/deploy_lock_dry_run.ps1)
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
- [docker-compose.bluegreen.proxy-validation.example.yml](../docker-compose.bluegreen.proxy-validation.example.yml)
- [docker-compose.bluegreen.proxy-test.example.yml](../docker-compose.bluegreen.proxy-test.example.yml)
- [nginx/bluegreen.local-test.example.conf](../nginx/bluegreen.local-test.example.conf)
- [scripts/blue_green_production_apply.ps1](../scripts/blue_green_production_apply.ps1)

## Current Status

- Local-only planning: READY after conservative defaults were filled in
  [BLUE_GREEN_DEPLOY_DECISIONS.md](BLUE_GREEN_DEPLOY_DECISIONS.md).
- Local-only dry-run review: READY after
  [BLUE_GREEN_DEPLOY_LOCAL_DRY_RUN_REVIEW.md](BLUE_GREEN_DEPLOY_LOCAL_DRY_RUN_REVIEW.md)
  is reviewed.
- Local apply simulation approval package: READY after
  [BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md](BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md)
  is reviewed.
- Gated local simulation runner: READY for dry-run / no-action status checks
  only at `scripts/blue_green_local_apply_simulation.ps1`.
- Local inactive startup plan: READY for review in
  [BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md](BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md).
- Gated local inactive startup runner: READY for dry-run / no-action status
  checks by default at `scripts/blue_green_local_inactive_startup.ps1`; future
  local-only execution is gated by the exact Ack and `-AllowContainerAction`.
- Non-production validation plan: READY after review at
  [BLUE_GREEN_NON_PRODUCTION_VALIDATION.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION.md).
  Non-production inactive runtime validation PASSED on 2026-05-18 using
  `web_green_test` on test port `18080` with image `aftersales-web:latest`.
  Local/test proxy routing validation PASSED on 2026-05-19 using
  `bluegreen_proxy_test` on test port `19080` and the unified proxy validation
  Compose file. The non-production validation chain is PASSED for inactive
  runtime plus local/test proxy routing. Future additional runtime validation
  still requires separate approval, deployment lock acquisition/release,
  non-`8000` test ports, and no production traffic switch.
- Non-production runtime validation approval package: READY after review at
  [BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md).
  It records the completed/passed manual inactive runtime validation, does not
  approve production apply, and requires separate approval for additional
  validation.
- Next required blue-green step: review
  [BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md)
  and
  [BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md](BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md)
  for future exact implementation design.
- Production runtime details document: READY after review at
  [BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md).
  It documents conservative defaults for nginx as proxy candidate, current
  `web` ownership of host port `8000` until final approval, service names
  `web_blue`, `web_green`, and `bluegreen_proxy`, active-color state under
  `.deploy/active-color.json`, controlled proxy switch shape, rollback to
  `previous_color`, at least 10 minutes of observation, backward-compatible
  migration policy, singleton scheduler, and shared media/uploads.
  Production implementation is still NOT READY and production apply remains
  NO-GO.
- Production switch/rollback review document: READY after review at
  [BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md).
  It documents the exact future proxy switch flow, active-color state design,
  rollback flow, cleanup boundaries, and remaining blockers. Proxy switch
  command: NOT IMPLEMENTED. Rollback command: NOT IMPLEMENTED. Production
  apply remains NO-GO.
- Local/test proxy routing validation result: PASSED on 2026-05-19 and
  recorded at
  [BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md](BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md).
  The validation used deployment lock path
  `.deploy/bluegreen-proxy-validation.lock`, Compose project
  `aftersales-bluegreen-proxy-validation`, inactive service `web_green_test`
  on port `18080`, test proxy service `bluegreen_proxy_test` on port `19080`,
  and `docker-compose.bluegreen.proxy-validation.example.yml`. Port `8000`,
  current `web`, production traffic, and production proxy configuration
  remained untouched. Normal non-deploy tasks are not blocked by this
  deployment lock.
- Local simulation execution: NO-GO. A future phase still requires
  `I_APPROVE_LOCAL_ONLY_BLUE_GREEN_SIMULATION_NO_PRODUCTION_TRAFFIC` and
  approval of exact commands. Real local simulation execution is not
  implemented in the current runner phase.
- Local inactive startup: NO-GO until a separate task approves one inactive
  service, a non-`8000` test port, `-AllowContainerAction`, and cleanup
  commands. The current startup runner blocks `-TestPort 8000`, blocks
  `-InactiveService web`, blocks active `docker-compose.yml`, and blocks correct
  Ack without `-AllowContainerAction`. Required phrase:
  `I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC`.
  The local inactive service reuses the existing `aftersales-web` image; the
  startup runner intentionally uses `--no-build`. Hold-open mode is available
  behind the same gates for local/test proxy validation only; after proxy
  validation, cleanup is mandatory and must stop only `bluegreen_proxy_test`
  and `web_green_test`.
- Local runtime apply: NO-GO until a separate task approves exact commands.
- Deployment lock helper: available at `scripts/deploy_lock.ps1`.
- safe_deploy lock awareness: READY for dry-run/check-only status reporting at
  `scripts/safe_deploy.ps1 -DryRun` and
  `scripts/safe_deploy.ps1 -CheckDeployLock`.
- safe_deploy lock enforcement: READY for real non-dry-run safe deploy mode;
  it acquires the lock before build/check/migrate/collectstatic/restart/health
  check and releases only the matching `lock_id` in cleanup/finally handling.
- Deployment lock enforcement for blue-green runtime paths: NO-GO until a
  separate apply task approves exact commands and confirms every
  runtime-changing path uses the shared lock.
- Production command path skeleton: implemented but blocked at
  `scripts/blue_green_production_apply.ps1`. It prints planned phases for
  preflight, lock, target color preparation, switch, observe, rollback, and
  cleanup. It does not deploy, acquire the production lock, run Docker
  commands, run migrations, run collectstatic, switch traffic, or modify files.
  Draft readiness phrase for blocked skeleton validation only:
  `I_APPROVE_PRODUCTION_BLUE_GREEN_APPLY_AFTER_PREFLIGHT_REVIEW`. This phrase
  is NOT ACTIVE for real production apply.
- Production preflight document: READY after review at
  [BLUE_GREEN_PRODUCTION_PREFLIGHT.md](BLUE_GREEN_PRODUCTION_PREFLIGHT.md).
  It does not approve production apply. It records required checks for
  deployment lock behavior, migration compatibility, scheduler singleton
  behavior, media/static/uploads, proxy and port ownership, active/target color
  tracking, health checks, rollback, observation, cleanup, and data loss
  prevention.
- Production apply readiness package: READY after review at
  [BLUE_GREEN_PRODUCTION_APPLY_READINESS.md](BLUE_GREEN_PRODUCTION_APPLY_READINESS.md).
  It records future command groups, production safety gates, required manual
  decisions, and the draft approval phrase. The production command path
  skeleton is implemented but blocked; production implementation is NOT READY
  and exact runtime command implementation is still not enabled.
- Production command review document: READY after review at
  [BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md](BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md).
  It records the future production command groups. Production implementation is
  NOT READY, exact runtime command implementation is still not enabled, and
  unresolved proxy, active-color, rollback, observation, migration, scheduler,
  and media/static blockers remain.
- Production apply: NO-GO until the production preflight document is reviewed
  and a separate production task approves exact runtime commands, route, port
  ownership, proxy, scheduler, migration, static/media, rollback, observation,
  cleanup, data safety, and lock handling.
- Runtime behavior changed by this checklist: no.
- Active Compose/proxy changes: require separate approval.
- Host port `8000` ownership change: requires separate approval.
- Active color state under `.deploy/` must not be committed and must not
  contain secrets.

## Deployment Lock Coverage Status

- `safe_deploy.ps1`: enforced in real mode.
- Blue-green production apply skeleton:
  `scripts/blue_green_production_apply.ps1`; command path skeleton implemented
  but blocked, no-action by default, and real production apply remains blocked
  even with the draft readiness phrase and valid parameters.
- Proxy switch script: not implemented yet.
- Cleanup script: not implemented yet.
- Local inactive startup: separate local-only gate, not production traffic.
- Production apply: NO-GO until a future runtime-changing implementation uses
  deployment lock acquisition before any build/start/migrate/collectstatic,
  proxy switch, traffic switch, cleanup, or rollback action.
- Non-production inactive runtime validation: PASSED on 2026-05-18 for
  `web_green_test` on `18080`.
- Local/test proxy routing validation: PASSED on 2026-05-19 for
  `bluegreen_proxy_test` on `19080` routing to `web_green_test` on `18080`.
- Deployment lock remains required for future runtime-changing production apply
  and any future local/test runtime rerun.

Runtime-changing actions that require the deployment lock before any future
apply include container start, container stop, container restart, image build,
migration, collectstatic, proxy switch, traffic switch, cleanup of blue/green
services, production apply, and rollback. If a lock exists, the task must block
and exit non-zero, not auto-queue. The task must release only the matching
`lock_id` in cleanup/finally handling. Stale lock removal requires manual
review. Normal non-deploy tasks are not blocked.

## Preconditions Before Applying

- Current single-web deployment is healthy through `/healthz/`.
- Active `docker-compose.yml` behavior is understood and still unchanged.
- Local-only planning defaults in
  [BLUE_GREEN_DEPLOY_DECISIONS.md](BLUE_GREEN_DEPLOY_DECISIONS.md) are filled.
- The local dry-run review package in
  [BLUE_GREEN_DEPLOY_LOCAL_DRY_RUN_REVIEW.md](BLUE_GREEN_DEPLOY_LOCAL_DRY_RUN_REVIEW.md)
  has been reviewed and accepted before any local apply simulation.
- The local apply simulation approval package in
  [BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md](BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md)
  has been reviewed and accepted before any local apply simulation.
- The local inactive startup plan in
  [BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md](BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md)
  has been reviewed before any inactive-color startup.
- The non-production validation plan in
  [BLUE_GREEN_NON_PRODUCTION_VALIDATION.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION.md)
  has been reviewed before any future non-production runtime validation.
- The non-production runtime validation approval package in
  [BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md)
  has been reviewed, and the exact approval phrase is supplied in a separate
  task before any future validation run.
- The local-test inactive Compose example
  [docker-compose.bluegreen.local-test.example.yml](../docker-compose.bluegreen.local-test.example.yml)
  has been reviewed and confirmed not to bind host port `8000`, not to declare
  a build for `web_green_test`, and to reuse image `aftersales-web`.
- The existing `aftersales-web` image is present locally, or a separate
  explicit image build/preparation task has been completed first.
- The deployment lock design in [DEPLOYMENT_LOCK.md](DEPLOYMENT_LOCK.md) has
  been reviewed.
- The deployment lock helper is integrated and enforced in real safe_deploy
  mode before build/check/migrate/collectstatic/restart/health check.
- Any future blue-green production deploy, proxy switch, rolling update, or
  cleanup action also integrates and enforces the same lock before changing
  runtime state.
- Any future production switch acquires the deployment lock first and releases
  it only after switch validation and cleanup/finally handling.
- The production apply skeleton has been reviewed in default no-action mode.
- The production preflight document in
  [BLUE_GREEN_PRODUCTION_PREFLIGHT.md](BLUE_GREEN_PRODUCTION_PREFLIGHT.md) has
  been reviewed.
- The production apply readiness package in
  [BLUE_GREEN_PRODUCTION_APPLY_READINESS.md](BLUE_GREEN_PRODUCTION_APPLY_READINESS.md)
  has been reviewed. It does not implement a production command and does not
  approve production apply.
- The production command review document in
  [BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md](BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md)
  has been reviewed. It does not implement or approve production runtime
  commands.
- The production runtime details document in
  [BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md)
  has been reviewed. It documents conservative defaults only and does not
  implement or approve production runtime commands.
- The production switch/rollback review document in
  [BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md)
  has been reviewed. It documents future switch and rollback design only and
  does not implement proxy reload, traffic switch, active-color state write, or
  rollback commands.
- Successful non-production inactive runtime validation has been reviewed, and
  local/test proxy routing validation has passed, before any future production
  apply request.
- The local/test proxy routing validation result in
  [BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md](BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md)
  has been reviewed. The completed run used `19080` for the test proxy while
  leaving `8000` untouched, used
  `docker-compose.bluegreen.proxy-validation.example.yml` so
  `bluegreen_proxy_test` and `web_green_test` shared one Docker network, and
  stopped only `bluegreen_proxy_test` and `web_green_test` during cleanup.
- The production apply skeleton still blocks a correct approval phrase with:
  `Real production blue-green apply command path is implemented as a skeleton only and remains blocked in this phase.`
- Any future execution request must supply `TargetColor` and `ActiveColor`, they
  must be different, `DeployLockPath` must stay under `.deploy/`, and missing
  migration, scheduler, media/static, or rollback confirmations must block.
  These gates still do not permit runtime action in this phase.
- Deployment tasks do not auto-queue behind an existing lock. A second deploy
  task stops and requires a manual rerun after the current deploy completes.
- Normal non-deploy tasks are not blocked by this deployment lock.
- The completed local inactive startup success on non-production port `18080`
  is understood as a local runtime test only; it does not waive deployment lock
  enforcement for future production apply.
- The future local simulation approval phrase is present:
  `I_APPROVE_LOCAL_ONLY_BLUE_GREEN_SIMULATION_NO_PRODUCTION_TRAFFIC`.
- The future inactive service is confirmed to bind only a non-`8000` local test
  port such as `18080` or `18081`.
- The future inactive service name is confirmed not to be `web`.
- The future inactive startup approval phrase is present only in a separately
  approved task:
  `I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC`.
- The future inactive startup command includes `-AllowContainerAction`; correct
  approval phrase alone is not enough.
- A separate apply task approves the exact local runtime commands before any
  container start, restart, proxy reload, or traffic switch is run.
- Future non-production runtime validation uses a non-production Compose
  project/scope, test-only ports such as `18080`, `18081`, or `19080`, and no
  Cloudflare/domain routing change.
- Future non-production runtime validation uses the deployment lock, while
  normal non-deploy tasks remain unblocked.
- A reviewed proxy design is selected and tested away from production traffic.
- The active color source of truth is documented and recoverable.
- The active color state path stays under `.deploy/`, is not committed, and
  contains no secrets.
- Database backup and restore process is confirmed for the production database.
- Any migrations are reviewed for backward compatibility before they run.
- Static and media file handling is confirmed for two web containers.
- Scheduler behavior is reviewed so only one scheduler instance runs.
- Cloudflare or external routing changes are reviewed without exposing tokens.
- Rollback authority and communication path are assigned before the switch.

## Required Manual Decisions

The local-only planning defaults in
[BLUE_GREEN_DEPLOY_DECISIONS.md](BLUE_GREEN_DEPLOY_DECISIONS.md) are filled.
They approve planning only, not runtime changes. Active apply work remains
NO-GO until a separate task approves exact commands, operator responsibility,
and rollback steps.

- Proxy technology: nginx is the local-only planning default, example-only
  until apply phase.
- Production proxy / active-color / rollback defaults are documented in
  [BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md);
  exact implementation and final production approval are still required.
- The exact future switch/rollback design is documented in
  [BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md);
  active-color state writes remain future-only and must be atomic.
- Active color tracking: future file-based marker, documented as draft/example
  only until an apply task creates real runtime state.
- Port ownership: current `web` service keeps host port `8000`; changing this
  requires separate approval.
- Cloudflare/external routing impact: tunnel target, DNS/proxy behavior, and
  any planned maintenance window are not approved for local-only planning.
- Migration compatibility rules: backward-compatible only during blue-green
  switch; risky schema changes require separate migration planning.
- Static/media handling: shared media remains unchanged; `collectstatic`
  behavior remains current safe-deploy behavior until apply design is finalized.
- Scheduler handling: singleton scheduler only; no blue/green scheduler
  replicas.
- Rollback authority: manual admin approval required; keep old color running;
  observe at least 10 minutes for local/test.
- First apply scope: local-only apply dry-run first; production remains NO-GO.

## Future Apply Flow

1. Acquire the deployment lock before changing runtime state.
2. Confirm the current active color and record it in the approved tracking
   location.
3. Build or start only the inactive color.
4. Run `python manage.py check` against the inactive color.
5. Run migrations only when they are reviewed as safe for both old and new code.
6. Run any approved static asset step without disrupting the active color.
7. Check the inactive color directly through `/healthz/`.
8. Run any agreed smoke tests against the inactive color.
9. Switch the proxy from the old active color to the inactive healthy color.
10. Check public `/healthz/` through the stable domain or routing path.
11. Monitor web and proxy logs during the observation window.
12. Keep the previous color running until rollback is no longer needed.
13. Stop or recycle the previous color only after the observation window passes.
14. Release the deployment lock in cleanup/finally handling.

## Do Not Run Yet

These actions are not approved by this checklist alone:

- Starting blue/green services in production.
- Starting, restarting, or replacing local runtime services without a separate
  approved apply task.
- Moving host port `8000` from `web` to a proxy.
- Changing Cloudflare tunnel targets or public routing.
- Running migrations.
- Reloading or replacing production proxy configuration.
- Reloading or replacing any active local proxy configuration without a
  separate approved apply task.
- Running local/test proxy validation unless hold-open inactive startup and
  cleanup of only `bluegreen_proxy_test` and `web_green_test` are explicitly
  included.
- Switching traffic between colors.
- Stopping the previous active color.
- Proceeding with production apply before deployment lock enforcement is active
  for the exact runtime path being used.
- Proceeding with production apply before successful local/test proxy routing
  validation and separate manual production approval.
- Proceeding with production apply before the production preflight document is
  reviewed and a separate exact command review is approved.

## Rollback Steps

1. If inactive color validation fails before the switch, do not switch traffic.
2. If errors appear after the switch, change the proxy back to the previous
   active color.
3. Confirm public `/healthz/` through the stable routing path.
4. Keep the failed color available for log inspection when it is safe to do so.
5. Do not attempt automatic database rollback.
6. If migrations were involved, follow the reviewed database backup/restore plan.
7. Record the final active color and the reason for rollback.

## Validate Without Changing Traffic

- Run the read-only planner:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_deploy_dry_run.ps1
```

- Run the production apply skeleton in default no-action mode:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_production_apply.ps1
```

- Review the production preflight document:
  [BLUE_GREEN_PRODUCTION_PREFLIGHT.md](BLUE_GREEN_PRODUCTION_PREFLIGHT.md).

- Review the production command review document:
  [BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md](BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md).

- Review the production switch/rollback review document:
  [BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md).

- Confirm execution requests without the exact approval phrase remain blocked:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_production_apply.ps1 -ExecuteProductionApply -TargetColor green -ActiveColor blue
```

- Confirm the correct approval phrase still does not perform real production
  apply in this skeleton phase:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_production_apply.ps1 -ExecuteProductionApply -Ack I_APPROVE_PRODUCTION_BLUE_GREEN_APPLY_AFTER_PREFLIGHT_REVIEW -TargetColor green -ActiveColor blue
```

- Confirm invalid target/active color choices remain blocked:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_production_apply.ps1 -ExecuteProductionApply -Ack I_APPROVE_PRODUCTION_BLUE_GREEN_APPLY_AFTER_PREFLIGHT_REVIEW -TargetColor blue -ActiveColor blue
```

- Run the read-only deployment lock dry-run helper:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock_dry_run.ps1 -Purpose "blue-green-production-preflight" -Target "production" -ShowPlan
```

- Run safe_deploy lock awareness dry-run without deploying:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\safe_deploy.ps1 -DryRun
```

- Run safe_deploy lock check without deploying:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\safe_deploy.ps1 -CheckDeployLock
```

- Validate safe_deploy acquire/release without deploying:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\safe_deploy.ps1 -ValidateDeployLockOnly -DeployLockPath .\.deploy\test-safe-deploy.lock
```

- Check deployment lock helper status without changing runtime state:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action status
```

- Review the local-only dry-run package:
  [BLUE_GREEN_DEPLOY_LOCAL_DRY_RUN_REVIEW.md](BLUE_GREEN_DEPLOY_LOCAL_DRY_RUN_REVIEW.md).
- Review the local apply simulation approval package:
  [BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md](BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md).
- Review the local inactive startup plan:
  [BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md](BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md).
- Run the read-only local simulation preview:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_apply_simulation_preview.ps1
```

- Run the gated local simulation runner in default dry-run / no-action mode:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_apply_simulation.ps1
```

- Run the gated local inactive startup runner in default dry-run / no-action
  mode:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_inactive_startup.ps1
```

- Confirm hold-open execution requests still require the same gates and do not
  use port `8000`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_inactive_startup.ps1 -ExecuteInactiveStartup -HoldOpenForProxyValidation
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_inactive_startup.ps1 -ExecuteInactiveStartup -HoldOpenForProxyValidation -Ack I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC
```

- Confirm the local-test inactive Compose example validates without starting
  containers:

```powershell
docker compose -f docker-compose.bluegreen.local-test.example.yml config
```

- Confirm the unified local-test proxy validation Compose example validates
  without starting containers:

```powershell
docker compose -f docker-compose.bluegreen.proxy-validation.example.yml config
```

- Confirm the proxy-only Compose example is treated as a low-level/deprecated
  standalone example and is not used for full validation without the inactive
  service on the same Docker network:

```powershell
docker compose -f docker-compose.bluegreen.proxy-test.example.yml config
```

- Confirm the local-test proxy nginx example exists and is readable:

```powershell
Test-Path .\nginx\bluegreen.local-test.example.conf
```

- Confirm the unified proxy validation config publishes only `18080` and
  `19080`, and never host port `8000`.

- Confirm the local-test inactive Compose example uses the existing image
  `aftersales-web` and does not require a build. If the image is missing, run a
  separate reviewed image preparation task first; do not add build behavior to
  the inactive startup script.

- Confirm inactive startup execution requests remain blocked unless the exact
  approval gate is supplied:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_inactive_startup.ps1 -ExecuteInactiveStartup
```

- Confirm the startup runner blocks correct Ack when `-AllowContainerAction` is
  missing:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_inactive_startup.ps1 -ExecuteInactiveStartup -Ack I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC
```

- Confirm the startup runner blocks forbidden target choices:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_inactive_startup.ps1 -ExecuteInactiveStartup -Ack I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC -TestPort 8000
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_inactive_startup.ps1 -ExecuteInactiveStartup -Ack I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC -InactiveService web
```

- Confirm execution requests are still blocked unless the exact approval gate
  is supplied, and that even correct approval remains a future placeholder in
  this phase:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_local_apply_simulation.ps1 -ExecuteLocalSimulation
```

- Validate draft Compose syntax without starting containers:

```powershell
docker compose -f docker-compose.bluegreen.example.yml config
```

- Review the example proxy config manually. It is not active and should not be
  copied into production without a separate apply task.
- Confirm the active Compose file still has one `web` service and no active
  proxy service.

## Existing Commands

Current commands remain unchanged until a future apply task is approved:

```powershell
docker compose up -d web
.\scripts\safe_deploy.ps1
```

The draft files do not change runtime behavior by existing commands because
they are separate examples and are not referenced by `docker-compose.yml`.

## Runtime Command Helper Checklist

- Confirm `scripts/blue_green_runtime_commands.ps1 -Action status` reports
  plan-only / no-action behavior.
- Confirm `scripts/blue_green_runtime_commands.ps1 -Action validate-state`
  validates `blue` / `green` values and blocks matching active/target colors.
- Confirm `scripts/blue_green_runtime_commands.ps1 -Action plan-switch`
  prints future switch steps with every step marked NOT RUN.
- Confirm `scripts/blue_green_runtime_commands.ps1 -Action plan-rollback`
  prints future rollback steps with every step marked NOT RUN.
- Confirm `scripts/blue_green_runtime_commands.ps1 -Action plan-cleanup`
  prints cleanup rules and performs no cleanup.
- Proxy switch/reload execution remains NOT ENABLED.
- Active-color state write remains NOT ENABLED.
- Rollback execution remains NOT ENABLED.
- Production apply remains NO-GO.
- Separate final runtime implementation approval is still required before any
  executable proxy switch, state write, rollback, or cleanup command is added.
