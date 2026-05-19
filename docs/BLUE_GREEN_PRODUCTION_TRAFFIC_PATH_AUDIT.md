# Blue-Green Production Traffic Path Audit

## Scope

This is a read-only audit of the current production traffic path and proxy
ownership questions for future blue-green apply planning.

Audit date: 2026-05-19.

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
- Host listener checks showed port `8000` was owned by Docker Desktop plumbing:
  `com.docker.backend.exe` on wildcard addresses, with `wslrelay.exe` also
  listening on loopback IPv6 at the time of the audit.
- `http://127.0.0.1:8000/healthz/` returned HTTP 200 with body `OK`.
- DNS for `tickets.kidstoyloverapps.com` resolved to Cloudflare A and AAAA
  addresses.
- `https://tickets.kidstoyloverapps.com/healthz/` could not be verified from
  this environment. PowerShell reported the connection closed unexpectedly,
  and `curl.exe` returned HTTP status `000`.
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
  listening on port `8000` during the audit.
- Docker service mapping `8000`: active Compose declares `web` with
  `8000:8000`.
- Live container ownership: not proven from Docker runtime commands because
  Docker API access was blocked by permission errors.
- Active Compose proxy service: none found.
- Repository proxy artifacts: example-only nginx and proxy validation files
  exist, but they are not active production runtime configuration.
- External domain routing: DNS is Cloudflare-fronted, but the origin path from
  Cloudflare to the app was not proven. The domain may reach the app through a
  tunnel, direct host routing, or another external proxy outside this
  repository. Manual confirmation is required.

## Current Production Risk

- If production traffic reaches the current `web` service through host port
  `8000`, the single-container restart downtime risk remains.
- If an external reverse proxy or Cloudflare tunnel is already involved, its
  ownership, config path, reload command, and rollback command are unknown from
  repository evidence and must be confirmed manually.
- The audit supports the current design assumption that active Compose is
  still single-web on `8000`, but it does not prove the full public traffic
  path because Docker runtime listing and external HTTPS health verification
  were blocked.

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

- Should `bluegreen_proxy` own host port `8000` in the future production path?
- Is Cloudflare/domain routing currently pointing to this host on port `8000`,
  a Cloudflare tunnel, or another external proxy?
- Is there an external reverse proxy outside `docker-compose.yml`?
- What is the exact production proxy or tunnel config path?
- What exact reload/switch command should be used?
- What exact rollback command should be used?
- What planned maintenance window, if any, is required for the first proxy
  ownership change?

## Go / No-Go

- Traffic path audit: READY after review.
- Production proxy switch implementation: NOT READY.
- Production runtime execution: NOT ENABLED.
- Production apply: NO-GO.

Next required step: manually confirm the current Cloudflare/origin/proxy path
and choose the production port/proxy ownership model before implementing any
real blue-green runtime command.
