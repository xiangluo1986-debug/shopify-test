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
active Compose proxy service was found, and Cloudflare Tunnel Published
application routes for both `tickets.kidstoyloverapps.com` and
`shopify.kidstoyloverapps.com` target `http://127.0.0.1:8000`. It does not
approve production apply.

The manual external routing decision package is documented in
[BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md).
It records the confirmed Cloudflare Published application route targets,
conservative routing options, and checklist required before any production
blue-green proxy apply. No Cloudflare/domain routing change is approved, no
host port `8000` ownership change is approved, and production apply remains
NO-GO.

The dedicated traffic path option comparison is documented in
[BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md](BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md).
It documents Option A, where `bluegreen_proxy` takes local `8000`, and Option
B, where Cloudflare Published application routes point to a new proxy port. The
conservative recommendation is Option B, but it is not approved yet.

The no-action Option B Cloudflare route change and rollback plan is documented
in
[BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md](BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md).
It proposes `18000` as a placeholder new proxy port. The port is not final,
Cloudflare change is not approved, and production apply remains NO-GO.

The Cloudflare route change readiness and manual cutover approval package is
documented in
[BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md).
It records the proposed future target `http://127.0.0.1:18000`, rollback
target `http://127.0.0.1:8000`, required pre-cutover checks, and manual
rollback plan. It does not approve Cloudflare cutover or production apply.

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
- The Cloudflare route check confirmed both tickets and shopify Published
  application routes target `http://127.0.0.1:8000`.
- A future proxy may own port `8000` only after explicit production apply
  approval.
- No task may take over port `8000` before final approval.
- The next routing decision must compare local proxy takeover of `8000` with a
  Cloudflare Published application route service target change to a new proxy
  port.
- The documented conservative direction is Option B for the first production
  transition, but chosen option, Cloudflare change, and `8000` takeover are all
  still unapproved.

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
- Do not change Cloudflare or domain routing, or local `8000` ownership, in
  any production apply unless separately approved.

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
- Traffic path option comparison: READY after review at
  [BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md](BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md).
- Option B route plan: READY after review at
  [BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md](BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md).
- Cloudflare cutover approval package: READY after review at
  [BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md).
- Proposed Option B proxy port: `18000`, NOT FINAL.
- `18000` candidate validation: PASSED.
- `18000` candidate route: PASSED.
- Final runtime rehearsal: PASSED.
- Conservative recommendation: Option B, not approved.
- Chosen option: NOT YET.
- Cloudflare cutover: NOT APPROVED.
- Cloudflare change: NOT APPROVED.
- `8000` takeover: NOT APPROVED.
- Cloudflare Published application route origin confirmed: YES.
- Switch/rollback review document: READY after review at
  [BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md).
- Production apply implementation: still NOT READY.
- Production apply: NO-GO.

Next required step: final manual Cloudflare cutover checklist / operator
approval.

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

## Production-Candidate Proxy Design Update (2026-05-19)

- Candidate compose example exists at
  [../docker-compose.bluegreen.proxy-candidate.example.yml](../docker-compose.bluegreen.proxy-candidate.example.yml).
- Candidate nginx config example exists at
  [../nginx/bluegreen.proxy-candidate.example.conf](../nginx/bluegreen.proxy-candidate.example.conf).
- The previous local `18000` candidate test failed because nginx referenced
  `web_green:8000` while the candidate Compose file did not define a
  `web_green` service on the same Docker network.
- The fixed candidate Compose example now defines `web_blue`, `web_green`, and
  `bluegreen_proxy_candidate` on one candidate network. The blue/green
  services reuse the existing `aftersales-web` image and expose only container
  port `8000`.
- A later local `18000` candidate test confirmed nginx could reach
  `web_green`, but `web_green` returned `GET /healthz/` as HTTP 404. That
  narrowed the remaining issue to candidate web source/env alignment, not
  Docker networking.
- The candidate web services now reference the active `.env` path without
  documenting values, mount `./backend:/app`, set `working_dir: /app`, mount
  workflow logs/media like active web, and keep an explicit no-migration
  `runserver` command for local candidate validation.
- Proposed production-candidate local proxy port: `18000`
  (`bluegreen_proxy_candidate`, host `18000` -> container `80`).
- Candidate validation remains local port `18000` only. Host port `8000`
  remains the current web path and is not published by the candidate example.
- Bluegreen proxy candidate `18000` validation: PASSED on 2026-05-19.
- Option B proxy candidate local path: PASSED.
- Production script requirement: wait for `web_blue` and `web_green` health
  before proxy validation or cutover because the first proxy request can return
  HTTP 502 while backends start.
- The candidate files are example-only and do not implement proxy reload,
  active-color state write, traffic switch, rollback, scheduler, migration,
  collectstatic, or database destructive behavior.
- Current Cloudflare routes for `tickets.kidstoyloverapps.com` and
  `shopify.kidstoyloverapps.com` remain `http://127.0.0.1:8000`.
- Cloudflare route change: NOT APPROVED.
- Host port `8000` takeover: NOT APPROVED.
- Production apply remains NO-GO.
- Final runtime rehearsal: PASSED.
- Next required step: final manual Cloudflare cutover checklist / operator
  approval.
- Future cutover requires manual Cloudflare edit and rollback plan review at
  [BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md).
