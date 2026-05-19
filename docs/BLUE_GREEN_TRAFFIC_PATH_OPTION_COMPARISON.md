# Blue-Green Traffic Path Option Comparison

## Purpose

Compare future blue-green traffic path options for the production transition.

This document does not approve production apply. It does not approve
Cloudflare changes. It does not approve local port `8000` takeover.

Production remains NO-GO.

## Confirmed Current State

- Cloudflare tunnel `aftersales-ticket` is used.
- Published application route:
  `tickets.kidstoyloverapps.com` -> `http://127.0.0.1:8000`.
- Published application route:
  `shopify.kidstoyloverapps.com` -> `http://127.0.0.1:8000`.
- Current Docker `web` owns local `8000`.
- No active `docker-compose.yml` nginx/proxy service is currently in the
  production path.
- Hostname routes are empty; current external app traffic reaches local
  `127.0.0.1:8000` through Cloudflare Tunnel Published application routes.

## Option A - bluegreen_proxy Takes Local 8000

Cloudflare Published application routes remain unchanged.

`bluegreen_proxy` eventually owns `127.0.0.1:8000` / host `8000`.

The current `web` service can no longer bind host `8000` directly.

Blue and green web containers sit behind the proxy on internal ports and the
Docker network.

Cloudflare config change is avoided.

### Pros

- Cloudflare routes remain stable.
- No Cloudflare origin edit required.
- Both tickets and shopify continue using the same tunnel route.

### Cons / Risks

- One-time local port ownership cutover required.
- Current `web` must release `8000` during the apply window.
- Needs a very careful rollback plan.
- Higher local runtime impact during transition.
- Must ensure proxy health before taking `8000`.

### Required Before Choosing

- Exact local proxy Compose design.
- Rollback path if proxy fails.
- Proof proxy can serve both tickets and shopify paths.
- Confirmation current `web` can move behind proxy safely.

## Option B - Cloudflare Routes Point To New Proxy Port

`bluegreen_proxy` runs on a new local port, for example `18000` or a
`19080`-like production port.

Cloudflare Published application routes are edited from
`http://127.0.0.1:8000` to the new proxy port.

Current `web` can keep `8000` during preparation.

Cloudflare change becomes the cutover point.

### Pros

- Avoids taking `8000` away from current `web` during preparation.
- Easier to test proxy on the new port before Cloudflare edit.
- Rollback may be Cloudflare route target back to `8000`.
- Lower local Docker port ownership risk.

### Cons / Risks

- Requires Cloudflare edit approval.
- Both tickets and shopify Published application routes must be updated
  consistently.
- Cloudflare Access / Published application behavior must be confirmed.
- Rollback requires Cloudflare edit or prepared route change.
- Mistake could affect both tickets and shopify.

### Required Before Choosing

- Cloudflare edit authority.
- Exact new proxy local port.
- Route update plan for both tickets and shopify.
- Rollback route target back to `8000`.
- Verification that Access policies remain unchanged.

## Recommended Conservative Direction

Prefer Option B for the first production transition because it allows building
and testing `bluegreen_proxy` on a new local port while current `web` remains
on `8000`.

Do not edit Cloudflare yet.

Do not take over `8000` yet.

Review the no-action Cloudflare route change plan and rollback plan before any
future route edit.

Production remains NO-GO.

The no-action Option B route change and rollback plan now exists at
[BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md](BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md).
It proposes `18000` as a conservative placeholder proxy port, but that port is
not final. The plan does not approve any Cloudflare change or production apply.

The Cloudflare route change readiness and manual cutover approval package now
exists at
[BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md).
It documents the proposed future target `http://127.0.0.1:18000`, rollback
target `http://127.0.0.1:8000`, required pre-cutover checks, and manual
rollback plan. It does not approve Cloudflare cutover or production apply.

## Decision Matrix

| Question | Option A - Proxy Takes 8000 | Option B - Cloudflare Targets New Proxy Port |
| --- | --- | --- |
| Cloudflare config change required | No | Yes |
| Local port `8000` ownership change required | Yes | No during preparation |
| Can current `web` stay untouched during preparation | No, not for final takeover | Yes |
| Rollback complexity | Local port/proxy rollback | Cloudflare route target rollback |
| Risk to both tickets/shopify | Yes, both share the same `8000` origin | Yes, both routes must be edited consistently |
| Testing confidence before cutover | Lower until proxy owns `8000` | Higher because proxy can be tested on a new port |
| Recommended first production approach | No | Yes, conservative default |

## Manual Decision Fields

- chosen option:
- chosen proxy local port:
- Cloudflare approver:
- tickets route current target:
- shopify route current target:
- proposed new target:
- rollback target:
- observation window:
- final approval owner:

## Go / No-Go

- Option comparison: READY after review.
- Option B route plan: READY after review at
  [BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md](BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md).
- Cloudflare cutover approval package: READY after review at
  [BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md).
- Proposed Option B proxy port: `18000`, NOT FINAL.
- `18000` candidate validation: PASSED.
- `18000` candidate route: PASSED.
- Final runtime rehearsal: PASSED.
- Chosen option: NOT YET.
- Cloudflare cutover: NOT APPROVED.
- Cloudflare change: NOT APPROVED.
- `8000` takeover: NOT APPROVED.
- Production apply: NO-GO.
- Next required step: final manual Cloudflare cutover checklist / operator
  approval.

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
- The candidate files keep Option B in design-only status. They do not change
  Cloudflare, do not take over host port `8000`, and do not enable production
  apply.
- Current Cloudflare routes for `tickets.kidstoyloverapps.com` and
  `shopify.kidstoyloverapps.com` remain `http://127.0.0.1:8000`.
- Cloudflare route change: NOT APPROVED.
- Host port `8000` takeover: NOT APPROVED.
- Production apply remains NO-GO.
- Final runtime rehearsal: PASSED.
- Next required step: final manual Cloudflare cutover checklist / operator
  approval.
- Future cutover requires manual Cloudflare edit and rollback plan review at
  [BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md).

## Final Manual Checklist Link

- Final manual Cloudflare cutover checklist exists at
  [BLUE_GREEN_MANUAL_CLOUDFLARE_CUTOVER_CHECKLIST.md](BLUE_GREEN_MANUAL_CLOUDFLARE_CUTOVER_CHECKLIST.md).
- Manual cutover checklist: READY after review.
- Approval phrase is documentation-only:
  `I_APPROVE_MANUAL_CLOUDFLARE_CUTOVER_TO_18000_AFTER_FINAL_REHEARSAL`.
- No script should accept the phrase yet.
- Cloudflare cutover remains NOT APPROVED.
- Production apply remains NO-GO.
- Final manual cutover requires operator approval before any Cloudflare route
  edit.
