# Blue-Green External Routing Decision

## Purpose

Record the manual decision required for external routing before any production
blue-green proxy apply.

This document does not approve production apply. It does not deploy, start or
stop containers, reload proxy, switch traffic, change Cloudflare/domain routing,
write active-color state, or modify production runtime configuration.

Production remains NO-GO.

## Known Facts From Audit

- External routing origin audit addendum date: 2026-05-19.
- Local port `8000` is served by the Docker web path.
- `http://127.0.0.1:8000/healthz/` returned HTTP 200 with app body `OK`.
- `netstat` found `0.0.0.0:8000` listening, owned at audit time by
  `com.docker.backend.exe` (`C:\Program Files\Docker\Docker\resources\com.docker.backend.exe`).
- `Get-NetTCPConnection` returned no matches for `80`, `443`, or `8000`, so
  `netstat` was used as the listener cross-check.
- No local `80` or `443` listener was found in the narrowed listening-port
  check.
- Active Compose exposes `web` with host port `8000` mapped to container port
  `8000`.
- No active proxy service was found in `docker-compose.yml`.
- `tickets.kidstoyloverapps.com` is behind Cloudflare.
- DNS returned Cloudflare A records `172.67.132.69` and `104.21.4.166`, plus
  Cloudflare AAAA records.
- A Windows `Cloudflared` service was found running with automatic start, and
  a `cloudflared` process was running.
- No nginx, Caddy, Traefik, HAProxy, or app-specific reverse proxy service or
  process was found by name. Windows built-in `SstpSvc` and
  `WinHttpAutoProxySvc` matched generic tunnel/proxy search terms, but they do
  not prove an app reverse proxy.
- Unauthenticated `https://tickets.kidstoyloverapps.com/healthz/` returned
  HTTP 200 from Cloudflare with a Cloudflare Access sign-in HTML page, not the
  app `OK` health response.
- The exact Cloudflare, origin, or tunnel path is not confirmed. The
  `cloudflared` target was not inspected because service command lines and
  tunnel config can contain secret tokens.
- No secret, token, credential, private environment, quick start, or tunnel
  token files were inspected.

Source audit:
[BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md](BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md).

## Unknowns To Manually Confirm

- Is `tickets.kidstoyloverapps.com` using Cloudflare proxy DNS only?
- Is it using Cloudflare Tunnel?
- Is there an external reverse proxy outside Docker?
- Does external traffic hit host port `8000` directly?
- Is any firewall or NAT forwarding `443` or `80` to `8000`?
- Where is the Cloudflare origin configured?
- If a tunnel exists, what local service and port does it target?
- Does Cloudflare Access intentionally protect `/healthz/`, or should a
  health-check bypass rule exist for this endpoint?
- Who controls Cloudflare settings?
- What change would be needed for `bluegreen_proxy` to take traffic?

## Routing Options

### Option A - Proxy Owns 8000 In Future

`bluegreen_proxy` eventually takes host port `8000`.

The current `web` service no longer binds host port `8000` directly.

This keeps the local origin port stable, but it requires one-time cutover
approval because it changes local port ownership.

Risk: port `8000` ownership moves from the current Docker web path to the
future proxy path.

### Option B - External Proxy Or Tunnel Points To New Proxy Port

Keep current `web` on host port `8000` until an external routing change is
approved.

`bluegreen_proxy` listens on another local port, and Cloudflare, tunnel, or
external proxy origin routing changes later.

This avoids immediate `8000` ownership change, but it requires separate
Cloudflare, tunnel, or external routing approval.

### Option C - Existing External Proxy Switches Upstream

If an external nginx, proxy, tunnel, or platform-level router exists outside
Compose, configure the blue/green upstream switch there.

This requires finding the exact config path, switch or reload command, rollback
command, owner, and maintenance impact before any production apply.

## Recommended Safest Next Path

Recommended next path: manual Cloudflare dashboard check fields to fill.

Reason: the audit found Cloudflare DNS, a running local `cloudflared` service,
and Docker ownership of local `8000`, but did not prove that the tunnel targets
local `8000`. It also found that unauthenticated external `/healthz/` reaches
Cloudflare Access rather than the app health response. That is insufficient
evidence for a tunnel-origin blue-green design, an external proxy upstream
switch design, or a one-time local proxy takeover design.

Required manual checks, without exposing secrets:

- In Cloudflare DNS, confirm whether `tickets.kidstoyloverapps.com` is proxied
  DNS to an origin, a CNAME to a tunnel, or another route type.
- In Cloudflare Zero Trust / Tunnels, confirm the tunnel name, public hostname,
  and service target for `tickets.kidstoyloverapps.com`.
- Confirm whether the target is `http://127.0.0.1:8000`,
  `http://localhost:8000`, another local port, or an external proxy.
- Confirm whether Cloudflare Access intentionally protects `/healthz/`.
- Confirm the exact owner who can approve any Cloudflare, tunnel, origin, or
  local port ownership change.

- Do not change Cloudflare or domain routing yet.
- Do not let `bluegreen_proxy` take host port `8000` yet.
- First manually confirm the exact external origin path.
- Require separate approval before any Cloudflare/domain routing change.
- Require separate approval before any host port `8000` ownership change.
- Production apply remains NO-GO until the external routing path is confirmed.

## Manual Checklist

- Cloudflare mode:
- Tunnel name if any:
- Tunnel public hostname entry:
- Tunnel service target:
- Origin hostname/IP:
- Origin port:
- Current target service:
- Cloudflare Access applies to `/healthz/`:
- External proxy exists:
- Proxy config path:
- Reload command:
- Who can approve routing change:
- Rollback routing command:

## Go / No-Go

- External routing decision package: READY after review.
- External routing confirmed: NOT YET.
- Production proxy switch implementation: NOT READY.
- Production apply: NO-GO.

Next required step: manually confirm the Cloudflare, origin, tunnel, and proxy
path without exposing secrets, then choose whether a future production
blue-green path changes host port `8000` ownership or external routing.
