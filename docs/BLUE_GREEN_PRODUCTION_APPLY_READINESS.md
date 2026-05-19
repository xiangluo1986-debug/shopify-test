# Blue-Green Production Apply Readiness

## Purpose

Prepare the exact production apply readiness review for future blue-green
deployment.

This document does not approve production apply. Production apply remains
NO-GO until a later explicit approval task reviews the exact runtime path and
approves the final command set.

Production runtime defaults are documented in
[BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md).
Those defaults cover proxy candidate, port ownership, service names,
active-color state, proxy switch shape, rollback, observation, migration
policy, scheduler singleton behavior, and media/static expectations. They do
not approve production command implementation or production apply.

The exact future proxy switch, active-color state, and rollback design is
documented in
[BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md).
It is READY after review, but it does not approve production apply.

## Current Passed Prerequisites

- Local inactive runtime validation: PASSED.
- Local/test proxy routing validation: PASSED.
- Deployment lock helper: available.
- safe_deploy lock enforcement: active in real mode.
- Production preflight document: exists.
- Production command review document:
  [BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md](BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md)
  exists and is READY after review.
- Production runtime details document:
  [BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md)
  exists and records conservative defaults.
- Production switch/rollback review document:
  [BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md)
  exists and is READY after review.
- Production command path skeleton: implemented but blocked.
- Production implementation: NOT READY.
- Exact production runtime command implementation: still not enabled.

## Conservative Defaults And Required Final Reviews

Conservative defaults now documented:

- Proxy candidate: nginx.
- Current production `web` owns host port `8000`; a future proxy may take over
  `8000` only after explicit final production apply approval.
- Future production service names: `web_blue`, `web_green`, and
  `bluegreen_proxy`.
- Active color state: `.deploy/active-color.json` with `active_color`,
  `previous_color`, `updated_at`, `updated_by`, `deploy_id`,
  `proxy_config_version`, and `notes`.
- Active color state under `.deploy/` must not be committed and must not
  contain secrets.
- Active color state writes must be atomic and must occur only after target
  switch or rollback health validation passes.
- Future proxy switch updates only a controlled local proxy
  include/symlink/state file after target health passes.
- Rollback switches the proxy back to `previous_color`, uses the deployment
  lock, and does not rollback the database unless separately approved.
- First production apply observation window: at least 10 minutes.
- Migration policy: backward-compatible migrations only; destructive
  migrations need a separate deploy plan.
- Scheduler policy: singleton scheduler only; Shopify sync, Review Request,
  settlement, Gmail/Trustpilot jobs, and other scheduled jobs must not run
  twice.
- Media/uploads must be shared; static handling must be reviewed before
  production proxy switch.

Final reviews still needed before production implementation or apply:

- Exact production proxy config path.
- Exact proxy switch/reload command.
- Exact active-color state update behavior.
- Exact rollback command and rollback authority.
- Target color selection for the specific deploy.
- Cloudflare/domain routing impact, with no first-apply routing change unless
  separately approved.
- Migration compatibility approval for the specific deploy.
- Scheduler singleton confirmation for the specific deploy.
- Media/static/uploads confirmation for the specific deploy.

## Exact Command Review

The dedicated production runtime command review is documented at
[BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md](BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md).
It is READY after review, but production implementation is NOT READY and
production apply remains NO-GO.

The production runtime details document is
[BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md).
It is READY after review for conservative design direction only.

All commands in this section are for future review context only.

NOT RUN IN THIS TASK.

The structured command path now exists in
`scripts/blue_green_production_apply.ps1` as a skeleton only. It prints
planned phases for preflight, lock, target color preparation, switch, observe,
rollback, and cleanup, but every phase is reported as `NOT RUN`.

The skeleton does not deploy, start, stop, restart, or build containers; run
migrations; run collectstatic; switch traffic; change Cloudflare/domain
routing; modify active Compose files; or modify production proxy
configuration.

### Git Status And Current Commit

NOT RUN IN THIS TASK:

```powershell
git status --short --branch
git rev-parse --short HEAD
```

### Deployment Lock Status / Acquire

NOT RUN IN THIS TASK:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action status
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action acquire -Purpose "blue-green-production-apply" -Target "production"
```

### Current 8000 Health

NOT RUN IN THIS TASK:

```powershell
powershell -NoProfile -Command 'Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/healthz/ | Select-Object StatusCode,Content'
```

### Migration Compatibility Check

NOT RUN IN THIS TASK:

```powershell
git diff --name-only <previous-reviewed-commit> <target-commit> -- backend/**/migrations/*.py
docker compose exec -T web python manage.py showmigrations
```

Migration compatibility also requires human review. Destructive, renaming, or
old-code-incompatible migrations must block production apply.

### Scheduler Singleton Check

NOT RUN IN THIS TASK:

```powershell
docker compose ps scheduler
```

The exact production scheduler singleton confirmation is still pending manual
review.

### Media / Static Path Check

NOT RUN IN THIS TASK:

```powershell
docker compose exec -T web python manage.py check
```

The exact media/static/uploads verification command depends on the production
storage decision and is not finalized here.

### Target Color Startup

NOT RUN IN THIS TASK.

Production target color startup command: not yet implemented.

No final production command is approved in this package.

### Target Color `/healthz/`

NOT RUN IN THIS TASK:

```powershell
powershell -NoProfile -Command 'Invoke-WebRequest -UseBasicParsing http://127.0.0.1:<target-color-health-port>/healthz/ | Select-Object StatusCode,Content'
```

The target color port must be selected and reviewed before this command can be
used.

### Proxy Config Validation

NOT RUN IN THIS TASK:

```powershell
<proxy-binary> -t -c <production-proxy-config-path>
```

The exact command depends on the selected production proxy technology and
config path.

### Proxy Switch

NOT RUN IN THIS TASK.

Production proxy switch command: not yet implemented.

The command must not be created or run until proxy technology, config path,
active color tracking, target color, rollback command, Cloudflare/domain
impact, and deployment lock handling are approved.

### Post-Switch Health Check

NOT RUN IN THIS TASK:

```powershell
powershell -NoProfile -Command 'Invoke-WebRequest -UseBasicParsing <production-health-url>/healthz/ | Select-Object StatusCode,Content'
```

The production health URL must be confirmed without exposing private routing or
secret values.

### Observation

NOT RUN IN THIS TASK:

```powershell
Start-Sleep -Seconds <approved-observation-seconds>
```

The observation window, checks, and accountable operator are still pending
manual approval.

### Rollback

NOT RUN IN THIS TASK.

Rollback command: not yet implemented.

Rollback must switch back to the previous color and must not attempt database
rollback unless a separate database rollback task is approved.

### Cleanup

NOT RUN IN THIS TASK.

Cleanup command: not yet implemented.

Cleanup must keep the old color available during the observation window and
must not remove database, media, static, upload, or secret-bearing state.

### Deployment Lock Release

NOT RUN IN THIS TASK:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action release -LockId <lock_id>
```

Release must use only the matching `lock_id` acquired by the same production
apply flow.

## Production Safety Gates

Production apply cannot proceed unless all gates below pass:

- Deployment lock acquired.
- No existing deployment lock.
- Current `8000` healthy.
- Target color not equal active color.
- Active-color state path remains under `.deploy/`, is not committed, and
  contains no secrets.
- Migration compatibility approved.
- Scheduler singleton confirmed.
- Media/static shared storage confirmed.
- Rollback plan reviewed.
- `TargetColor` and `ActiveColor` supplied and different.
- `DeployLockPath` constrained under `.deploy/`.
- Old color retained during observation.
- Cloudflare/domain impact known.
- Exact command approved.
- Production approval phrase supplied.

## Approval Phrase Draft

Future draft phrase:

```text
I_APPROVE_PRODUCTION_BLUE_GREEN_APPLY_AFTER_PREFLIGHT_REVIEW
```

This phrase is accepted by the current skeleton only to prove that runtime
execution remains blocked. It is NOT ACTIVE for real production apply in this
phase. Future implementation must still require deployment lock, exact command
review, migration compatibility confirmation, scheduler singleton
confirmation, shared media/static storage confirmation, rollback command
confirmation, and a separate explicit production approval.

## Go / No-Go

- Readiness package: READY after review.
- Production runtime details document: READY after review at
  [BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md).
- Production switch/rollback review document: READY after review at
  [BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md).
- Production command review document: READY after review at
  [BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md](BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md).
- Production command path skeleton: implemented but blocked.
- Production implementation: NOT READY.
- Exact production runtime command implementation: still not enabled.
- Production apply: NO-GO.

This readiness package does not deploy, start, stop, restart, or build
containers; run migrations; run collectstatic; switch traffic; change
Cloudflare/domain routing; modify active Compose files; modify production
proxy configuration; call Shopify APIs; call Gmail APIs; send email; or affect
ticket, review request, translation, settlement, Trustpilot, Kudosi, or Ali
Reviews workflows.
