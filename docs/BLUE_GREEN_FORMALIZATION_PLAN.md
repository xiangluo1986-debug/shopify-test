# Blue-Green Formalization Plan

## Purpose

This document formalizes the dry-run plan for converting the current
production-candidate blue-green proxy setup into a reviewed long-term
production blue-green setup.

This is a documentation and dry-run plan only. It does not deploy, start,
stop, restart, or build containers; change Cloudflare routes; run migrations;
run collectstatic; reload proxy configuration; switch traffic; write
active-color state; call Shopify APIs; call Gmail APIs; call
`translationsRegister`; or send email.

## Current Baseline

- Cloudflare routes for `tickets.kidstoyloverapps.com` and
  `shopify.kidstoyloverapps.com` currently target
  `http://127.0.0.1:18000`.
- Port `18000` is served by `bluegreen_proxy_candidate`.
- `bluegreen_proxy_candidate`, `web_blue`, and `web_green` must remain
  running while Cloudflare targets `18000`.
- Port `8000` remains the rollback target and must not be stopped, removed,
  renamed, or taken over yet.
- Production runtime execution is still not enabled.
- Production apply remains NO-GO until a later approved runtime-changing task
  passes formal dry-run checks and acquires the deployment lock.

## Formalization Goal

The long-term target is a production blue-green flow where:

- A reviewed proxy service is the stable Cloudflare origin.
- `web_blue` and `web_green` are managed as formal color services.
- The inactive color can be prepared and health-checked without public traffic.
- The proxy can switch to the healthy inactive color through an approved,
  validated command path.
- The previous color remains available during observation.
- `8000` remains available as rollback until a separate cleanup task approves
  any change.

Formalization must happen in stages. The current candidate proxy path is live,
so the first phase is observation and documentation, not renaming or runtime
replacement.

## Staged Rollout Plan

### Stage 0 - Observe Current 18000 Path

Status: current safe stage.

Actions:

- Check `http://127.0.0.1:18000/healthz/`.
- Check `http://127.0.0.1:8000/healthz/`.
- Confirm `bluegreen_proxy_candidate`, `web_blue`, and `web_green` remain
  running through read-only status checks.
- Keep the current Cloudflare routes unchanged.
- Keep the old `8000` path available as rollback.
- Record only sanitized observations: timestamp, target, HTTP status, and a
  short symptom summary when needed.

Do not change runtime behavior in this stage.

### Stage 1 - Prepare Formal Compose And Service Naming

Status: future design review only.

Decisions to prepare before implementation:

- Whether the long-term proxy service keeps the
  `bluegreen_proxy_candidate` name temporarily or changes to a stable name
  such as `bluegreen_proxy`.
- Whether the formal services live in the main Compose file or in a reviewed
  production overlay.
- Whether Cloudflare continues to target `18000` for the first stable period.
- The exact proxy config path and validation command.
- The exact active-color state path and atomic write behavior.
- The exact rollback path from proxy switch back to previous color and, if
  needed, from Cloudflare origin back to `http://127.0.0.1:8000`.

No live service rename is allowed until the rollback plan covers both old and
new names and the formal dry-run proves the command sequence.

### Stage 2 - Add Restart Policies In A Reviewed Runtime Plan

Status: future implementation task only.

The formal runtime should define restart policy expectations for:

- The production proxy service.
- `web_blue`.
- `web_green`.

Recommended starting point for review: `unless-stopped`, unless the operator
selects a different policy.

Restart policy changes must not:

- Start duplicate schedulers.
- Run migrations or collectstatic automatically.
- Build images.
- Change Cloudflare routes.
- Stop or remove the `8000` rollback path.

Any real restart policy change is runtime-changing work and must use the
deployment lock.

### Stage 3 - Add Health Checks And Monitoring Design

Status: future design and implementation task only.

Minimum health checks:

- Public candidate path: `http://127.0.0.1:18000/healthz/`.
- Rollback path: `http://127.0.0.1:8000/healthz/`.
- Direct `web_blue` health through a reviewed local-only or Docker-network
  path.
- Direct `web_green` health through a reviewed local-only or Docker-network
  path.

Monitoring must avoid secrets, tokens, cookies, customer data, addresses,
phone numbers, order details, ticket bodies, and private environment values.

### Stage 4 - Update Safe Deploy Dry-Run First

Status: future no-action script update before any runtime apply.

Before real production blue-green execution is enabled, the dry-run path must
print:

- Current Cloudflare target: `http://127.0.0.1:18000`.
- Rollback target: `http://127.0.0.1:8000`.
- Candidate services that must remain running.
- Formal service names and compose paths planned for the later apply.
- Restart policy plan status.
- Health check plan status.
- Active-color state write status: NOT ENABLED.
- Proxy switch execution status: NOT ENABLED.
- Rollback execution status: NOT ENABLED.
- Production apply status: NO-GO until final approval.

The dry-run must remain no-action and must not acquire the production lock
unless a later reviewed design explicitly requires a lock check for a
runtime-changing mode.

### Stage 5 - Validate Inactive Color

Status: future controlled validation only.

Validation must prove an inactive color can become healthy without taking over
`8000` or changing public traffic. The validation must use a non-`8000` test
port or Docker-network-only health path, must keep the active `18000` path
alive, and must leave the old `8000` rollback path untouched.

Any validation that starts, stops, restarts, or builds containers requires a
separate approved task and deployment lock handling.

### Stage 6 - Later Controlled Real Apply

Status: not approved by this document.

A later real apply may be considered only after:

- The formalization dry-run passes.
- The inactive color validation passes.
- Restart policy and health check behavior are reviewed.
- The rollback plan is reviewed and still includes `8000`.
- The exact runtime commands are reviewed.
- The deployment lock behavior is confirmed.
- A separate explicit approval authorizes the real runtime-changing task.

The first real apply must keep the previous color running through observation
and must not remove the `8000` rollback target.

## What Must Not Be Done Yet

- Do not stop port `8000`.
- Do not remove the current `8000` rollback path.
- Do not remove or stop `bluegreen_proxy_candidate`, `web_blue`, or
  `web_green` while Cloudflare targets `18000`.
- Do not remove the candidate proxy before the formal service is running,
  healthy, and covered by a rollback plan.
- Do not rename live services without a rollback plan for both old and new
  service names.
- Do not run a real deploy until the formal dry-run passes.
- Do not run migrations or collectstatic as part of formalization planning.
- Do not reload proxy configuration or switch traffic in a documentation task.
- Do not write active-color state in this phase.
- Do not change Cloudflare routes in this phase.
- Do not call Shopify, Gmail, Trustpilot, Kudosi, Ali Reviews, or external
  write APIs.
- Do not stage, commit, or push generated logs or runtime output.

## Dry-Run Review Checklist

Before this plan can feed a future implementation task, review must confirm:

- `18000 /healthz/` passes or any failure is understood.
- `8000 /healthz/` passes or rollback risk is explicitly addressed.
- Candidate service names and formal target names are mapped.
- The formal Compose ownership model is selected.
- Restart policies are planned and do not create duplicate schedulers.
- Health checks are planned for proxy, rollback, blue, and green paths.
- `scripts/blue_green_deploy_dry_run.ps1` reports formalization status while
  remaining no-action.
- Future runtime-changing commands are still behind deployment lock rules.
- Cleanup of `8000` is out of scope.

## Review Status

- Formalization plan: ready for ChatGPT review after this documentation task.
- Runtime behavior changed by this plan: no.
- Cloudflare routing changed by this plan: no.
- Container/proxy start, stop, restart, or build by this plan: no.
- Deploy, migration, collectstatic, proxy reload, or traffic switch by this
  plan: no.
- Production apply: NO-GO.
