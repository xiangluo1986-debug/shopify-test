# Blue-Green Production Preflight Readiness Review

## Purpose

Review production readiness before any production blue-green apply.

This document does not approve production apply. Production remains NO-GO until
all preflight items are reviewed and a separate production approval task is
created for the exact runtime path and command set.

## Current Passed Validations

- Local inactive runtime validation: PASSED.
- Local/test proxy routing validation: PASSED.
- Deployment lock helper: available.
- safe_deploy real mode: lock enforced.
- Production apply skeleton: no-action only.

## Required Production Decisions / Checks

### A. Deployment Lock

- `scripts/safe_deploy.ps1` enforces the deployment lock in real non-dry-run
  mode.
- Production blue-green apply must also acquire the deployment lock before any
  runtime-changing action.
- A second deploy task must block and exit. It must not auto-queue behind the
  first deployment task.
- Stale lock handling requires manual review only. No automatic stale lock
  deletion is approved.
- The runtime-changing apply path must release only the matching `lock_id` in
  cleanup/finally handling.

### B. Migration Compatibility

- Blue-green requires backward-compatible migrations so old and new web code
  can run safely during the switch window.
- Destructive schema changes must not run in the same deploy as a blue-green
  web switch.
- Column removal or column rename must not happen in the same deploy as the
  blue-green switch.
- Risky migrations require a separate migration plan, backup review, and
  rollback review before production apply.
- Rollback should not attempt database rollback unless separately approved.

### C. Scheduler Singleton

- The scheduler must not be duplicated during blue-green web deployment.
- Blue-green applies to web traffic only.
- No second scheduler container should be started as part of a blue-green
  traffic switch.
- Review Request, Shopify sync, settlement, and other scheduled jobs must not
  run twice.
- Scheduler behavior must be explicitly checked before any production apply.

### D. Media / Static / Uploads

- Media and uploads must be shared and visible to both colors.
- Static handling and any `collectstatic` step must be reviewed before
  production apply.
- Container-local upload-only storage is not acceptable because uploads could
  disappear or diverge across colors.
- Production apply must confirm the web switch does not change media or upload
  volume ownership unexpectedly.

### E. Proxy And Port Ownership

- The current `web` service owns host port `8000` today.
- The production proxy takeover strategy must be explicitly approved before
  any runtime change.
- Cloudflare, domain, tunnel, or external routing impact must be known before
  any production apply.
- No port `8000` takeover is approved without a separate production apply
  approval.
- Active production nginx/proxy configuration must not be changed by this
  preflight review.

### F. Active / Target Color Tracking

- Production apply must define how the active color is tracked before any
  switch.
- Target color must be validated and must not equal the active color.
- The previous active color must be known before switch.
- Rollback target must be known and recorded before switch.
- Active/target state must be recoverable by another operator.

### G. Health Checks

- `/healthz/` must pass on the target color before switch.
- `/healthz/` must pass through the post-switch production routing path after
  switch.
- The old color should remain available during the observation window.
- Health checks prove only the health endpoint. Any required admin or workflow
  smoke checks must be listed in the separate production apply task.

### H. Rollback

- Rollback means switching the proxy back to the previous color.
- The old color must not be stopped immediately after the initial switch.
- Rollback authority and the exact rollback command must be known before
  production apply.
- Rollback must not attempt database rollback unless separately approved.
- Rollback remains a runtime-changing action and must follow deployment lock
  rules.

### I. Observation Window

- A minimum observation period must be defined before cleanup.
- During observation, inspect web logs, proxy logs, health checks, and any
  agreed operator smoke checks.
- The observation window should start after the post-switch health check
  passes.
- Cleanup must wait until the observation window has completed and rollback is
  no longer immediately needed.

### J. Cleanup

- Cleanup may run only after the observation window.
- Cleanup must not remove database volumes or media volumes.
- Cleanup must not stop the scheduler unexpectedly.
- Cleanup must not stop the previous color until rollback no longer requires
  it.
- Cleanup is runtime-changing and must be covered by the deployment lock in the
  approved production apply task.

### K. Data Loss Prevention

- A web traffic switch should not switch the database.
- Current and target web colors must intentionally share the same production
  database.
- Migration policy and scheduler singleton behavior are the main data safety
  risks.
- Blue-green switching web traffic does not itself delete data.
- Database backup, migration review, and scheduler singleton confirmation must
  be complete before any production apply approval.

## Go / No-Go

- Production preflight document: READY after review.
- Production apply: NO-GO.
- Next step: production apply readiness checklist package / exact command
  review.

This preflight document is a readiness review only. It does not deploy, start
or stop containers, build images, run migrations, run collectstatic, switch
traffic, change Cloudflare/domain routing, change active Compose files, change
production proxy configuration, call Shopify APIs, call Gmail APIs, send email,
or affect ticket, review request, translation, or settlement workflows.
