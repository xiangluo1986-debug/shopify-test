# Blue-Green Post-Cutover Observation

## Purpose

This document records the current post-cutover production state and the first
checks to use if the blue-green candidate path shows a problem.

This is documentation only. It does not change Cloudflare routes, start or
stop containers, restart containers, rebuild images, deploy code, run
migrations, run collectstatic, reload proxy configuration, switch traffic,
write active-color state, call Shopify APIs, call Gmail APIs, or send email.

## Current Production Traffic State

- Current Cloudflare target for `tickets.kidstoyloverapps.com`:
  `http://127.0.0.1:18000`.
- Current Cloudflare target for `shopify.kidstoyloverapps.com`:
  `http://127.0.0.1:18000`.
- Current production traffic path:

```text
Cloudflare Tunnel
  -> 127.0.0.1:18000
  -> bluegreen_proxy_candidate
  -> web_blue / web_green
```

- Rollback target remains `http://127.0.0.1:8000`.
- The old `8000` path must not be removed yet.
- `8000` remains the rollback path until a separate cleanup task is reviewed
  and explicitly approved.

## Required Running Services

The following services must remain running while Cloudflare targets `18000`:

- `bluegreen_proxy_candidate`
- `web_blue`
- `web_green`

Do not stop, restart, rebuild, or redeploy these services as part of
observation. Any future runtime-changing action requires the deployment lock
and a separate approved task.

## Recorded Manual Check Result

Manual external checks were confirmed after the Cloudflare route target change:

- `tickets.kidstoyloverapps.com`: passed.
- `shopify.kidstoyloverapps.com`: passed.

This document does not repeat those external checks and does not perform any
Cloudflare or application routing change.

## First Checks For Any Future Issue

If either tickets or shopify appears unhealthy after cutover, check in this
order:

1. `http://127.0.0.1:18000/healthz/`
2. `http://127.0.0.1:8000/healthz/`
3. Candidate service status for `bluegreen_proxy_candidate`, `web_blue`, and
   `web_green`.
4. Whether both public hostnames are affected or only one hostname is affected.
5. Whether the failure is only an application page, only `/healthz/`, or both.

Safe read-only checks:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:18000/healthz/" -UseBasicParsing
Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz/" -UseBasicParsing
docker ps
docker compose ps
```

Use log inspection only for diagnosis. Do not commit logs or generated
runtime output.

## Issue Triage Guide

- `18000 /healthz/` fails and `8000 /healthz/` passes: treat the candidate
  path as suspect. Use the rollback runbook to manually change both
  Cloudflare route targets back to `http://127.0.0.1:8000` if user-facing
  failures are confirmed.
- Both `18000 /healthz/` and `8000 /healthz/` fail: treat this as an
  application/runtime issue, not only a blue-green candidate issue. Preserve
  evidence and avoid cleanup.
- `18000 /healthz/` passes but a public page fails: inspect application errors
  and request path behavior before changing traffic. Preserve sanitized
  evidence.
- Only one hostname fails: verify the hostname-specific Cloudflare route and
  application path behavior. Do not change routes without explicit approval.

## Observation Rules

- Keep the `18000` candidate path alive.
- Keep the `8000` rollback path alive.
- Keep candidate services running.
- Do not remove the old path during the initial observation period.
- Do not run deploy, migration, collectstatic, proxy reload, traffic switch,
  active-color write, container restart, container stop, container start, or
  image build commands during observation.
- Do not call external write APIs.
- Do not expose secrets in notes, logs, screenshots, or commits.

## Exit Criteria For Observation

The cutover should remain in observation until all of the following are true:

- No repeated `500` errors or `/healthz/` failures are observed on the
  `18000` path.
- Tickets and shopify manual checks remain healthy.
- The rollback runbook has been reviewed and remains usable.
- Monitoring and notification gaps are documented in
  [BLUE_GREEN_HARDENING_PLAN.md](BLUE_GREEN_HARDENING_PLAN.md).
- Cleanup of the old `8000` path has a separate reviewed plan and explicit
  approval.

## Related Documents

- [BLUE_GREEN_HARDENING_PLAN.md](BLUE_GREEN_HARDENING_PLAN.md)
- [BLUE_GREEN_ROLLBACK_RUNBOOK.md](BLUE_GREEN_ROLLBACK_RUNBOOK.md)
- [BLUE_GREEN_LONG_TERM_OPERATIONS.md](BLUE_GREEN_LONG_TERM_OPERATIONS.md)
- [SAFE_DEPLOY.md](SAFE_DEPLOY.md)
- [BLUE_GREEN_DEPLOY_PLAN.md](BLUE_GREEN_DEPLOY_PLAN.md)
