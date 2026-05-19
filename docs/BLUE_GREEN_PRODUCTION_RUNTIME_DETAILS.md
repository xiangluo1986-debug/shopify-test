# Blue-Green Production Runtime Details

## Purpose

Resolve production runtime design details before implementing production
blue-green apply.

The exact future proxy switch, active-color state, and rollback design is
reviewed separately in
[BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md).
That review is READY after review, but it does not approve production apply.

Final runtime approval design is documented in
[BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md](BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md).
It is READY after review, but runtime command execution remains NOT ENABLED
and production apply remains NO-GO.

The read-only production traffic path audit is documented in
[BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md](BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md).
It records that active Compose still declares `web` on host port `8000`, no
active Compose proxy service was found, DNS is Cloudflare-fronted, and exact
production proxy/origin ownership still requires manual confirmation. It does
not approve production apply.

The manual external routing decision package is documented in
[BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md).
It records the Cloudflare/origin/tunnel unknowns, conservative routing options,
and checklist required before any production blue-green proxy apply. External
routing is NOT YET confirmed, no Cloudflare/domain routing change is approved,
no host port `8000` ownership change is approved, and production apply remains
NO-GO.

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
- The traffic path audit found Docker Desktop host networking listening on
  `8000` and active Compose declaring `web` as the `8000:8000` service.
  Docker runtime container listing and the public HTTPS route were not proven
  from this shell, so external proxy/origin ownership still needs manual
  confirmation.
- A future proxy may own port `8000` only after explicit production apply
  approval.
- No task may take over port `8000` before final approval.
- External routing must be manually confirmed before deciding whether a future
  proxy owns `8000` or an external proxy/tunnel points to another proxy port.

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
  - `proxy_config_version`
  - `notes`
- Do not commit the state file.
- The state file must not contain secrets, tokens, credentials, private URLs,
  database passwords, or private environment values.
- Writes must be atomic.
- Update active color only after target health and proxy switch validation
  pass.
- Rollback updates `active_color` back to `previous_color` only after rollback
  switch and rollback health validation pass.

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
- Traffic path audit: READY after review at
  [BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md](BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md).
- External routing decision package: READY after review at
  [BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md).
- External routing confirmed: NOT YET.
- Switch/rollback review document: READY after review at
  [BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md).
- Production apply implementation: still NOT READY.
- Production apply: NO-GO.

Next required step: use these conservative defaults to design the future
production apply implementation and exact command review, then request a
separate final production approval before any runtime-changing action.

## Runtime Command Helper Status

- `scripts/blue_green_runtime_commands.ps1` exists as a plan-only / no-action
  helper for status and future command planning.
- The helper does not reload proxy, switch traffic, write
  `.deploy/active-color.json`, start/stop/restart containers, run migrations,
  run collectstatic, or execute rollback.
- Active-color state write is not enabled yet.
- Proxy reload/switch is not enabled yet.
- Rollback execution is not enabled yet.
- Production apply remains NO-GO.
- Final runtime implementation still needs a separate approval after exact
  proxy, state write, rollback, observation, cleanup, migration, scheduler, and
  media/static behavior is reviewed.
