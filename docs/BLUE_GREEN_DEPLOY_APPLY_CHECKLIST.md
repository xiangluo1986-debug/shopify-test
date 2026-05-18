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
- [BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md](BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md)
- [scripts/deploy_lock_dry_run.ps1](../scripts/deploy_lock_dry_run.ps1)
- [scripts/blue_green_local_apply_simulation.ps1](../scripts/blue_green_local_apply_simulation.ps1)
- [scripts/blue_green_local_inactive_startup.ps1](../scripts/blue_green_local_inactive_startup.ps1)

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
  startup runner intentionally uses `--no-build`.
- Local runtime apply: NO-GO until a separate task approves exact commands.
- Deployment lock: design/dry-run only. Active deploy scripts do not enforce
  the lock yet.
- Production apply: NO-GO until deployment lock enforcement is implemented.
- Runtime behavior changed by this checklist: no.
- Active Compose/proxy changes: require separate approval.
- Host port `8000` ownership change: requires separate approval.

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
- The local-test inactive Compose example
  [docker-compose.bluegreen.local-test.example.yml](../docker-compose.bluegreen.local-test.example.yml)
  has been reviewed and confirmed not to bind host port `8000`, not to declare
  a build for `web_green_test`, and to reuse image `aftersales-web`.
- The existing `aftersales-web` image is present locally, or a separate
  explicit image build/preparation task has been completed first.
- The deployment lock design in [DEPLOYMENT_LOCK.md](DEPLOYMENT_LOCK.md) has
  been reviewed.
- The deployment lock is implemented and enforced before any production deploy,
  build, restart, proxy switch, rolling update, or cleanup action.
- Any future production switch acquires the deployment lock first and releases
  it only after switch validation and cleanup/finally handling.
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
- A reviewed proxy design is selected and tested away from production traffic.
- The active color source of truth is documented and recoverable.
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
- Switching traffic between colors.
- Stopping the previous active color.
- Proceeding with production apply before deployment lock enforcement is active.

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

- Run the read-only deployment lock dry-run helper:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock_dry_run.ps1 -Purpose "blue-green-production-preflight" -Target "production" -ShowPlan
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

- Confirm the local-test inactive Compose example validates without starting
  containers:

```powershell
docker compose -f docker-compose.bluegreen.local-test.example.yml config
```

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
