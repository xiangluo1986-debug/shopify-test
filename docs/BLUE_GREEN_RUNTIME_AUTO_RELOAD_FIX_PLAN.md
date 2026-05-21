# Blue-Green Runtime Autoreload Fix Plan

## Purpose

This is a no-runtime-change diagnosis and apply plan for disabling Django
autoreload on the aftersales blue-green runtime path.

This document does not deploy, restart, rebuild, reload proxy configuration,
switch traffic, change Cloudflare routes, run migrations, run collectstatic,
write active-color state, call Shopify APIs, call Gmail APIs, call
`translationsRegister`, or send email.

## Current Traffic Model

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

The `18000` path and the `8000` rollback path must both remain alive until a
separate approved runtime task changes them.

## Root Cause Summary

The likely root cause of short Cloudflare `502` responses during Codex
code/template edits is Django development-server autoreload in the blue-green
runtime path.

Plain `python manage.py runserver 0.0.0.0:8000` enables Django autoreload by
default. When source or template files change under the mounted app directory,
the development server restarts its inner serving process. During that short
restart window, port `8000` inside `web_blue` or `web_green` can refuse
connections, and `bluegreen_proxy_candidate` can return `502` for requests
that arrive during the gap.

## Evidence Summary

Observed runtime evidence from the task:

- Cloudflare routes both `tickets.kidstoyloverapps.com` and
  `shopify.kidstoyloverapps.com` to `http://127.0.0.1:18000`.
- `18000` routes to `bluegreen_proxy_candidate`, then to `web_blue` /
  `web_green`.
- During code/template edits, Cloudflare can show `502`.
- Docker `RestartCount` for `aftersales-web-1`, `web_blue`, and `web_green`
  is `0`.
- Proxy logs include `connect() failed (111: Connection refused) while
  connecting to upstream`.
- Web logs repeat `Starting development server at http://0.0.0.0:8000/` and
  Django's development-server warning.

Read-only repo inspection:

- `docker-compose.yml` defines `web` without a command override, so the image
  default from `backend/Dockerfile` applies to the `8000` rollback path.
- `backend/Dockerfile` currently defines:

```text
python manage.py migrate && python manage.py runserver 0.0.0.0:8000
```

- `docker-compose.bluegreen.proxy-candidate.example.yml` defines the shared
  `web_blue` / `web_green` candidate command as:

```text
python manage.py runserver 0.0.0.0:8000
```

- `web_blue` and `web_green` inherit that shared command in the
  production-candidate example.
- `docker-compose.bluegreen.local-test.example.yml` and
  `docker-compose.bluegreen.proxy-validation.example.yml` also use plain
  `runserver` for local validation services.
- No inspected Compose or Dockerfile runtime command uses `--noreload`.
- No inspected Compose or Dockerfile runtime command uses `gunicorn`,
  `daphne`, or `uvicorn`.

## Why RestartCount Is Still 0

Docker `RestartCount` increments when the container itself exits and Docker
starts it again. Django autoreload can restart the inner development-server
process while the container remains running.

That means `RestartCount=0` does not rule out an app-level restart inside the
container. It only shows Docker did not repeatedly restart the container.

## Why Repeated Development-Server Starts Matter

`Starting development server at http://0.0.0.0:8000/` is printed when Django
`runserver` starts the serving process. Seeing that message repeatedly while
Docker `RestartCount` stays at `0` points to Django's autoreloader restarting
inside the already-running container.

The accompanying warning that this is a development server confirms the
runtime path is still using `runserver`, not a production WSGI or ASGI server.

## Why The Proxy Sees Connection Refused

During autoreload, Django stops the old serving process and starts a new one.
For a short interval, nothing may be listening on `web_blue:8000` or
`web_green:8000`.

If `bluegreen_proxy_candidate` receives a request during that interval, its
upstream TCP connection can fail with `111: Connection refused`, which is
reported to the public Cloudflare path as a `502`.

## Short-Term Fix

In a separate approved runtime-changing task, add `--noreload` to the
blue-green production path only:

```text
python manage.py runserver 0.0.0.0:8000 --noreload
```

Scope for the short-term fix:

- Target only the `web_blue` / `web_green` production-candidate runtime path.
- Keep the old `http://127.0.0.1:8000` rollback path unchanged.
- Do not change Cloudflare routes in the same step.
- Do not run migrations or collectstatic as part of the command-only fix.
- Do not stop or remove the old `8000` path.

This is still not a production-grade runtime. It is only a stabilization step
to prevent file-edit autoreload gaps while the blue-green path remains on
Django `runserver`.

## Long-Term Fix

Replace Django `runserver` on the production path with a real WSGI or ASGI
server after a separate design and apply review.

Candidate long-term options:

- Gunicorn for WSGI.
- Daphne or Uvicorn for ASGI if the app needs ASGI behavior.

The long-term server choice must review:

- dependency changes,
- worker count,
- timeout settings,
- static and media handling,
- request logging,
- health check behavior,
- graceful restart behavior,
- Windows host and Docker Compose operations,
- rollback behavior,
- deployment lock integration.

## Controlled Apply Checklist

A future apply task must be separately approved before it changes runtime
files or containers.

Checklist:

- Read [SAFE_DEPLOY.md](SAFE_DEPLOY.md) and
  [BLUE_GREEN_LONG_TERM_OPERATIONS.md](BLUE_GREEN_LONG_TERM_OPERATIONS.md).
- Acquire the deployment lock before any runtime-changing action.
- If the deployment lock already exists, stop and require a manual rerun.
  Do not auto-queue behind the lock.
- Confirm `http://127.0.0.1:8000` is still available as rollback.
- Confirm `bluegreen_proxy_candidate`, `web_blue`, and `web_green` are
  running before making changes.
- Prepare the exact runtime command diff for review.
- Change only the approved blue-green production command path.
- Do not change Cloudflare routes in the same task.
- Do not switch traffic in the same task.
- Do not run migrations or collectstatic for the `--noreload` change.
- Restart only the minimum approved blue-green runtime services after the
  command change.
- Validate direct color health where available.
- Validate `http://127.0.0.1:18000/healthz/`.
- Spot-check tickets and shopify paths through the `18000` route.
- Review sanitized proxy and web logs for new `502` or startup loops.
- Keep the old `8000` path alive through the observation period.

## Rollback Checklist

Rollback must be explicit and manual. Do not perform automatic rollback.

Checklist:

- Preserve evidence without copying secrets, customer personal data, or token
  values.
- If `18000` health fails and `8000` health passes, use the reviewed rollback
  runbook before changing public traffic.
- Revert the approved command change only through a separately approved
  runtime task.
- Keep `bluegreen_proxy_candidate`, `web_blue`, and `web_green` running unless
  a reviewed rollback task explicitly says otherwise.
- Keep `http://127.0.0.1:8000` alive.
- Do not remove volumes, media, uploads, logs, or secret-bearing files.
- Do not run destructive Docker, database, or Git cleanup commands.

## Commands Not Approved By This Plan

Do not run these without separate explicit approval and the deployment lock
where applicable:

```powershell
docker compose up
docker compose up -d
docker compose up -d --build
docker compose build
docker compose restart
docker compose stop
docker compose start
docker compose down
docker compose exec -T web python manage.py migrate
docker compose exec -T web python manage.py collectstatic --noinput
```

Never run these for this plan:

```powershell
docker compose down -v
docker volume rm
docker system prune
python manage.py flush
```

Also not approved by this plan:

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

## Review Status

- Diagnosis package: ready for ChatGPT review.
- Runtime behavior changed by this document: no.
- Short-term `--noreload` apply: not approved by this document.
- Long-term WSGI/ASGI replacement: not approved by this document.
- Production apply remains NO-GO until a separate runtime-changing task is
  explicitly approved.
