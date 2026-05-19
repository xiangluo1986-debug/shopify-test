# Blue-Green Production Runtime Details

## Purpose

Resolve production runtime design details before implementing production
blue-green apply.

This document does not approve production apply. It does not deploy, start or
stop containers, run migrations, run collectstatic, switch traffic, change
Cloudflare or domain routing, modify active Compose files, modify production
proxy configuration, call Shopify APIs, call Gmail APIs, send email, or affect
ticket, review request, translation, settlement, Trustpilot, Kudosi, or Ali
Reviews workflows.

Production remains NO-GO.

## Recommended Conservative Design

### A. Proxy Technology

- Use nginx as the production blue-green proxy candidate.
- Do not replace the current production path until a separate production apply
  task gives explicit approval.
- The production proxy config path must be explicitly created and reviewed in a
  later task before any runtime implementation can use it.

### B. Port Ownership

- The current production `web` service owns host port `8000` today.
- A future proxy may own port `8000` only after explicit production apply
  approval.
- No task may take over port `8000` before final approval.

### C. Blue / Green Service Names

Future production services should use clear names, for example:

- `web_blue`
- `web_green`
- `bluegreen_proxy`

The scheduler remains separate and singleton. There must be no blue/green
scheduler.

### D. Active Color Storage

- Use a simple local state file under `.deploy/`, for example
  `.deploy/active-color.json`.
- The state file should contain:
  - `active_color`
  - `previous_color`
  - `updated_at`
  - `updated_by`
  - `deploy_id`
- Do not commit the state file.
- The state file must not contain secrets, tokens, credentials, private URLs,
  database passwords, or private environment values.

### E. Proxy Switch Mechanism

- A future switch should update only a controlled local proxy
  include/symlink/state file after the target color passes health checks.
- The exact proxy reload or switch command must be reviewed later.
- Do not change Cloudflare or domain routing in the first production apply
  unless separately approved.

### F. Rollback Command

- Rollback should switch the proxy back to `previous_color`.
- Rollback should not rollback the database unless separately approved.
- The old color must be kept running during the observation window.
- Rollback must also use the deployment lock.

### G. Observation Window

- Conservative default: at least 10 minutes for the first production apply.
- During observation, check `/healthz/`, the admin login path, key internal
  pages, and web logs.
- Do not clean up the old color until observation passes.

### H. Migration Policy

- Only backward-compatible migrations are allowed in blue-green apply.
- Destructive migrations require a separate deploy plan.
- Do not remove or rename fields in the same deploy as the blue-green switch.

### I. Scheduler Singleton

- The scheduler must not be duplicated.
- Shopify sync, Review Request, settlement, Gmail/Trustpilot jobs, and other
  scheduled jobs must not run twice.

### J. Media / Static

- Media and uploads must be shared.
- Static handling must be reviewed before production proxy switch.
- Container-local-only upload storage is not acceptable.

## Go / No-Go

- Runtime details: READY after review.
- Production apply implementation: still NOT READY.
- Production apply: NO-GO.

Next required step: use these conservative defaults to design the future
production apply implementation and exact command review, then request a
separate final production approval before any runtime-changing action.
