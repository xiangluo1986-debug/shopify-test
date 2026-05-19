# Blue-Green Cloudflare Cutover Approval

## Purpose

Prepare the future manual Cloudflare Published application route cutover for
the blue-green deployment path.

This document does not approve Cloudflare changes. It does not approve
production apply. Production remains NO-GO.

## Current Confirmed Route Targets

- Tunnel: `aftersales-ticket`.
- Route type: Published application routes.
- `tickets.kidstoyloverapps.com` -> `http://127.0.0.1:8000`.
- `shopify.kidstoyloverapps.com` -> `http://127.0.0.1:8000`.
- Hostname routes tab is empty.

## Proposed Future Cutover Target

- `tickets.kidstoyloverapps.com` -> `http://127.0.0.1:18000`.
- `shopify.kidstoyloverapps.com` -> `http://127.0.0.1:18000`.
- Port `18000` is the `bluegreen_proxy_candidate` port.
- `18000` candidate validation has PASSED locally.
- Final approval is still required before any Cloudflare edit.

## Required Pre-Cutover Checks

Before any future Cloudflare edit:

- `git status` reviewed.
- Deployment lock available.
- No existing deployment lock.
- Current `8000 /healthz/` OK.
- `bluegreen_proxy_candidate` running and healthy on `18000`.
- `18000 /healthz/` HTTP 200.
- `web_blue` and `web_green` healthy.
- Rollback target confirmed: `http://127.0.0.1:8000`.
- Both tickets and shopify routes must be edited consistently.
- Cloudflare Access policies must not be changed.
- Old path `8000` kept available during observation.
- Observation window approved.
- Rollback owner confirmed.

## Manual Cutover Approval Phrase

```text
I_APPROVE_MANUAL_CLOUDFLARE_ROUTE_CUTOVER_TO_18000
```

This phrase is documentation-only for now. No script should accept this phrase
yet. Actual Cloudflare edit remains manual and separately approved.

## Future Manual Cutover Steps

NOT RUN IN THIS TASK.

1. Open Cloudflare One / Zero Trust.
2. Go to Networks > Connectors > `aftersales-ticket`.
3. Go to Published application routes.
4. Confirm tickets route currently points to `http://127.0.0.1:8000`.
5. Confirm shopify route currently points to `http://127.0.0.1:8000`.
6. Edit tickets route service target to `http://127.0.0.1:18000`.
7. Edit shopify route service target to `http://127.0.0.1:18000`.
8. Do not change Access policies.
9. Do not delete routes.
10. Do not change tunnel token.
11. Do not change hostname routes.

## Future Validation After Cutover

After future manual cutover:

- Confirm local `18000 /healthz/` still HTTP 200.
- Confirm local `8000 /healthz/` still HTTP 200.
- Confirm external tickets app loads or Access page behaves as expected.
- Confirm external shopify app loads or Access page behaves as expected.
- Confirm key admin pages after login if available.
- Monitor app logs.
- Observe for approved window.

## Rollback Plan

NOT RUN IN THIS TASK.

Rollback:

1. Change `tickets.kidstoyloverapps.com` target back to
   `http://127.0.0.1:8000`.
2. Change `shopify.kidstoyloverapps.com` target back to
   `http://127.0.0.1:8000`.
3. Confirm external access returns to previous behavior.
4. Do not rollback database.
5. Keep logs for investigation.
6. Keep deployment lock rules in place.

## Risks

- Both tickets and shopify share the route target.
- A wrong route target can affect both admin apps.
- Cloudflare Access may show login page instead of `/healthz/` OK externally.
- Rollback is manual unless future Cloudflare API automation is separately
  designed and approved.
- Do not cut over unless the `18000` candidate is already healthy.

## Go / No-Go

- Cutover approval package: READY after review.
- Cloudflare cutover: NOT APPROVED.
- Production apply: NO-GO.
- Runtime execution: NOT ENABLED.
