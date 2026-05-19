# Blue-Green Production Command Review

## Purpose

Review the exact future production blue-green runtime command path.

This document does not approve production apply. It does not enable runtime
commands, deploy, start containers, stop containers, restart containers, build
images, run migrations, run collectstatic, switch traffic, or change proxy,
Cloudflare, domain, Shopify, ticket, review request, translation, settlement,
Gmail, Trustpilot, Kudosi, or Ali Reviews workflows.

Production remains NO-GO.

## Current Validated Prerequisites

- Local inactive runtime validation: PASSED.
- Local/test proxy routing validation: PASSED.
- Deployment lock: implemented.
- `safe_deploy` lock enforcement: active.
- Production command skeleton: implemented but blocked.

## Exact Future Production Command Groups

All command groups below are documentation for a future implementation review
only.

NOT RUN IN THIS TASK.

### A. Preflight

NOT RUN IN THIS TASK:

- `git status`.
- Current commit.
- Current `8000 /healthz/`.
- Deployment lock status.
- Active color status.
- Target color status.
- Migration compatibility confirmation.
- Scheduler singleton confirmation.
- Media/static shared storage confirmation.
- Rollback command confirmation.

The preflight must block if any required status is missing, uncertain, or not
approved for the specific production deploy being reviewed.

### B. Deployment Lock

NOT RUN IN THIS TASK:

- Acquire lock.
- Block if lock exists.
- No auto-queue.
- Parse `lock_id`.
- Release matching `lock_id` in finally.

The future implementation must acquire the deployment lock before any
runtime-changing command and must release only the matching `lock_id` owned by
the same deploy flow.

### C. Target Color Preparation

NOT RUN IN THIS TASK:

- Validate target color is not active color.
- Prepare/start target web color.
- Confirm no scheduler duplicate.
- Do not run destructive migration.
- Health check target `/healthz/`.

The future target preparation path must leave the current active color serving
traffic until the target color has passed health checks.

### D. Proxy Switch

NOT RUN IN THIS TASK:

- Validate proxy config.
- Switch only after target health passes.
- Post-switch `8000 /healthz/`.
- No Cloudflare/domain change unless separately approved.

The future proxy switch mechanism is not approved by this review document and
must remain blocked until proxy technology, config path, active color storage,
rollback, and production routing impact are known.

### E. Observation

NOT RUN IN THIS TASK:

- Observation window.
- Logs to inspect.
- Health checks to run.
- Current/old color retained.

Observation must keep the old color available until rollback is no longer
immediately required.

### F. Rollback

NOT RUN IN THIS TASK:

- Switch proxy back to old color.
- Health check old color.
- Do not rollback database unless separately approved.

Rollback is a runtime-changing path and must follow the same deployment lock
rules as the forward switch.

### G. Cleanup

NOT RUN IN THIS TASK:

- Cleanup only after observation.
- Do not remove DB/media volumes.
- Do not stop scheduler unexpectedly.

Cleanup must not remove database state, media/uploads, static state, secrets,
or rollback-required runtime state.

## Production Command Unknowns / Blockers

The following items are still unknown or must be decided before production
runtime command implementation can be enabled:

- Actual production proxy technology/path.
- Whether proxy owns port `8000`.
- Blue/green service names in production.
- Active color storage.
- Exact proxy reload/switch mechanism.
- Rollback exact command.
- Observation time.
- Migration policy for this deploy.
- Scheduler singleton confirmation.
- Media/static confirmation.

## Go / No-Go

- Command review doc: READY after review.
- Production implementation: NOT READY.
- Production apply: NO-GO.

Next required step: resolve production proxy, active-color, and rollback details
before any future runtime command implementation task.
