# Blue-Green Hardening Plan

## Purpose

This plan lists the production hardening work needed after the manual
Cloudflare cutover to the `18000` candidate proxy path.

This is a planning document only. It does not deploy, restart, rebuild,
reload, switch traffic, change Cloudflare routes, run migrations, run
collectstatic, write active-color state, call Shopify APIs, call Gmail APIs,
or send email.

## Current Baseline

- Cloudflare target for both tickets and shopify:
  `http://127.0.0.1:18000`.
- Rollback target: `http://127.0.0.1:8000`.
- Active candidate services that must remain running:
  `bluegreen_proxy_candidate`, `web_blue`, and `web_green`.
- Old `8000` path remains available and must not be removed yet.
- External manual checks for both tickets and shopify were confirmed after
  cutover.
- Future issue triage should start with `18000 /healthz/`, `8000 /healthz/`,
  and candidate service status.

## Hardening Goals

- Make the candidate proxy a formal long-term production proxy service.
- Keep rollback to `8000` available until the observation period and
  hardening checklist are complete.
- Make health and error detection visible without exposing secrets.
- Integrate future deploys into a locked blue-green flow.
- Avoid ad hoc restart, rebuild, route edit, or cleanup steps.

## Formal Production Proxy Service

Convert `bluegreen_proxy_candidate` into a reviewed long-term production proxy
service in a later approved implementation task.

Use [BLUE_GREEN_FORMALIZATION_PLAN.md](BLUE_GREEN_FORMALIZATION_PLAN.md) as the
dry-run plan for staging that conversion. The formalization plan keeps the
current `18000` path alive, keeps `8000` as rollback, and blocks live service
renames or real apply work until a later approved task.

Required decisions before implementation:

- Final service name: keep `bluegreen_proxy_candidate` temporarily or rename to
  a stable production name.
- Final Compose ownership: decide whether the proxy and color services live in
  the main Compose file or a reviewed production overlay.
- Final host port: keep Cloudflare targeting `18000` for the first stable
  period unless a separate task approves a different port model.
- Final proxy configuration path and validation command.
- Final upstream switch method: config include, generated config, symlink, or
  another reviewed mechanism.
- Active-color state source and atomic write helper.
- Rollback authority and exact manual or scripted route.

Acceptance criteria:

- Proxy config validation exists before reload or switch.
- Proxy health check exists at `http://127.0.0.1:18000/healthz/`.
- Both `web_blue` and `web_green` can be health-checked without changing
  public traffic.
- The old `8000` rollback path remains documented until cleanup is approved.

## Restart Policy Requirements

The long-term runtime should explicitly define restart behavior for:

- Production proxy service.
- `web_blue`.
- `web_green`.

Recommended policy for review: `unless-stopped`, unless the production
operator chooses a stricter policy such as `always`. The selected policy must
be documented before implementation.

Requirements:

- A host reboot should not leave the proxy or color web services down.
- Restart policy must not create duplicate schedulers.
- Restart policy must not start unapproved migration, collectstatic, or deploy
  actions.
- Restart policy changes require a separate implementation task and deployment
  lock if they change running containers.

## Health Checks

Minimum health checks to design:

- Public candidate proxy path:
  `http://127.0.0.1:18000/healthz/`.
- Rollback path:
  `http://127.0.0.1:8000/healthz/`.
- Direct `web_blue` health through the Docker network or a reviewed local-only
  port.
- Direct `web_green` health through the Docker network or a reviewed
  local-only port.

Health check requirements:

- Use safe GET requests only.
- Do not call Shopify, Gmail, Trustpilot, Kudosi, Ali Reviews, or other
  external write APIs.
- Do not print environment values or secrets.
- Treat repeated health failures as alertable events.
- Record status in sanitized local output, not committed logs.

## Monitoring And Notification Design

Design monitoring for:

- Repeated `500` responses on tickets and shopify pages.
- `18000 /healthz/` failure.
- `8000 /healthz/` failure.
- `bluegreen_proxy_candidate` container exit or restart loop.
- `web_blue` or `web_green` container exit or restart loop.
- Proxy upstream errors such as `502` from an unavailable color service.

Notification requirements:

- Alert when `18000 /healthz/` fails more than once in a short window.
- Alert when public pages return repeated `500` responses.
- Alert when the rollback path `8000 /healthz/` is also unhealthy.
- Include hostname, path, HTTP status, timestamp, and checked target.
- Exclude secrets, tokens, cookies, customer data, addresses, phone numbers,
  order details, and ticket bodies.

Possible implementation paths for a later task:

- Windows scheduled PowerShell health watcher.
- Container-side read-only health watcher.
- Existing uptime monitoring service if already approved.
- Local browser or host sound notification for urgent operator attention.

## Safe Deploy Integration

Future deployments should use the blue-green path instead of restarting the
only serving web container.

Future flow:

1. Acquire the deployment lock before the first runtime-changing action.
2. Identify active and inactive color.
3. Prepare the inactive color.
4. Run Django checks against the inactive color.
5. Confirm inactive color `/healthz/`.
6. Validate proxy configuration.
7. Switch proxy to the inactive color only after health passes.
8. Confirm `18000 /healthz/` and key public pages.
9. Keep the previous color running through the observation window.
10. Roll back to the previous color or `8000` only with reviewed authority.
11. Cleanup only after the stable observation period.

The deployment lock remains mandatory for all real deploy, switch, rollback,
restart, rebuild, cleanup, migration, collectstatic, active-color write, and
runtime-changing actions.

## Cleanup Strategy For Old Path

Do not remove or stop the old `8000` path yet.

Cleanup can be considered only after:

- A stable observation period with no repeated `500` or health failures.
- Monitoring and notification are in place.
- Rollback runbook is reviewed and tested in a no-action review.
- Long-term proxy service ownership is implemented and reviewed.
- Future deploy flow uses the blue-green path behind the deployment lock.
- A separate cleanup task explicitly approves what will be stopped or removed.

Cleanup must not:

- Remove database volumes.
- Remove media or upload storage.
- Remove secrets or secret-bearing config.
- Stop the scheduler unless a separate reviewed plan requires it.
- Run broad cleanup commands such as `docker compose down -v` or Docker prune.

## Review Status

- Post-cutover observation doc: ready for review after creation.
- Hardening plan: ready for review after creation.
- Rollback runbook: ready for review after creation.
- Long-term operations doc: ready for review after creation.
- Formalization plan: ready for review after creation.
- Production runtime implementation: not enabled by this plan.
- Production apply scripts: still no-action / blocked unless separately
  approved.
