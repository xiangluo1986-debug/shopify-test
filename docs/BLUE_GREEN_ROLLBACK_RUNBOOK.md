# Blue-Green Rollback Runbook

## Purpose

This runbook describes the manual rollback path if the post-cutover
`18000` candidate route becomes unsafe.

This is documentation only. It does not change Cloudflare routes, start or
stop containers, restart containers, rebuild images, deploy code, run
migrations, run collectstatic, reload proxy configuration, switch traffic,
write active-color state, call Shopify APIs, call Gmail APIs, or send email.

## Current Route And Rollback Target

- Current Cloudflare target for both tickets and shopify:
  `http://127.0.0.1:18000`.
- Current production path:

```text
Cloudflare Tunnel
  -> 127.0.0.1:18000
  -> bluegreen_proxy_candidate
  -> web_blue / web_green
```

- Manual rollback target: `http://127.0.0.1:8000`.
- Keep `bluegreen_proxy_candidate`, `web_blue`, and `web_green` running while
  diagnosing unless a later explicit task approves runtime changes.
- Keep the old `8000` path running.

## When To Roll Back

Roll back when customer-facing risk is higher on the `18000` path than on the
`8000` path, for example:

- `http://127.0.0.1:18000/healthz/` fails repeatedly while
  `http://127.0.0.1:8000/healthz/` passes.
- Tickets or shopify public pages return repeated `500` errors after cutover.
- The proxy returns repeated `502` or upstream errors.
- `bluegreen_proxy_candidate` exits or enters a restart loop.
- Either `web_blue` or `web_green` is unhealthy and the proxy cannot reliably
  serve the active path.
- The operator cannot quickly determine whether the candidate path is safe.

Do not roll back automatically. Use the manual rollback only after confirming
the issue and preserving enough sanitized evidence for follow-up diagnosis.

## Pre-Rollback Checks

Safe local checks:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:18000/healthz/" -UseBasicParsing
Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz/" -UseBasicParsing
docker ps
docker compose ps
```

Record:

- Timestamp.
- Which hostname failed.
- Which path failed.
- HTTP status or error class.
- Whether `18000 /healthz/` passed.
- Whether `8000 /healthz/` passed.
- Candidate service status.

Do not record secrets, cookies, tokens, customer personal data, ticket bodies,
addresses, phone numbers, or full raw customer emails.

## Manual Cloudflare Rollback

Manual operator action:

1. Open the Cloudflare Tunnel Published application route settings for the
   tickets hostname.
2. Change the service target from `http://127.0.0.1:18000` back to
   `http://127.0.0.1:8000`.
3. Open the matching route settings for the shopify hostname.
4. Change the service target from `http://127.0.0.1:18000` back to
   `http://127.0.0.1:8000`.
5. Save the route changes.
6. Do not change tunnel tokens, domain ownership, DNS records, or unrelated
   Cloudflare settings.

No Cloudflare API call is part of this runbook.

## Post-Rollback Checks

After the manual route change:

1. Check `http://127.0.0.1:8000/healthz/`.
2. Check the tickets hostname manually.
3. Check the shopify hostname manually.
4. Confirm the customer-facing error has stopped.
5. Preserve sanitized evidence from before and after rollback.
6. Keep the `18000` candidate services available for follow-up diagnosis
   unless a separate approved task decides otherwise.

Safe local check:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz/" -UseBasicParsing
```

Optional diagnostic check after traffic is safe:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:18000/healthz/" -UseBasicParsing
```

## What Not To Do During Rollback

Do not:

- Stop, restart, rebuild, or redeploy `bluegreen_proxy_candidate`,
  `web_blue`, or `web_green`.
- Stop the old `8000` path.
- Run `docker compose up`, `docker compose down`, `docker compose restart`, or
  image build commands.
- Run migrations.
- Run collectstatic.
- Reload proxy configuration.
- Switch active color.
- Write active-color state.
- Remove containers, volumes, logs, media, uploads, or database files.
- Run destructive Git commands.
- Stage, commit, or push logs.
- Call Shopify, Gmail, Trustpilot, Kudosi, Ali Reviews, or other external
  write APIs.

## Evidence Preservation

Preserve evidence locally for diagnosis, but do not commit generated logs.

Useful evidence:

- Sanitized timestamps and HTTP statuses.
- Which route target was active.
- Candidate service status.
- Whether `18000 /healthz/` and `8000 /healthz/` passed.
- Short sanitized error summaries.

Avoid:

- Secrets, tokens, API keys, cookies, private environment values, customer
  addresses, phone numbers, ticket bodies, full raw customer emails, database
  passwords, or Django secret values.
- Committing files under `logs/`.

## Follow-Up After Rollback

After rollback is stable:

- Keep `8000` as the active target until the candidate issue is understood.
- Review proxy, color service, and app health evidence.
- Update the hardening plan with the root cause and prevention item.
- Do not re-cut over to `18000` without a separate reviewed task and manual
  approval.
