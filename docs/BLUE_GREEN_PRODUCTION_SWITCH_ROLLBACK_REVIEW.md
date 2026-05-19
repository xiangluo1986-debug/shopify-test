# Blue-Green Production Switch / Rollback Review

## Purpose

Review the exact future production proxy switch, active-color state, and
rollback design before implementing production runtime-changing commands.

This document does not approve production apply. It does not deploy, start or
stop containers, restart containers, build images, run migrations, run
collectstatic, switch traffic, reload proxy, change Cloudflare or domain
routing, modify active Compose files, modify production proxy configuration,
call Shopify APIs, call Gmail APIs, send email, or affect ticket, review
request, translation, settlement, Trustpilot, Kudosi, or Ali Reviews workflows.

Production remains NO-GO.

## Current Conservative Defaults

- Proxy candidate: nginx.
- Future service names: `web_blue`, `web_green`, and `bluegreen_proxy`.
- Active color state: `.deploy/active-color.json`.
- Current production `web` keeps host port `8000` until final production
  approval.
- No Cloudflare or domain change unless separately approved.
- Old color retained during the observation window.
- Rollback switches proxy back to `previous_color`.
- Database rollback is not part of the default rollback.

## Active-Color State Design

Future state file shape:

```json
{
  "active_color": "blue",
  "previous_color": "green",
  "updated_at": "...",
  "updated_by": "...",
  "deploy_id": "...",
  "proxy_config_version": "...",
  "notes": "..."
}
```

Rules:

- `.deploy/active-color.json` must not be committed.
- The state file must not contain secrets, tokens, credentials, database
  passwords, private URLs, private environment values, or API keys.
- Writes must be atomic, for example by writing a temporary file under
  `.deploy/` and replacing the final file only after the complete JSON is
  written and validated.
- The active color may be updated only after target health and proxy switch
  validation pass.
- Rollback may update `active_color` back to `previous_color` only after
  rollback switch and rollback health validation pass.
- The state file is operational state only. It is not an approval record and
  must not be treated as source-controlled configuration.

## Proxy Switch Design

Future switch flow:

1. Acquire the deployment lock before any runtime-changing switch action.
2. Validate the target color health first.
3. Render or select the target upstream config.
4. Validate the proxy config before reload or switch.
5. Reload or switch proxy only after validation passes.
6. Confirm post-switch `/healthz/` through the production routing path.
7. Update `.deploy/active-color.json` only after target health and post-switch
   health pass.
8. Keep the old color running during the observation window.

Future command examples:

```text
NOT RUN IN THIS TASK
validate target color health
render or select target upstream config
validate production proxy config
reload or switch production proxy
confirm post-switch /healthz/
write .deploy/active-color.json atomically
```

Unknowns are intentionally not finalized here. The exact production nginx
config path, proxy validation command, proxy reload command, include/symlink
target, and state writer helper still require a later implementation review.
This document does not invent an active production config path as final.

## Rollback Design

Future rollback flow:

1. Acquire the deployment lock before any runtime-changing rollback action.
2. Read `previous_color` from the reviewed active-color state.
3. Validate that the previous color is still available.
4. Switch proxy back to `previous_color`.
5. Confirm post-rollback `/healthz/` through the production routing path.
6. Update `.deploy/active-color.json` only after rollback switch and rollback
   health validation pass.
7. Keep the failed target color available until logs are collected and the
   operator decides it is safe to stop.

Rollback rules:

- Rollback also requires the deployment lock.
- Rollback switches proxy back to `previous_color`.
- Post-rollback `/healthz/` must pass before active-color state is updated.
- Do not rollback the database unless separately approved.
- Do not stop the failed target until logs are collected.

Future command examples:

```text
NOT RUN IN THIS TASK
acquire deployment lock
switch proxy back to previous_color
confirm post-rollback /healthz/
write .deploy/active-color.json atomically
collect failed target logs before cleanup
```

## Cleanup Design

- Old color cleanup may run only after the approved observation window passes.
- Cleanup must not stop the scheduler.
- Cleanup must not remove database volumes, media volumes, upload storage,
  static state, secrets, or rollback-required runtime state.
- Cleanup must not run `docker compose down` for the whole project.
- Cleanup remains runtime-changing and must use the deployment lock in the
  future approved command path.

## Remaining Unknowns / Blockers

- Exact production nginx config path.
- Exact proxy reload command.
- Exact active-color atomic write helper.
- Exact production Compose files and service names.
- Rollback command authority.
- Observation window final value.
- Final migration policy for the specific deploy.
- Scheduler, media, and static confirmation for the specific deploy.

## Go / No-Go

- Switch/rollback review doc: READY after review.
- Production command implementation: NOT READY.
- Production apply: NO-GO.

Next required step: implement no runtime-changing production commands yet.
Use this review with the production runtime details and command review docs as
input to a later exact implementation task, then require separate final
production approval before any proxy reload, traffic switch, active-color
state write, cleanup, or rollback command is run.

## Runtime Command Helper Status

- `scripts/blue_green_runtime_commands.ps1` exists as a plan-only / no-action
  helper.
- The helper may print `status`, `validate-state`, `plan-switch`,
  `plan-rollback`, and `plan-cleanup` output, but it does not execute those
  runtime steps.
- Proxy switch/reload execution is not enabled.
- Active-color state write is not enabled.
- Rollback execution is not enabled.
- Production apply remains NO-GO.
- The future approval phrase
  `I_APPROVE_BLUE_GREEN_RUNTIME_COMMANDS_AFTER_FINAL_REVIEW` is documented
  only and is not active for execution.
- Final runtime implementation still needs a separate reviewed and approved
  task before any proxy reload, traffic switch, state write, rollback, or
  cleanup command can run.
