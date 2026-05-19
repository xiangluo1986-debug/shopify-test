# Blue-Green Manual Cloudflare Cutover Checklist

## Purpose

Provide the final manual checklist before any Cloudflare route cutover.

This document does not perform the cutover.

This document does not approve production apply by itself.

Cloudflare cutover remains NOT APPROVED until the operator explicitly approves.

## Current Confirmed Route Targets

- Tunnel: `aftersales-ticket`.
- Route type: Published application routes.
- `tickets.kidstoyloverapps.com` -> `http://127.0.0.1:8000`.
- `shopify.kidstoyloverapps.com` -> `http://127.0.0.1:8000`.
- Hostname routes tab is empty.

## Proposed Future Cutover Target

- `tickets.kidstoyloverapps.com` -> `http://127.0.0.1:18000`.
- `shopify.kidstoyloverapps.com` -> `http://127.0.0.1:18000`.
- `18000` is the `bluegreen_proxy_candidate` local port.
- `18000` final runtime rehearsal has PASSED.
- Final manual approval is still required.

## Required Approval Phrase

```text
I_APPROVE_MANUAL_CLOUDFLARE_CUTOVER_TO_18000_AFTER_FINAL_REHEARSAL
```

- This phrase is documentation-only for now.
- No script should accept this phrase yet.
- The actual Cloudflare change is manual.
- Operator must type/confirm this phrase before editing Cloudflare.

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

- Manual cutover checklist: READY after review.
- Cloudflare cutover: NOT APPROVED.
- Production apply: NO-GO until operator approval.
- Runtime execution: NOT ENABLED except manual candidate rehearsal already tested.
