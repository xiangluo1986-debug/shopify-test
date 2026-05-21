# Blue-Green Long-Term Operations

## Purpose

This document describes daily and weekly operations for the aftersales
blue-green production path after Cloudflare was manually changed to target
`http://127.0.0.1:18000`.

This is documentation only. It does not deploy, restart, rebuild, switch
traffic, change Cloudflare routes, run migrations, run collectstatic, reload
proxy configuration, write active-color state, call Shopify APIs, call Gmail
APIs, or send email.

## Current Runtime Model

Current production traffic path:

```text
Cloudflare Tunnel
  -> 127.0.0.1:18000
  -> bluegreen_proxy_candidate
  -> web_blue / web_green
```

Rollback target:

```text
http://127.0.0.1:8000
```

Services that must remain running:

- `bluegreen_proxy_candidate`
- `web_blue`
- `web_green`

The old `8000` path must remain available until a separate cleanup task is
reviewed and explicitly approved.

## Daily Checks

Daily read-only checks during the observation period:

- Check `http://127.0.0.1:18000/healthz/`.
- Check `http://127.0.0.1:8000/healthz/`.
- Confirm `bluegreen_proxy_candidate`, `web_blue`, and `web_green` are
  running.
- Manually spot-check tickets and shopify pages.
- Review whether any repeated `500`, `502`, or health check failures were
  observed.
- Confirm no one removed the `8000` rollback path.

Safe commands:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:18000/healthz/" -UseBasicParsing
Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz/" -UseBasicParsing
docker ps
docker compose ps
```

## Weekly Checks

Weekly read-only checks:

- Confirm the rollback runbook still matches the Cloudflare route model.
- Confirm the hardening plan has owners for monitoring, restart policy, and
  formal proxy service work.
- Confirm `8000` cleanup is still blocked until explicit approval.
- Confirm future deploy work still uses the deployment lock requirement.
- Review sanitized incident notes for repeated page failures or health check
  failures.
- Review whether the candidate proxy should be formalized or renamed in a
  separate implementation task.
- Review the formalization plan before any service rename, restart policy
  change, proxy reload, active-color state write, or real apply task.
- Review the autoreload stabilization plan before any runtime command change
  for `web_blue` or `web_green`.

## Safe Status Commands

These commands are read-only status checks in this operations context:

```powershell
docker ps
docker compose ps
Invoke-WebRequest -Uri "http://127.0.0.1:18000/healthz/" -UseBasicParsing
Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz/" -UseBasicParsing
git status --short --branch
git diff --check
git diff --cached --name-only
```

Log inspection can be useful, but logs must not be committed and must not
expose secrets or customer personal data in documentation.

## Dangerous Commands

Do not run these during routine operations:

```powershell
docker compose down -v
docker volume rm
docker system prune
python manage.py flush
```

Do not run runtime-changing commands without a separate approved task and the
deployment lock:

```powershell
docker compose up
docker compose restart
docker compose build
docker compose stop
docker compose start
docker compose run
docker compose exec -T web python manage.py migrate
docker compose exec -T web python manage.py collectstatic --noinput
```

Do not run destructive Git commands such as reset, restore, checkout, clean,
or rebase unless the user explicitly asks for that exact operation.

## Debugging If Tickets Or Shopify Fails

First isolate where the failure is:

1. Check `http://127.0.0.1:18000/healthz/`.
2. Check `http://127.0.0.1:8000/healthz/`.
3. Check candidate services with `docker ps` or `docker compose ps`.
4. Determine whether tickets, shopify, or both are affected.
5. Determine whether only public pages fail or `/healthz/` also fails.

Interpretation:

- `18000` fails and `8000` passes: candidate path, proxy, or color service is
  suspect. Use [BLUE_GREEN_ROLLBACK_RUNBOOK.md](BLUE_GREEN_ROLLBACK_RUNBOOK.md)
  if customer-facing failures are confirmed.
- `18000` passes and `8000` fails: rollback safety is degraded. Do not remove
  or clean up the old path; investigate `8000` separately.
- Both fail: likely broader app/runtime problem. Preserve evidence and avoid
  cleanup or deploy actions.
- Only one hostname fails: check hostname-specific route behavior and app
  path behavior before changing traffic.

## Deploy And Switch Policy

- All real deploy, switch, rollback, restart, rebuild, migration,
  collectstatic, active-color write, and cleanup actions require the
  deployment lock.
- If the deployment lock already exists, the second deploy or runtime task
  must stop and require a manual rerun. It must not auto-queue.
- Normal read-only checks and documentation tasks are not blocked by the
  deployment lock.
- Future blue-green deploy work must keep the previous color running through
  the observation window.
- Rollback must remain possible until a separate cleanup task is approved.

## Evidence And Commit Safety

- Do not commit logs.
- Do not stage generated runtime output.
- Do not copy secrets into docs, issues, tickets, commit messages, or chat.
- Keep incident notes sanitized: hostname, path, status code, timestamp, and
  short symptom summary are enough for most follow-up.
- Use the exact per-run `$run` path printed by any approved runner and review
  it through `scripts/review_codex_run.ps1`; do not rely on
  `latest_run_path.txt` as the primary source when multiple Codex tasks are
  running.

## Related Documents

- [BLUE_GREEN_POST_CUTOVER_OBSERVATION.md](BLUE_GREEN_POST_CUTOVER_OBSERVATION.md)
- [BLUE_GREEN_HARDENING_PLAN.md](BLUE_GREEN_HARDENING_PLAN.md)
- [BLUE_GREEN_FORMALIZATION_PLAN.md](BLUE_GREEN_FORMALIZATION_PLAN.md)
- [BLUE_GREEN_RUNTIME_AUTO_RELOAD_FIX_PLAN.md](BLUE_GREEN_RUNTIME_AUTO_RELOAD_FIX_PLAN.md)
- [BLUE_GREEN_ROLLBACK_RUNBOOK.md](BLUE_GREEN_ROLLBACK_RUNBOOK.md)
- [SAFE_DEPLOY.md](SAFE_DEPLOY.md)
- [BLUE_GREEN_DEPLOY_PLAN.md](BLUE_GREEN_DEPLOY_PLAN.md)
