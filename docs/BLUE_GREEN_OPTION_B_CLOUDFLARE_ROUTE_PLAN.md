# Blue-Green Option B Cloudflare Route Plan

## Purpose

Plan the future Option B Cloudflare route target change for the first
blue-green production transition.

This document does not approve a Cloudflare change. It does not approve
production apply. It does not deploy, start or stop containers, reload proxy,
switch traffic, write active-color state, or change runtime configuration.

Production remains NO-GO.

The Cloudflare route change readiness and manual cutover approval package now
exists at
[BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md).
It is documentation-only, does not approve Cloudflare changes, and does not
approve production apply.

## Current Confirmed Cloudflare Route Targets

- Tunnel: `aftersales-ticket`.
- Route type: Cloudflare Tunnel Published application routes.
- `tickets.kidstoyloverapps.com` -> `http://127.0.0.1:8000`.
- `shopify.kidstoyloverapps.com` -> `http://127.0.0.1:8000`.
- Hostname routes tab: empty.

## Proposed Future Option B Target

Documented proposed target:

- Proposed `bluegreen_proxy` local port: `18000`.
- Future target:
  - `tickets.kidstoyloverapps.com` -> `http://127.0.0.1:18000`.
  - `shopify.kidstoyloverapps.com` -> `http://127.0.0.1:18000`.

`18000` is proposed, not active. The local `18000` proxy candidate validation
has PASSED, but final manual Cloudflare cutover approval is still required. No
Cloudflare edit is approved or performed by this task.

## Preconditions Before Future Cloudflare Route Change

- `bluegreen_proxy` is running and healthy on the chosen new local port.
- `/healthz/` through `bluegreen_proxy` returns HTTP 200.
- Current `8000` remains healthy.
- `git status` has been reviewed.
- Deployment lock is available.
- No existing deployment lock is present.
- Deployment lock is acquired for the runtime-changing task.
- `web_blue` and `web_green` are healthy.
- Rollback target is confirmed as `http://127.0.0.1:8000`.
- Both tickets and shopify routes are changed consistently.
- Cloudflare Access policies remain unchanged.
- Approval owner is confirmed.
- Observation window is confirmed.
- Rollback owner is confirmed.
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
- Cloudflare cutover approval package: READY after review at
  [BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md).
- Chosen port: `18000`, ACTIVE current Cloudflare target.
- Previous target / rollback target: `http://127.0.0.1:8000`.
- `18000` candidate validation: PASSED.
- `18000` candidate route: PASSED.
- Final runtime rehearsal: PASSED.
- Cloudflare cutover: PASSED.
- Cloudflare change in this documentation task: no.
- Candidate services must remain running: `bluegreen_proxy_candidate`,
  `web_blue`, and `web_green`.
- Production blue-green external traffic path: ACTIVE through `18000`
  candidate.
- Production apply scripts remain no-action / blocked unless separately
  approved.
- Runtime command execution remains NOT ENABLED except already-running manual
  candidate services.
- Next required step: post-cutover observation and hardening plan.

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
- The candidate files are example-only, production-candidate design-only, not
  active, not used by normal `docker compose` commands, and must not bind
  host port `8000`.
- Current Cloudflare routes for `tickets.kidstoyloverapps.com` and
  `shopify.kidstoyloverapps.com` now target `http://127.0.0.1:18000`.
- Previous target / rollback target: `http://127.0.0.1:8000`.
- Cloudflare route change: PASSED by manual Option B cutover before this
  documentation update.
- Host port `8000` takeover: NOT APPROVED.
- Production apply scripts remain no-action / blocked unless separately
  approved.
- Production blue-green external traffic path is now active through the
  `18000` candidate.
- Candidate services must remain running: `bluegreen_proxy_candidate`,
  `web_blue`, and `web_green`.
- Post-cutover observation and hardening plan should use the rollback plan at
  [BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md).

## Bluegreen Proxy Candidate 18000 Validation Result (2026-05-19)

- Validation status: PASSED.
- Scope: local production-candidate proxy only.
- Candidate compose: `docker-compose.bluegreen.proxy-candidate.example.yml`.
- Candidate proxy: `bluegreen_proxy_candidate`.
- Candidate port: `18000`.
- Candidate web services: `web_blue` and `web_green`.
- Initial `18000 /healthz/` returned HTTP 502 while `web_blue` and
  `web_green` were still health: starting.
- After waiting for backend health, `18000 /healthz/` returned HTTP 200.
- `8000 /healthz/` stayed HTTP 200 before and after validation.
- Earlier validation cleanup stopped only `bluegreen_proxy_candidate`,
  `web_green`, and `web_blue`.
- After the later manual Cloudflare cutover, candidate services must remain
  running because Cloudflare now targets `18000`.
- Cloudflare change: no.
- Cloudflare route change in this documentation task: no.
- Cloudflare cutover result: PASSED before this documentation task.
- Current Cloudflare target: `http://127.0.0.1:18000`.
- Rollback target: `http://127.0.0.1:8000`.
- Production traffic path: ACTIVE through `18000` candidate.
- Production apply scripts: still no-action / blocked unless separately
  approved.
- Cloudflare cutover approval package exists at
  [BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md).
- Cloudflare cutover: PASSED.
- Final runtime rehearsal: PASSED.
- Next required step: post-cutover observation and hardening plan.
- Production script requirement: wait for `web_blue` and `web_green` health
  before proxy validation or cutover because the first request may return HTTP
  502 while backends start.

## Final Manual Checklist Link

- Pre-cutover live checklist exists at
  [BLUE_GREEN_PRE_CUTOVER_LIVE_CHECKLIST.md](BLUE_GREEN_PRE_CUTOVER_LIVE_CHECKLIST.md).
- Pre-cutover live checklist: READY after review.
- Final manual Cloudflare cutover checklist exists at
  [BLUE_GREEN_MANUAL_CLOUDFLARE_CUTOVER_CHECKLIST.md](BLUE_GREEN_MANUAL_CLOUDFLARE_CUTOVER_CHECKLIST.md).
- Manual cutover checklist: READY after review.
- Approval phrase is documentation-only:
  `I_APPROVE_MANUAL_CLOUDFLARE_CUTOVER_TO_18000_AFTER_LIVE_CHECKS`.
- No script should accept the phrase yet.
- Cloudflare cutover: PASSED.
- Current Cloudflare target: `http://127.0.0.1:18000`.
- Rollback target: `http://127.0.0.1:8000`.
- Candidate services must remain running.
- Production apply scripts remain no-action / blocked unless separately
  approved.
- Next required step: post-cutover observation and hardening plan.
