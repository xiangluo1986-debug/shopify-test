# Blue-Green Manual Cloudflare Cutover Checklist

## Purpose

Record the final manual checklist and the completed Cloudflare route cutover.

This document does not perform the cutover.

This document does not approve production apply by itself.

Cloudflare cutover PASSED on 2026-05-19 after operator approval.

## Current Confirmed Route Targets

- Tunnel: `aftersales-ticket`.
- Route type: Published application routes.
- `tickets.kidstoyloverapps.com` -> `http://127.0.0.1:18000`.
- `shopify.kidstoyloverapps.com` -> `http://127.0.0.1:18000`.
- Previous target / rollback target: `http://127.0.0.1:8000`.
- Hostname routes tab is empty.

## Proposed Future Cutover Target

- `tickets.kidstoyloverapps.com` -> `http://127.0.0.1:18000`.
- `shopify.kidstoyloverapps.com` -> `http://127.0.0.1:18000`.
- `18000` is the `bluegreen_proxy_candidate` local port.
- `18000` final runtime rehearsal has PASSED.
- Final manual approval is still required.

## Required Approval Phrase

```text
I_APPROVE_MANUAL_CLOUDFLARE_CUTOVER_TO_18000_AFTER_LIVE_CHECKS
```

- This phrase is documentation-only for now.
- No script should accept this phrase yet.
- The actual Cloudflare change is manual.
- Operator must type/confirm this phrase before editing Cloudflare.

## Pre-Cutover Live Checklist Link

- Pre-cutover live checklist exists at
  [BLUE_GREEN_PRE_CUTOVER_LIVE_CHECKLIST.md](BLUE_GREEN_PRE_CUTOVER_LIVE_CHECKLIST.md).
- Pre-cutover live checklist: READY after review.
- Manual Cloudflare cutover: PASSED on 2026-05-19.
- Current Cloudflare target: `http://127.0.0.1:18000`.
- Rollback target: `http://127.0.0.1:8000`.
- Next required step: post-cutover observation and hardening plan.

## Pre-Cutover Checklist

- [ ] Confirm current `8000 /healthz/` is HTTP 200.
- [ ] Start `bluegreen_proxy_candidate` on `18000`.
- [ ] Confirm `18000 /healthz/` is HTTP 200.
- [ ] Confirm `web_blue` and `web_green` are healthy.
- [ ] Confirm deployment lock status is clear or acquired as planned.
- [ ] Confirm rollback target is `http://127.0.0.1:8000`.
- [ ] Confirm both tickets and shopify routes must be changed together.
- [ ] Confirm Cloudflare Access policies will not be changed.
- [ ] Confirm no database migration is being run.
- [ ] Confirm no scheduler duplicate is being started.
- [ ] Confirm rollback owner is present.
- [ ] Confirm observation window is ready.

## Manual Cloudflare Cutover Steps

NOT RUN IN THIS TASK.

1. Open Cloudflare One / Zero Trust.
2. Go to Networks > Connectors > `aftersales-ticket`.
3. Go to Published application routes.
4. Confirm `tickets.kidstoyloverapps.com` currently targets `http://127.0.0.1:8000`.
5. Change `tickets.kidstoyloverapps.com` target to `http://127.0.0.1:18000`.
6. Confirm `shopify.kidstoyloverapps.com` currently targets `http://127.0.0.1:8000`.
7. Change `shopify.kidstoyloverapps.com` target to `http://127.0.0.1:18000`.
8. Do not change Access policies.
9. Do not delete routes.
10. Do not change hostname routes.
11. Do not change tunnel token.

## Post-Cutover Validation Checklist

- [ ] Confirm local `18000 /healthz/` remains HTTP 200.
- [ ] Confirm local `8000 /healthz/` remains HTTP 200.
- [ ] Check external tickets route behavior.
- [ ] Check external shopify route behavior.
- [ ] Confirm Cloudflare Access login behavior unchanged.
- [ ] Check key admin pages after login if available.
- [ ] Monitor app logs.
- [ ] Observe for approved window.
- [ ] Do not stop old/current web path until observation passes.

## Manual Rollback Steps

NOT RUN IN THIS TASK.

Rollback:

1. Change `tickets.kidstoyloverapps.com` target back to `http://127.0.0.1:8000`.
2. Change `shopify.kidstoyloverapps.com` target back to `http://127.0.0.1:8000`.
3. Verify external access returns to previous behavior.
4. Keep `18000` candidate running until rollback is confirmed or explicitly stopped.
5. Do not rollback database.
6. Do not change Access policies.
7. Keep logs for investigation.

## Go / No-Go

- Pre-cutover live checklist: READY after review at
  [BLUE_GREEN_PRE_CUTOVER_LIVE_CHECKLIST.md](BLUE_GREEN_PRE_CUTOVER_LIVE_CHECKLIST.md).
- Manual cutover checklist: READY after review.
- Cloudflare cutover: PASSED.
- Current Cloudflare target: `http://127.0.0.1:18000`.
- Rollback target: `http://127.0.0.1:8000`.
- Candidate services must remain running: `bluegreen_proxy_candidate`,
  `web_blue`, and `web_green`.
- Production blue-green external traffic path: ACTIVE through `18000`
  candidate.
- Production apply scripts remain no-action / blocked unless separately
  approved.
- Next required step: post-cutover observation and hardening plan.

## Manual Cutover Result (2026-05-19)

- Cloudflare cutover: PASSED.
- Route type: Published application routes.
- Tunnel: `aftersales-ticket`.
- `tickets.kidstoyloverapps.com` now targets `http://127.0.0.1:18000`.
- `shopify.kidstoyloverapps.com` now targets `http://127.0.0.1:18000`.
- Previous target / rollback target: `http://127.0.0.1:8000`.
- Local `18000 /healthz/`: HTTP 200 OK.
- Local `8000 /healthz/`: HTTP 200 OK.
- External tickets and shopify browser login checks: PASSED with no obvious
  errors.
- Deployment lock was acquired and released.
- Access policies, hostname routes, tunnel token, and DNS were not changed.
- No migration, collectstatic, database rollback, proxy reload, traffic
  switch script, active-color state write, or container start/stop/restart/build
  was run by this documentation task.
- Candidate services must remain running while Cloudflare targets `18000`.
