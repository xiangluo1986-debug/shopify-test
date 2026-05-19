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
- Manual Cloudflare One / Zero Trust check confirmed tunnel
  `aftersales-ticket`.
- Tunnel type: `cloudflared`.
- Tunnel status: HEALTHY.
- Published application route:
  `tickets.kidstoyloverapps.com` -> `http://127.0.0.1:8000`.
- Published application route:
  `shopify.kidstoyloverapps.com` -> `http://127.0.0.1:8000`.
- Hostname routes tab has no hostname routes.
- External access is using Cloudflare Tunnel Published application routes, not
  hostname routes.
- This confirms the current tunnel origin target is local
  `127.0.0.1:8000`.
- No Cloudflare setting was changed.
- No nginx, Caddy, Traefik, HAProxy, or app-specific reverse proxy service or
  process was found by name. Windows built-in `SstpSvc` and
  `WinHttpAutoProxySvc` matched generic tunnel/proxy search terms, but they do
  not prove an app reverse proxy.
- Unauthenticated `https://tickets.kidstoyloverapps.com/healthz/` returned
  HTTP 200 from Cloudflare with a Cloudflare Access sign-in HTML page, not the
  app `OK` health response.
- No secret, token, credential, private environment, quick start, or tunnel
  token files were inspected.

Source audit:
[BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md](BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md).

## Updated Routing Interpretation

- External app traffic reaches local `8000` through Cloudflare Tunnel
  Published application routes.
- Current Docker `web` owns local `8000`.
- Both `tickets.kidstoyloverapps.com` and `shopify.kidstoyloverapps.com`
  share the same `http://127.0.0.1:8000` origin target.
- Future blue-green production routing must account for both hostnames sharing
  that origin.
- Cloudflare Access behavior for unauthenticated `/healthz/` is still a
  separate access-policy question; it was not changed in this task.

## Routing Options

### Option A - Proxy Owns 8000 In Future

`bluegreen_proxy` eventually takes host port `8000`.

The current `web` service no longer binds host port `8000` directly.

Cloudflare Published application routes stay pointing to
`http://127.0.0.1:8000`.

This keeps the Cloudflare service target stable, but it requires one-time local
port ownership cutover approval.

Risk: port `8000` ownership moves from the current Docker web path to the
future proxy path.

### Option B - Cloudflare Routes Point To New Proxy Port

Keep current `web` on host port `8000` until a Cloudflare route edit is
approved.

`bluegreen_proxy` runs on a new local port.

Cloudflare Published application route service targets for both
`tickets.kidstoyloverapps.com` and `shopify.kidstoyloverapps.com` change from
`http://127.0.0.1:8000` to the approved `bluegreen_proxy` port.

This avoids immediate local `8000` ownership change, but it requires separate
Cloudflare route edit approval.

Risk: Cloudflare Published application route service target changes.

## Recommended Safest Next Path

- Do not change Cloudflare or domain routing yet.
- Do not let `bluegreen_proxy` take host port `8000` yet.
- Create a no-action comparison / decision package for Option A vs Option B.
- Require separate approval before any Cloudflare/domain routing change.
- Require separate approval before any host port `8000` ownership change.
- Production apply remains NO-GO.

## Manual Checklist

- Cloudflare mode: Cloudflare Tunnel Published application routes.
- Tunnel name if any: `aftersales-ticket`
- Tunnel public hostname entry:
  - `tickets.kidstoyloverapps.com` -> `http://127.0.0.1:8000`
  - `shopify.kidstoyloverapps.com` -> `http://127.0.0.1:8000`
- Tunnel service target: `http://127.0.0.1:8000`
- Origin hostname/IP: `127.0.0.1`
- Origin port: `8000`
- Current target service: current Docker `web`
- Cloudflare Access applies to `/healthz/`:
- External proxy exists:
- Proxy config path:
- Reload command:
- Who can approve routing change:
- Rollback routing command:

## Go / No-Go

- External routing decision package: READY after review.
- Cloudflare Published application route origin confirmed: YES.
- Production proxy switch implementation: NOT READY.
- Production apply: NO-GO.

Next required step: create a no-action Option A vs Option B comparison package
covering local `8000` proxy takeover versus Cloudflare Published application
route service target changes for both hostnames.
