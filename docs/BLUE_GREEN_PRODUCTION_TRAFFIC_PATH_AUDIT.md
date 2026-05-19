# Blue-Green Production Traffic Path Audit

## Scope

This is a read-only audit of the current production traffic path and proxy
ownership questions for future blue-green apply planning.

Audit date: 2026-05-19.

The manual external routing decision package is documented in
[BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md).
It records the confirmed Cloudflare Tunnel Published application route targets
and the routing options required before any production blue-green proxy apply.
Production apply remains NO-GO.

The dedicated Option A versus Option B comparison is documented in
[BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md](BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md).
It recommends Option B as the conservative direction for the first production
transition, but the chosen option is still NOT YET and Cloudflare changes
require separate approval.

The no-action Option B Cloudflare route change and rollback plan is documented
in
[BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md](BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md).
It proposes `18000` as a placeholder proxy port only; the port is not final,
Cloudflare change is not approved, and production apply remains NO-GO.

This audit did not deploy, build images, start containers, stop containers,
restart containers, run migrations, run collectstatic, reload proxy, switch
traffic, write active-color state, change Cloudflare/domain routing, modify
active Compose files, modify production proxy configuration, call Shopify APIs,
call Gmail APIs, send email, or affect ticket, review request, translation,
settlement, Trustpilot, Kudosi, or Ali Reviews workflows.

## Read-Only Evidence

- `git status --short --branch` showed branch `main...origin/main` with
  unrelated untracked task files already present.
- `docker compose ps` and `docker ps` could not be inspected from this shell
  because Docker Desktop API access returned permission errors.
- `docker compose config --no-interpolate --services` showed active Compose
  services `db`, `web`, and `scheduler`.
- The non-interpolated Compose port view showed `web` publishes host port
  `8000` to container port `8000`.
- No active Compose service named nginx, proxy, caddy, traefik, haproxy, or
  `bluegreen_proxy` was found in the active Compose service list.
- Current host listener checks showed `0.0.0.0:8000` listening and owned by
  Docker Desktop plumbing: `com.docker.backend.exe`
  (`C:\Program Files\Docker\Docker\resources\com.docker.backend.exe`) at audit
  time.
- `Get-NetTCPConnection` returned no rows for `80`, `443`, or `8000`, but
  `netstat` confirmed the `8000` listener. The discrepancy is recorded as a
  tooling observation, not as proof that `8000` is absent.
- No local `80` or `443` listener was found in the narrowed listening-port
  check.
- `http://127.0.0.1:8000/healthz/` returned HTTP 200 with body `OK`.
- `http://127.0.0.1:18080/healthz/` and
  `http://127.0.0.1:19080/healthz/` were not serving.
- Windows service/process discovery found a running `Cloudflared` service with
  automatic start and a running `cloudflared` process.
- Manual Cloudflare One / Zero Trust check confirmed tunnel
  `aftersales-ticket`, type `cloudflared`, status HEALTHY.
- Cloudflare Published application route
  `tickets.kidstoyloverapps.com` targets `http://127.0.0.1:8000`.
- Cloudflare Published application route
  `shopify.kidstoyloverapps.com` targets `http://127.0.0.1:8000`.
- The Cloudflare hostname routes tab has no hostname routes.
- External access is using Published application routes, not hostname routes.
- Both tickets and shopify routes share the same local
  `http://127.0.0.1:8000` origin target.
- No Cloudflare setting was changed.
- No nginx, Caddy, Traefik, HAProxy, or app-specific reverse proxy service or
  process was found by name. `SstpSvc` and `WinHttpAutoProxySvc` appeared only
  because the search included generic tunnel/proxy terms; they are Windows
  built-in services and do not prove app routing.
- DNS for `tickets.kidstoyloverapps.com` resolved to Cloudflare A and AAAA
  addresses: A `172.67.132.69`, A `104.21.4.166`, and Cloudflare IPv6
  addresses.
- PowerShell and `curl.exe` had local TLS/client failures for
  `https://tickets.kidstoyloverapps.com/healthz/`, so a Python HTTPS read was
  used as a sanitized cross-check.
- The Python HTTPS read returned HTTP 200 from `server=cloudflare` with a
  `cf-ray` header and a Cloudflare Access sign-in HTML page. It did not return
  the app `OK` health response, so unauthenticated external `/healthz/` does
  not prove the Cloudflare-to-origin path.
- Repository proxy/tunnel indicators found only non-active blue-green examples
  and documentation, including:
  `docker-compose.bluegreen.proxy-validation.example.yml`,
  `docker-compose.bluegreen.proxy-test.example.yml`,
  `nginx/bluegreen.example.conf`,
  `nginx/bluegreen.local-test.example.conf`, and
  `docs/BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md`.
- Project documentation notes that `quick start.txt` contains a cloudflared
  startup pattern, but this audit did not inspect that file because it may
  contain private tunnel details.

## Current Traffic Path Summary

- Current host port `8000` owner: Docker Desktop host networking processes were
  listening on port `8000` during the audit; the current observed owner was
  `com.docker.backend.exe`.
- Docker service mapping `8000`: active Compose declares `web` with
  `8000:8000`.
- Live container ownership: not proven from Docker runtime commands because
  Docker API access was blocked by permission errors.
- Active Compose proxy service: none found.
- Repository proxy artifacts: example-only nginx and proxy validation files
  exist, but they are not active production runtime configuration.
- Local `80`/`443`: no listening local server was confirmed on either port.
- External domain routing: Cloudflare Tunnel Published application routes for
  both `tickets.kidstoyloverapps.com` and `shopify.kidstoyloverapps.com`
  target `http://127.0.0.1:8000`. The hostname routes tab is empty. External
  access is using Published application routes, not hostname routes.
- Cloudflare Access is in front of unauthenticated `/healthz/`; that access
  policy behavior was observed but not changed.
- No Cloudflare/domain routing change is approved by this audit or by the
  external routing decision package.
- No host port `8000` ownership change is approved by this audit or by the
  external routing decision package.

## Current Production Risk

- If production traffic reaches the current `web` service through host port
  `8000`, the single-container restart downtime risk remains.
- Because both public hostnames share `http://127.0.0.1:8000`, a future route
  change or local proxy takeover affects both tickets and shopify entry points.
- The audit supports the current design assumption that local app traffic is
  available on `8000`. Cloudflare Access still prevents unauthenticated public
  `/healthz/` from proving the app body through the external URL.

## Blue-Green Insertion Options

### Option A: Future `bluegreen_proxy` Owns Port 8000

Introduce a production `bluegreen_proxy` service in a future explicitly
approved apply. The proxy would take over host port `8000` and route to
`web_blue` or `web_green`.

This keeps the public host port stable, but the first proxy takeover is itself
a runtime-changing production task and may require a planned maintenance
window, exact rollback command, and deployment lock enforcement.

### Option B: Cloudflare Published Routes Point To New Proxy Port

Continue leaving current `web` on `8000` and run `bluegreen_proxy` on a new
local port until a separate Cloudflare route edit task is reviewed and
approved.

This avoids local `8000` ownership change, but it changes the Cloudflare
Published application route service target for both tickets and shopify.

### Option C: Switch At An External Proxy If One Exists

If production already uses an external reverse proxy or Cloudflare tunnel
target outside Docker Compose, switch upstreams there only after a separate
review identifies the exact config path, switch/reload command, rollback
command, and traffic impact.

This avoids a Docker port takeover, but it requires proof of current external
proxy ownership and an approved no-secret operational procedure.

## Required Manual Decisions

- Should `bluegreen_proxy` eventually take local `8000` while Cloudflare
  Published application routes stay on `http://127.0.0.1:8000`?
- Or should `bluegreen_proxy` run on a new local port and both Cloudflare
  Published application route service targets change to that port?
- Does Cloudflare Access intentionally protect `/healthz/`, or should that
  endpoint have a health-check bypass rule?
- Is there an external reverse proxy outside `docker-compose.yml`?
- What is the exact production proxy or tunnel config path, if safe to
  identify without exposing tokens?
- What exact reload/switch command should be used?
- What exact rollback command should be used?
- Should `bluegreen_proxy` own host port `8000` in the future production path,
  or should an existing tunnel/proxy switch upstream instead?
- What planned maintenance window, if any, is required for the first proxy
  ownership change?
- Complete the manual checklist in
  [BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md)
  before any production proxy switch implementation.
- Review the Option A versus Option B comparison in
  [BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md](BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md)
  and fill the manual decision fields before any Cloudflare route edit or
  local `8000` takeover.

## Recommended Next Path

Recommended next path: review the no-action comparison / decision package for
Option A versus Option B.

The manual Cloudflare check confirmed both Published application routes target
local `127.0.0.1:8000`, while current Docker `web` owns local `8000`. The next
decision remains whether to keep the Cloudflare target stable and move local
port ownership to `bluegreen_proxy`, or keep current local ownership and change
the Cloudflare service targets. The conservative recommendation is Option B for
the first production transition, but it is not approved yet.

Do not change Cloudflare yet. Do not take over `8000` yet. Production apply
remains NO-GO.

## Go / No-Go

- Traffic path audit: READY after review.
- External routing decision package: READY after review at
  [BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md).
- Option comparison package: READY after review at
  [BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md](BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md).
- Option B route plan: READY after review at
  [BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md](BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md).
- Proposed Option B proxy port: `18000`, NOT FINAL.
- Conservative recommendation: Option B, not approved.
- Chosen option: NOT YET.
- Cloudflare Published application route origin confirmed: YES.
- Cloudflare change: NOT APPROVED.
- `8000` takeover: NOT APPROVED.
- Production proxy switch implementation: NOT READY.
- Production runtime execution: NOT ENABLED.
- Production apply: NO-GO.

Next required step: review the Option B route plan, approve or change the
final proxy port, fill the option comparison manual decision fields, and
separately approve any future Cloudflare route edit before implementing any
real blue-green runtime command.
