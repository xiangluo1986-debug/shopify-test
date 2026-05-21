# Blue-Green Runtime Autoreload Apply Package

## Purpose

Prepare and record the controlled source/config change to disable Django
development-server autoreload for the aftersales runtime by adding
`--noreload` to the relevant `runserver` commands.

This task updates source/config definitions only. It does not recreate or
restart running containers, so currently running runtime behavior is unchanged
until a separate controlled apply is performed.

This package does not build images, restart containers, run Docker Compose
apply commands, run migrations, run collectstatic, reload proxy configuration,
switch traffic, change Cloudflare routes, call Shopify APIs, call Gmail APIs,
call `translationsRegister`, send email, stage files, commit, or push.

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

Runtime paths covered by the source/config `--noreload` change and requiring
future controlled container recreation:

- `aftersales-web-1` / old host `8000` rollback path.
- `web_blue`.
- `web_green`.

## Inspection And Config Change Result

Before this task, the active `docker-compose.yml` `web` service did not define
a command override. It published host port `8000` and therefore used the image
default from `backend/Dockerfile` for the old rollback path.

Previous command source for `aftersales-web-1`:

```text
backend/Dockerfile
```

Current command:

```text
CMD ["bash", "-lc", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]
```

Because `backend/Dockerfile` is outside the allowed files for this task, the
prepared config change adds an explicit `web` command override in
`docker-compose.yml`.

Prepared command for `aftersales-web-1` / old `8000` rollback path:

```text
command: bash -lc "python manage.py migrate && python manage.py runserver 0.0.0.0:8000 --noreload"
```

The current production-candidate blue/green services inherit a shared command
from the `x-candidate-django-web` anchor in:

```text
docker-compose.bluegreen.proxy-candidate.example.yml
```

Previous shared command for `web_blue` and `web_green`:

```text
command: bash -lc "python manage.py runserver 0.0.0.0:8000"
```

Prepared shared command for `web_blue` and `web_green`:

```text
command: bash -lc "python manage.py runserver 0.0.0.0:8000 --noreload"
```

`web_blue` and `web_green` both inherit that command through:

```text
web_blue:
  <<: *candidate-django-web

web_green:
  <<: *candidate-django-web
```

## Exact Config Files Changed

This source/config task changes only these command sources:

```text
docker-compose.yml
docker-compose.bluegreen.proxy-candidate.example.yml
```

No `backend/Dockerfile` change is made in this task.

No `.env`, `.env.*`, token, credential, log, Cloudflare, Shopify, Gmail,
database, active-color state, or generated runtime output files are part of
this package.

## Exact Proposed Commands

For `aftersales-web-1` / old `8000` rollback path, preserve the existing
effective command shape and add only `--noreload` to `runserver` through a
`docker-compose.yml` command override.

Previous effective image default:

```text
CMD ["bash", "-lc", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]
```

Prepared `docker-compose.yml` override:

```text
command: bash -lc "python manage.py migrate && python manage.py runserver 0.0.0.0:8000 --noreload"
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

Prepared:

```text
command: bash -lc "python manage.py runserver 0.0.0.0:8000 --noreload"
```

## Minimal Diff Plan

Prepared patch:

```diff
--- a/docker-compose.yml
+++ b/docker-compose.yml
@@
     depends_on:
       - db
+    command: bash -lc "python manage.py migrate && python manage.py runserver 0.0.0.0:8000 --noreload"
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
6. Confirm only the two command diffs listed in this document are present.
7. Avoid Cloudflare route changes, proxy reloads, traffic switches,
   collectstatic, and unrelated migrations.
8. Restart or rebuild only the minimum explicitly approved runtime services.
9. Validate direct and proxied health checks.
10. Observe for new `502`, startup-loop, or health-check failures.
11. Keep the old `8000` rollback path alive throughout observation.
12. Release the deployment lock only after the apply, validation, or rollback
    path has completed.

## Controlled Apply Commands For Future Approval

This section is documentation only. Do not run these commands unless a future
runtime-changing task explicitly approves the apply, acquires the deployment
lock, and confirms the current `18000` candidate path and `8000` rollback path
are healthy before recreation.

Manual no-build recreation commands for only the affected web services:

```powershell
docker compose up -d --no-build --no-deps --force-recreate web
docker compose -f docker-compose.bluegreen.proxy-candidate.example.yml up -d --no-build --no-deps --force-recreate web_blue web_green
```

Scope:

- Recreates only `web`, `web_blue`, and `web_green`.
- Does not rebuild images.
- Does not recreate `db`, `scheduler`, or `bluegreen_proxy_candidate`.
- Does not change Cloudflare routes, reload the proxy, switch traffic, run
  collectstatic, call Shopify APIs, call Gmail APIs, call
  `translationsRegister`, or send email.
- The active `web` command preserves the existing `python manage.py migrate`
  prelude, so recreating `web` is still a runtime/migration-risk action and
  requires explicit approval under the deployment lock.

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

- Apply package status: source/config change ready for controlled apply.
- Runtime behavior changed by this package: no; running containers were not
  recreated or restarted.
- Docker restart/up/down/build performed by this package: no.
- Cloudflare route changed by this package: no.
- Deploy, migration, collectstatic, and proxy reload performed by this
  package: no.
- Controlled container apply: not performed and still requires a separate
  runtime-changing approval and deployment lock.
