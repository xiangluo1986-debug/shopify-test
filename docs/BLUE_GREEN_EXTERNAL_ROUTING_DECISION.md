# Blue-Green External Routing Decision

## Purpose

Record the manual decision required for external routing before any production
blue-green proxy apply.

This document does not approve production apply. It does not deploy, start or
stop containers, reload proxy, switch traffic, change Cloudflare/domain routing,
write active-color state, or modify production runtime configuration.

Production remains NO-GO.

## Known Facts From Audit

- Local port `8000` is served by the Docker web path.
- Active Compose exposes `web` with host port `8000` mapped to container port
  `8000`.
- No active proxy service was found in `docker-compose.yml`.
- `tickets.kidstoyloverapps.com` is behind Cloudflare.
- The exact Cloudflare, origin, or tunnel path is not confirmed.
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

## Recommended Conservative Decision

- Do not change Cloudflare or domain routing yet.
- Do not let `bluegreen_proxy` take host port `8000` yet.
- First manually confirm the exact external origin path.
- Require separate approval before any Cloudflare/domain routing change.
- Require separate approval before any host port `8000` ownership change.
- Production apply remains NO-GO until the external routing path is confirmed.

## Manual Checklist

- Cloudflare mode:
- Tunnel name if any:
- Origin hostname/IP:
- Origin port:
- Current target service:
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
