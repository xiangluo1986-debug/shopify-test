# Blue-Green Runtime Autoreload Apply Package

## Purpose

Prepare a controlled future apply package to disable Django development-server
autoreload for the aftersales runtime by adding `--noreload` to the relevant
`runserver` commands.

This task does not apply changes and does not restart containers.

This package is documentation only. It does not edit runtime files, build
images, restart containers, run Docker Compose apply commands, run migrations,
run collectstatic, reload proxy configuration, switch traffic, change
Cloudflare routes, call Shopify APIs, call Gmail APIs, call
`translationsRegister`, send email, stage files, commit, or push.

## Current Runtime Scope

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

Runtime paths that must be covered by the future `--noreload` apply:

- `aftersales-web-1` / old host `8000` rollback path.
- `web_blue`.
- `web_green`.

## Read-Only Inspection Result

The active `docker-compose.yml` `web` service does not define a command
override. It publishes host port `8000` and therefore uses the image default
from `backend/Dockerfile` for the old rollback path.

Current command source for `aftersales-web-1`:

```text
backend/Dockerfile
```

Current command:

```text
CMD ["bash", "-lc", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]
```

The current production-candidate blue/green services inherit a shared command
from the `x-candidate-django-web` anchor in:

```text
docker-compose.bluegreen.proxy-candidate.example.yml
```

Current shared command for `web_blue` and `web_green`:

```text
command: bash -lc "python manage.py runserver 0.0.0.0:8000"
```

`web_blue` and `web_green` both inherit that command through:

```text
web_blue:
  <<: *candidate-django-web

web_green:
  <<: *candidate-django-web
```

## Exact Future Files To Change

A separate approved runtime-changing task would need to change only these
runtime command sources:

```text
backend/Dockerfile
docker-compose.bluegreen.proxy-candidate.example.yml
```

Do not change these files in this documentation-only package.

No `.env`, `.env.*`, token, credential, log, Cloudflare, Shopify, Gmail,
database, active-color state, or generated runtime output files are part of
this package.

## Exact Proposed Commands

For `aftersales-web-1` / old `8000` rollback path, preserve the existing
command shape and add only `--noreload` to `runserver`.

Current:

```text
CMD ["bash", "-lc", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]
```

Proposed:

```text
CMD ["bash", "-lc", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000 --noreload"]
```

Important: this does not add a new migration command, but the existing
Dockerfile command already runs `python manage.py migrate` before `runserver`.
Any future restart or rebuild of the old `8000` path must therefore be treated
as a runtime and migration-risk action requiring explicit approval.

For `web_blue` and `web_green`, preserve the shared candidate command shape and
add only `--noreload` to `runserver`.

Current:

```text
command: bash -lc "python manage.py runserver 0.0.0.0:8000"
```

Proposed:

```text
command: bash -lc "python manage.py runserver 0.0.0.0:8000 --noreload"
```

## Minimal Diff Plan

Future approved patch only:

```diff
--- a/backend/Dockerfile
+++ b/backend/Dockerfile
@@
-CMD ["bash", "-lc", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]
+CMD ["bash", "-lc", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000 --noreload"]
```

```diff
--- a/docker-compose.bluegreen.proxy-candidate.example.yml
+++ b/docker-compose.bluegreen.proxy-candidate.example.yml
@@
-  command: bash -lc "python manage.py runserver 0.0.0.0:8000"
+  command: bash -lc "python manage.py runserver 0.0.0.0:8000 --noreload"
```

No other command, port, volume, network, env file, health check, proxy config,
Cloudflare route, active-color state, database, Shopify, Gmail, or scheduler
change is included in this plan.

## Deployment Lock Requirement

The future real apply task is runtime-changing and must acquire the deployment
lock before any build, restart, start, stop, proxy reload, traffic switch,
cleanup, migration, collectstatic, or rollback action.

Lock path:

```text
.deploy/deploy.lock
```

Rules:

- If the lock exists, stop and require a manual rerun.
- Do not auto-queue behind the lock.
- Release only the matching lock id during cleanup.
- Normal documentation and read-only validation tasks are not blocked by the
  lock.

Required reference docs before any real apply:

- [SAFE_DEPLOY.md](SAFE_DEPLOY.md)
- [BLUE_GREEN_LONG_TERM_OPERATIONS.md](BLUE_GREEN_LONG_TERM_OPERATIONS.md)
- [BLUE_GREEN_RUNTIME_AUTO_RELOAD_FIX_PLAN.md](BLUE_GREEN_RUNTIME_AUTO_RELOAD_FIX_PLAN.md)

## Controlled Apply Sequence For Future Approval

This sequence is not executed by this package.

1. Confirm the operator explicitly approved a runtime-changing `--noreload`
   apply for the old `8000` path, `web_blue`, and `web_green`.
2. Confirm no unrelated local changes would be overwritten.
3. Acquire `.deploy/deploy.lock`.
4. Confirm the current rollback target `http://127.0.0.1:8000` is alive.
5. Confirm `bluegreen_proxy_candidate`, `web_blue`, and `web_green` are
   running before changes.
6. Apply only the two command diffs listed in this document.
7. Avoid Cloudflare route changes, proxy reloads, traffic switches,
   collectstatic, and unrelated migrations.
8. Restart or rebuild only the minimum explicitly approved runtime services.
9. Validate direct and proxied health checks.
10. Observe for new `502`, startup-loop, or health-check failures.
11. Keep the old `8000` rollback path alive throughout observation.
12. Release the deployment lock only after the apply, validation, or rollback
    path has completed.

## Health Check Sequence For Future Approval

Run only after the future approved runtime action has been performed.

Direct rollback path:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz/" -UseBasicParsing
```

Candidate proxy path:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:18000/healthz/" -UseBasicParsing
```

Direct service checks may be used only through the exact future approved
Compose project and service names. They must not start, stop, build, restart,
or recreate services unless that action is explicitly approved under the lock.

Expected result:

```text
HTTP 200 from /healthz/
```

## External Check Sequence For Future Approval

Run only after local health checks pass.

Manual browser or read-only HTTP checks:

- `https://tickets.kidstoyloverapps.com/healthz/`
- `https://shopify.kidstoyloverapps.com/healthz/`
- A low-risk tickets page smoke check.
- A low-risk shopify app page smoke check.

Do not submit forms, trigger syncs, call Shopify write APIs, call Gmail APIs,
send emails, publish translations, run `translationsRegister`, or expose
customer data during these checks.

## Rollback Sequence For Future Approval

Rollback must be explicit and manual. This package does not perform rollback.

If the candidate `18000` path fails and the old `8000` path passes:

1. Preserve sanitized evidence without copying secrets, customer personal data,
   or token values.
2. Keep `http://127.0.0.1:8000` alive.
3. Do not stop or remove `bluegreen_proxy_candidate`, `web_blue`, or
   `web_green` unless a separately approved rollback task says so.
4. Revert only the approved `--noreload` command change through a separate
   reviewed runtime task.
5. If public traffic must be moved, follow the reviewed rollback runbook and
   manual Cloudflare rollback plan. Do not improvise a route change.
6. Do not delete volumes, media, uploads, logs, `.deploy` state, or
   secret-bearing files.

If both `18000` and `8000` fail, stop further runtime changes, keep evidence
sanitized, and review logs/status before any rollback or deploy action.

## Commands Not To Run In This Package

Do not run these during this documentation-only task:

```powershell
docker compose up
docker compose up -d
docker compose up -d --build
docker compose build
docker compose restart
docker compose stop
docker compose start
docker compose down
docker compose run
docker compose exec -T web python manage.py migrate
docker compose exec -T web python manage.py collectstatic --noinput
```

Never run these for this package:

```powershell
docker compose down -v
docker volume rm
docker system prune
python manage.py flush
```

Also do not run:

- Cloudflare route changes.
- Proxy reloads.
- Traffic switches.
- Active-color writes.
- Shopify API calls.
- Gmail API calls.
- `translationsRegister`.
- Email sends.
- Git staging, commits, or pushes.
- Destructive Git commands such as `git reset`, `git restore`,
  `git checkout`, `git clean`, or `git rebase`.
- Lock-file deletion.

## Review Status

- Apply package status: ready for ChatGPT review.
- Runtime behavior changed by this package: no.
- Docker restart/up/down/build performed by this package: no.
- Cloudflare route changed by this package: no.
- Deploy, migration, collectstatic, and proxy reload performed by this
  package: no.
- Real `--noreload` apply approval: not granted by this package.
