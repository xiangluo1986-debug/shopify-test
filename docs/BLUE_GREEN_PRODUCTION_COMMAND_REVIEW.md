# Blue-Green Production Command Review

## Purpose

Review the exact future production blue-green runtime command path.

This document does not approve production apply. It does not enable runtime
commands, deploy, start containers, stop containers, restart containers, build
images, run migrations, run collectstatic, switch traffic, or change proxy,
Cloudflare, domain, Shopify, ticket, review request, translation, settlement,
Gmail, Trustpilot, Kudosi, or Ali Reviews workflows.

Production remains NO-GO.

Production runtime defaults for proxy technology, port ownership, service
names, active-color storage, proxy switch shape, rollback, observation,
migration policy, scheduler singleton behavior, and media/static handling are
documented in
[BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md).
Those defaults resolve the design direction only. They do not approve
production command implementation or production apply.

The exact future proxy switch, active-color state, and rollback design is
reviewed in
[BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md).
That review is READY after review, but production command implementation is
still NOT READY.

Final runtime approval design is documented in
[BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md](BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md).
It is READY after review, but runtime command execution remains NOT ENABLED
and production apply remains NO-GO.

The production traffic path audit is documented in
[BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md](BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md).
It is READY after review and records that Cloudflare Tunnel Published
application routes for both tickets and shopify target
`http://127.0.0.1:8000`. It does not approve production apply.

The manual external routing decision package is documented in
[BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md).
It records the confirmed Published application route targets and the remaining
Option A versus Option B routing decision. No Cloudflare/domain routing change
and no host port `8000` ownership change are approved without a separate future
approval.

The dedicated traffic path option comparison is documented in
[BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md](BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md).
It documents both Option A and Option B. The conservative recommendation is
Option B, but the chosen option is still NOT YET and Cloudflare changes require
separate approval.

The no-action Option B Cloudflare route change and rollback plan is documented
in
[BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md](BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md).
It proposes `18000` as a placeholder `bluegreen_proxy` port. The port is not
final, Cloudflare change is not approved, and production apply remains NO-GO.

## Current Validated Prerequisites

- Local inactive runtime validation: PASSED.
- Local/test proxy routing validation: PASSED.
- Deployment lock: implemented.
- `safe_deploy` lock enforcement: active.
- Production command skeleton: implemented but blocked.
- Production runtime details document:
  [BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md)
  exists and records conservative defaults.
- Production switch/rollback review document:
  [BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md)
  exists and is READY after review.
- Final runtime approval design:
  [BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md](BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md)
  exists and is READY after review; execution remains NOT ENABLED.
- Production traffic path audit:
  [BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md](BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md)
  exists and is READY after review; both tickets and shopify Cloudflare
  Published application routes target `http://127.0.0.1:8000`.
- External routing decision package:
  [BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md)
  exists after this package is reviewed.
- Traffic path option comparison:
  [BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md](BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md)
  exists after review; Option B is the conservative recommendation, but it is
  not approved yet.
- Option B route plan:
  [BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md](BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md)
  exists after review; proposed port `18000` is not final, Cloudflare change
  is NOT APPROVED, and production apply remains NO-GO.

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
- No host port `8000` ownership change unless separately approved.

The future proxy switch mechanism is not approved by this review document and
must remain blocked until the exact proxy config path, switch/reload command,
active-color state update, rollback command, and production routing impact are
reviewed for the specific apply. The dedicated switch/rollback review is
documented in
[BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md).
The current traffic path audit is documented in
[BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md](BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md)
and confirms both Cloudflare Published application routes target
`http://127.0.0.1:8000`. The remaining manual decision is whether
`bluegreen_proxy` owns `8000` or Cloudflare service targets move to a new proxy
port.
The external routing decision package is documented in
[BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md)
and the dedicated comparison is documented in
[BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md](BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md).
Both must be reviewed before any production proxy switch implementation.
Option B is the conservative recommendation, but not approved yet.
Conservative defaults are documented in
[BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md):
nginx candidate, no port `8000` takeover before final approval, no first-apply
Cloudflare/domain routing change unless separately approved, and switch only
through a controlled local proxy include/symlink/state file after target health
passes.

### E. Observation

NOT RUN IN THIS TASK:

- Observation window.
- Logs to inspect.
- Health checks to run.
- Current/old color retained.

Observation must keep the old color available until rollback is no longer
immediately required. Conservative default observation for the first
production apply is at least 10 minutes, with `/healthz/`, admin login path,
key internal pages, and web logs checked before cleanup.

### F. Rollback

NOT RUN IN THIS TASK:

- Switch proxy back to old color.
- Health check old color.
- Do not rollback database unless separately approved.

Rollback is a runtime-changing path and must follow the same deployment lock
rules as the forward switch. The conservative default is to switch the proxy
back to `previous_color`, keep the old color running during observation, and
avoid database rollback unless a separate database rollback task is approved.

### G. Cleanup

NOT RUN IN THIS TASK:

- Cleanup only after observation.
- Do not remove DB/media volumes.
- Do not stop scheduler unexpectedly.

Cleanup must not remove database state, media/uploads, static state, secrets,
or rollback-required runtime state.

## Production Runtime Defaults And Remaining Blockers

The following conservative defaults are now documented in
[BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md):

- Proxy candidate: nginx.
- Port ownership: current production `web` owns host port `8000`; a future
  proxy may own `8000` only after explicit final production apply approval.
- External routing: Cloudflare Published application routes are confirmed for
  both tickets and shopify to `http://127.0.0.1:8000`; production apply remains
  blocked until the Option A versus Option B routing decision is approved.
- Production service names: `web_blue`, `web_green`, and `bluegreen_proxy`.
- Active color storage: local `.deploy/active-color.json` containing
  `active_color`, `previous_color`, `updated_at`, `updated_by`, and
  `deploy_id`, plus `proxy_config_version` and `notes`.
- Active color state under `.deploy/` must not be committed and must not
  contain secrets.
- Active color state writes must be atomic and must occur only after target
  switch or rollback health validation passes.
- Proxy switch shape: controlled local proxy include/symlink/state update only
  after target health passes.
- Rollback shape: switch proxy back to `previous_color`, with deployment lock
  protection and no automatic database rollback.
- Observation default: at least 10 minutes for the first production apply.
- Migration policy: backward-compatible migrations only; destructive changes
  need a separate deploy plan.
- Scheduler policy: singleton scheduler only; no blue/green scheduler.
- Media/static policy: shared media/uploads required; static handling reviewed
  before proxy switch.

Production runtime command implementation is still blocked until a later task
reviews and implements the exact production proxy config path, switch/reload
command, rollback command, state-file write behavior, validation commands, and
cleanup commands. Scheduler singleton and migration compatibility remain
required gates for every production apply.

## Go / No-Go

- Command review doc: READY after review.
- Traffic path audit: READY after review at
  [BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md](BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md).
- External routing decision package: READY after review at
  [BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md).
- Traffic path option comparison: READY after review at
  [BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md](BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md).
- Option B route plan: READY after review at
  [BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md](BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md).
- Proposed Option B proxy port: `18000`, NOT FINAL.
- Conservative recommendation: Option B, not approved.
- Chosen option: NOT YET.
- Cloudflare change: NOT APPROVED.
- `8000` takeover: NOT APPROVED.
- Cloudflare Published application route origin confirmed: YES.
- Switch/rollback review doc: READY after review at
  [BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md).
- Production implementation: NOT READY.
- Production apply: NO-GO.

Next required step: review the Option B route plan, approve or change the
final proxy port, fill the option comparison manual decision fields, then
separately review and approve the exact runtime command path before any
production apply.

## Runtime Command Helper Status

- `scripts/blue_green_runtime_commands.ps1` exists as a blocked runtime command
  helper.
- Current helper status: plan-only / no-action.
- It prints future command plans only; it does not acquire the deployment lock,
  reload proxy, switch traffic, write active-color state, run rollback, or run
  cleanup.
- Proxy switch execution: NOT ENABLED.
- Active-color state write: NOT ENABLED.
- Rollback execution: NOT ENABLED.
- Production apply remains NO-GO.
- The final runtime implementation and any executable production command path
  require a separate approval task.
