# Blue-Green Production Traffic Path Audit

## Scope

This is a read-only audit of the current production traffic path and proxy
ownership questions for future blue-green apply planning.

Audit date: 2026-05-19.

The manual external routing decision package is documented in
[BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md).
It records the routing options and checklist required before any production
blue-green proxy apply. External routing is NOT YET confirmed, and production
apply remains NO-GO.

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
- External domain routing: DNS is Cloudflare-fronted and Cloudflare Access is
  in front of unauthenticated `/healthz/`, but the origin path from Cloudflare
  to the app was not proven. A running local `cloudflared` service exists, but
  its service target was not inspected because command lines and tunnel config
  can contain secret tokens. The domain may reach the app through a tunnel,
  direct host routing, or another external proxy outside this repository.
  Manual confirmation is required.
- No Cloudflare/domain routing change is approved by this audit or by the
  external routing decision package.
- No host port `8000` ownership change is approved by this audit or by the
  external routing decision package.

## Current Production Risk

- If production traffic reaches the current `web` service through host port
  `8000`, the single-container restart downtime risk remains.
- If an external reverse proxy or Cloudflare tunnel is already involved, its
  ownership, config path, reload command, and rollback command are unknown from
  repository evidence and must be confirmed manually.
- The audit supports the current design assumption that local app traffic is
  available on `8000`, but it does not prove the full public traffic path
  because Docker runtime listing was blocked and external HTTPS reaches
  Cloudflare Access rather than the app health body.

## Blue-Green Insertion Options

### Option A: Future `bluegreen_proxy` Owns Port 8000

Introduce a production `bluegreen_proxy` service in a future explicitly
approved apply. The proxy would take over host port `8000` and route to
`web_blue` or `web_green`.

This keeps the public host port stable, but the first proxy takeover is itself
a runtime-changing production task and may require a planned maintenance
window, exact rollback command, and deployment lock enforcement.

### Option B: Keep Current Port 8000 Until One-Time Proxy Takeover

Continue leaving current `web` on `8000` until a separate one-time proxy
takeover task is reviewed and approved.

This avoids changing the current path during command design, but production
blue-green apply cannot become real until port ownership or external routing
is resolved.

### Option C: Switch At An External Proxy If One Exists

If production already uses an external reverse proxy or Cloudflare tunnel
target outside Docker Compose, switch upstreams there only after a separate
review identifies the exact config path, switch/reload command, rollback
command, and traffic impact.

This avoids a Docker port takeover, but it requires proof of current external
proxy ownership and an approved no-secret operational procedure.

## Required Manual Decisions

- In Cloudflare DNS, is `tickets.kidstoyloverapps.com` a proxied DNS record,
  a CNAME/public hostname backed by Cloudflare Tunnel, or another route type?
- In Cloudflare Zero Trust / Tunnels, what tunnel name and public hostname
  entry serve `tickets.kidstoyloverapps.com`, if any?
- What exact service target is configured for that public hostname:
  `http://127.0.0.1:8000`, `http://localhost:8000`, another local port, or an
  external proxy?
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

## Recommended Next Path

Recommended next path: manual Cloudflare dashboard check fields to fill.

The audit found a running local `cloudflared` service, but did not prove that
Cloudflare Tunnel targets local `8000`. It also found Cloudflare Access in
front of unauthenticated `/healthz/`. Because the origin path is still
insufficiently evidenced, do not choose tunnel-origin blue-green, external
proxy upstream switching, or one-time local proxy takeover yet.

After the manual fields identify the exact origin target, choose the matching
implementation path in a separate reviewed task. Production apply remains
NO-GO.

## Go / No-Go

- Traffic path audit: READY after review.
- External routing decision package: READY after review at
  [BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md).
- External routing confirmed: NOT YET.
- Production proxy switch implementation: NOT READY.
- Production runtime execution: NOT ENABLED.
- Production apply: NO-GO.

Next required step: manually confirm the current Cloudflare/origin/proxy path
and choose the production port/proxy ownership model before implementing any
real blue-green runtime command.
