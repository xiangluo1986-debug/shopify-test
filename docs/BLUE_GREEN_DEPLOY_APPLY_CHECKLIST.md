# Blue-Green Deploy Apply Checklist

This checklist is for a future reviewed apply task only. Do not use it to
switch production traffic, restart production, run migrations, or change
Cloudflare routing until that task is explicitly approved.

Related non-active drafts:

- [docker-compose.bluegreen.example.yml](../docker-compose.bluegreen.example.yml)
- [nginx/bluegreen.example.conf](../nginx/bluegreen.example.conf)
- [BLUE_GREEN_DEPLOY_PLAN.md](BLUE_GREEN_DEPLOY_PLAN.md)
- [BLUE_GREEN_DEPLOY_DECISIONS.md](BLUE_GREEN_DEPLOY_DECISIONS.md)

## Preconditions Before Applying

- Current single-web deployment is healthy through `/healthz/`.
- Active `docker-compose.yml` behavior is understood and still unchanged.
- All manual decisions in
  [BLUE_GREEN_DEPLOY_DECISIONS.md](BLUE_GREEN_DEPLOY_DECISIONS.md) are marked
  with approved choices before any apply command is run.
- A reviewed proxy design is selected and tested away from production traffic.
- The active color source of truth is documented and recoverable.
- Database backup and restore process is confirmed for the production database.
- Any migrations are reviewed for backward compatibility before they run.
- Static and media file handling is confirmed for two web containers.
- Scheduler behavior is reviewed so only one scheduler instance runs.
- Cloudflare or external routing changes are reviewed without exposing tokens.
- Rollback authority and communication path are assigned before the switch.

## Required Manual Decisions

Before applying, update
[BLUE_GREEN_DEPLOY_DECISIONS.md](BLUE_GREEN_DEPLOY_DECISIONS.md) so every
decision has an approved choice, approver, and date. Pending decisions mean
NO-GO for active apply work.

- Proxy technology: nginx, Caddy, Traefik, HAProxy, or existing host proxy.
- Active color tracking: config include, state file, label, checklist, or script.
- Port ownership: whether the proxy takes host port `8000` or external routing
  moves to a different local proxy port.
- Cloudflare/external routing impact: tunnel target, DNS/proxy behavior, and
  any planned maintenance window.
- Migration compatibility rules: expand/contract sequencing, old-code/new-code
  overlap, and rollback limits.
- Static/media handling: shared volume, host mount, collectstatic process, and
  upload/media consistency.
- Scheduler handling: singleton scheduler update timing and rollback behavior.
- Rollback authority: who can switch back, when to decide, and how long to keep
  the previous color running.

## Future Apply Flow

1. Confirm the current active color and record it in the approved tracking
   location.
2. Build or start only the inactive color.
3. Run `python manage.py check` against the inactive color.
4. Run migrations only when they are reviewed as safe for both old and new code.
5. Run any approved static asset step without disrupting the active color.
6. Check the inactive color directly through `/healthz/`.
7. Run any agreed smoke tests against the inactive color.
8. Switch the proxy from the old active color to the inactive healthy color.
9. Check public `/healthz/` through the stable domain or routing path.
10. Monitor web and proxy logs during the observation window.
11. Keep the previous color running until rollback is no longer needed.
12. Stop or recycle the previous color only after the observation window passes.

## Do Not Run Yet

These actions are not approved by this checklist alone:

- Starting blue/green services in production.
- Moving host port `8000` from `web` to a proxy.
- Changing Cloudflare tunnel targets or public routing.
- Running migrations.
- Reloading or replacing production proxy configuration.
- Switching traffic between colors.
- Stopping the previous active color.

## Rollback Steps

1. If inactive color validation fails before the switch, do not switch traffic.
2. If errors appear after the switch, change the proxy back to the previous
   active color.
3. Confirm public `/healthz/` through the stable routing path.
4. Keep the failed color available for log inspection when it is safe to do so.
5. Do not attempt automatic database rollback.
6. If migrations were involved, follow the reviewed database backup/restore plan.
7. Record the final active color and the reason for rollback.

## Validate Without Changing Traffic

- Run the read-only planner:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_deploy_dry_run.ps1
```

- Validate draft Compose syntax without starting containers:

```powershell
docker compose -f docker-compose.bluegreen.example.yml config
```

- Review the example proxy config manually. It is not active and should not be
  copied into production without a separate apply task.
- Confirm the active Compose file still has one `web` service and no active
  proxy service.

## Existing Commands

Current commands remain unchanged until a future apply task is approved:

```powershell
docker compose up -d web
.\scripts\safe_deploy.ps1
```

The draft files do not change runtime behavior by existing commands because
they are separate examples and are not referenced by `docker-compose.yml`.
