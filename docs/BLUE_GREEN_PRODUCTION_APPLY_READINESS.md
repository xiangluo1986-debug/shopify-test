# Blue-Green Production Apply Readiness

## Purpose

Prepare the exact production apply readiness review for future blue-green
deployment.

This document does not approve production apply. Production apply remains
NO-GO until a later explicit approval task reviews the exact runtime path and
approves the final command set.

## Current Passed Prerequisites

- Local inactive runtime validation: PASSED.
- Local/test proxy routing validation: PASSED.
- Deployment lock helper: available.
- safe_deploy lock enforcement: active in real mode.
- Production preflight document: exists.
- Production command path skeleton: implemented but blocked.
- Exact production runtime command implementation: not approved yet.

## Required Manual Production Decisions Still Needed

- Production proxy technology and config path.
- Whether production proxy takes over port `8000`.
- Cloudflare/domain routing impact.
- Active color tracking method.
- Target color selection.
- Rollback command.
- Observation window.
- Who has rollback authority.
- Migration compatibility approval.
- Scheduler singleton confirmation.
- Media/static/uploads confirmation.

## Exact Command Review

All commands in this section are for a future review task only.

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
- Production command path skeleton: implemented but blocked.
- Exact production runtime command implementation: not approved yet.
- Production apply: NO-GO.

This readiness package does not deploy, start, stop, restart, or build
containers; run migrations; run collectstatic; switch traffic; change
Cloudflare/domain routing; modify active Compose files; modify production
proxy configuration; call Shopify APIs; call Gmail APIs; send email; or affect
ticket, review request, translation, settlement, Trustpilot, Kudosi, or Ali
Reviews workflows.
