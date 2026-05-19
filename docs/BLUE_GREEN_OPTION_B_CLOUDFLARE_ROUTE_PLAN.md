# Blue-Green Option B Cloudflare Route Plan

## Purpose

Plan the future Option B Cloudflare route target change for the first
blue-green production transition.

This document does not approve a Cloudflare change. It does not approve
production apply. It does not deploy, start or stop containers, reload proxy,
switch traffic, write active-color state, or change runtime configuration.

Production remains NO-GO.

## Current Confirmed Cloudflare Route Targets

- Tunnel: `aftersales-ticket`.
- Route type: Cloudflare Tunnel Published application routes.
- `tickets.kidstoyloverapps.com` -> `http://127.0.0.1:8000`.
- `shopify.kidstoyloverapps.com` -> `http://127.0.0.1:8000`.
- Hostname routes tab: empty.

## Proposed Future Option B Target

Conservative placeholder:

- Proposed `bluegreen_proxy` local port: `18000`.
- Future target:
  - `tickets.kidstoyloverapps.com` -> `http://127.0.0.1:18000`.
  - `shopify.kidstoyloverapps.com` -> `http://127.0.0.1:18000`.

`18000` is proposed, not active. The final port must be approved later. No
Cloudflare edit is approved or performed by this task.

## Preconditions Before Future Cloudflare Route Change

- `bluegreen_proxy` is running and healthy on the chosen new local port.
- `/healthz/` through `bluegreen_proxy` returns HTTP 200.
- Current `8000` remains healthy.
- Deployment lock is acquired for the runtime-changing task.
- Rollback target is confirmed as `http://127.0.0.1:8000`.
- Both tickets and shopify routes are changed consistently.
- Cloudflare Access policies remain unchanged.
- Approval owner is confirmed.
- Observation window is confirmed.
- Old web path remains available during observation if possible.

## Future Manual Cloudflare Change Steps

NOT RUN IN THIS TASK.

1. Open Cloudflare One / Zero Trust.
2. Go to Networks > Connectors > `aftersales-ticket`.
3. Go to Published application routes.
4. Edit the `tickets.kidstoyloverapps.com` route.
5. Change service target from `http://127.0.0.1:8000` to
   `http://127.0.0.1:18000`.
6. Edit the `shopify.kidstoyloverapps.com` route.
7. Change service target from `http://127.0.0.1:8000` to
   `http://127.0.0.1:18000`.
8. Do not change Access policy unless separately approved.
9. Do not delete routes.
10. Do not change tunnel token.

## Future Validation After Cloudflare Change

- Check external tickets health and app access.
- Check external shopify health and app access.
- Check internal `8000` health.
- Check `bluegreen_proxy` local health on the approved new local port.
- Monitor logs.
- Confirm Cloudflare Access login still works.

## Rollback Plan

NOT RUN IN THIS TASK.

1. Change the `tickets.kidstoyloverapps.com` service target back to
   `http://127.0.0.1:8000`.
2. Change the `shopify.kidstoyloverapps.com` service target back to
   `http://127.0.0.1:8000`.
3. Verify external access.
4. Do not rollback database.
5. Keep logs for investigation.

## Risks

- Both tickets and shopify share the route target.
- A mistake can affect both admin apps.
- Cloudflare Access may make an external `/healthz/` test return an Access
  page instead of app `OK`.
- Rollback is manual unless future API automation is approved.
- Clear screenshots or manual confirmation are needed before applying.

## Go / No-Go

- Option B plan: READY after review.
- Chosen port: NOT FINAL.
- Proposed placeholder port: `18000`.
- Cloudflare change: NOT APPROVED.
- Production apply: NO-GO.
