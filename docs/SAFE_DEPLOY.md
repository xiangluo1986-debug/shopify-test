# Safe Deploy and Health Check

## Why this exists

Deploys can briefly break a server while code, containers, migrations, and static assets are changing. The standard for this project is:

1. Build before restart.
2. Validate before restart.
3. Restart only after checks pass.
4. Confirm `/healthz/` after restart.
5. Print useful logs and fail loudly if the server is not healthy.

This reduces the chance of silently leaving the Django aftersales server unavailable after an update.

## Current limitation

The current Compose setup has one `web` container serving port `8000`. `safe_deploy.ps1` reduces deployment risk by validating before restart and checking `/healthz/` after restart, but it cannot fully eliminate brief restart-time unavailability while a single serving container is replaced.

For the future zero- or lower-downtime design, see [BLUE_GREEN_DEPLOY_PLAN.md](BLUE_GREEN_DEPLOY_PLAN.md). That plan is documentation only until a separate reviewed apply task is approved.

The current safe deploy flow now enforces a deployment single-flight lock in
real non-dry-run mode. The standalone helper exists at
`scripts/deploy_lock.ps1`, and `safe_deploy.ps1` reports/checks lock state in
dry-run/check-only modes without acquiring the real lock. Before any future
blue-green production apply, proxy switch, rolling restart, or cleanup work,
the deployment lock described in [DEPLOYMENT_LOCK.md](DEPLOYMENT_LOCK.md) must
also be enforced by that runtime-changing path.
The runtime-only lock path is:

```text
.deploy/deploy.lock
```

The existing local inactive-color startup success on non-production port
`18080` does not remove this requirement. The lock protects against overlapping
deploy-related tasks, which is separate from proving that an inactive local
service can become healthy.

## Deployment Lock Coverage Status

- `safe_deploy.ps1`: enforced in real mode.
- Blue-green production apply script: not implemented yet.
- Proxy switch script: not implemented yet.
- Cleanup script: not implemented yet.
- Local inactive startup: separate local-only gate, not production traffic.
- Production apply: NO-GO until all runtime-changing scripts use deployment
  lock.

Runtime-changing deploy paths include container start, container stop,
container restart, image build, migration, collectstatic, proxy switch, traffic
switch, cleanup of blue/green services, production apply, and rollback. Future
scripts for those paths must acquire the deployment lock before changing
runtime state. If the lock exists, they must block and exit non-zero, not
auto-queue. They must release only the matching `lock_id` in cleanup/finally
handling. Stale locks require manual review. Normal non-deploy tasks are not
blocked.

## Current project deploy command

From the project root:

```powershell
.\scripts\safe_deploy.ps1
```

Dry run:

```powershell
.\scripts\safe_deploy.ps1 -DryRun
```

`-DryRun` reports the deployment lock path, whether
`scripts/deploy_lock.ps1` exists, whether the lock currently exists, and whether
a real safe deploy would be blocked. It does not acquire or release the real
lock and still executes no deploy commands.

Check only for an existing deployment lock:

```powershell
.\scripts\safe_deploy.ps1 -CheckDeployLock
```

This checks lock status only. It does not deploy, build, migrate,
collectstatic, restart containers, create a lock, delete a lock, acquire a
lock, or release a lock. It exits `0` when no lock exists and non-zero when a
lock exists.

For validation with a temporary test lock under `.deploy/`:

```powershell
.\scripts\safe_deploy.ps1 -CheckDeployLock -DeployLockPath .\.deploy\test-safe-deploy.lock
```

Validate acquire/release cleanup without deploying:

```powershell
.\scripts\safe_deploy.ps1 -ValidateDeployLockOnly -DeployLockPath .\.deploy\test-safe-deploy.lock
```

This may create and release the selected test lock under `.deploy/`, but it
does not run Docker, build images, run migrations, run collectstatic, restart
containers, call `/healthz/`, or switch traffic.

Deployment lock dry-run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock_dry_run.ps1 -Purpose "safe-deploy-preflight" -Target "production" -ShowPlan
```

This helper is read-only. It does not create or delete `.deploy/deploy.lock`.
`scripts/safe_deploy.ps1` has dry-run/check-only awareness of the lock, and
real non-dry-run deploy enforces it before the first Docker deploy command.

Deployment lock helper status:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action status
```

Acquire/release examples are documented in
[DEPLOYMENT_LOCK.md](DEPLOYMENT_LOCK.md). Release requires the exact `lock_id`
from the current lock. `scripts/safe_deploy.ps1` automatically acquires this
lock in real mode and releases only the matching `lock_id` in cleanup/finally
handling.

Deployment tasks should not auto-queue behind the lock. If a deploy task sees
an existing lock, it should stop and require a manual rerun after the current
deploy is complete. Normal non-deploy tasks are not blocked by this deployment
lock.

Optional flags:

```powershell
.\scripts\safe_deploy.ps1 -SkipMigrate
.\scripts\safe_deploy.ps1 -SkipCollectstatic
.\scripts\safe_deploy.ps1 -HealthUrl "http://127.0.0.1:8000/healthz/"
```

`-SkipPull` is accepted for operator habit, but this script does not run `git pull` by default. Update code through the approved workflow before deployment.

## Health check URL

```text
http://127.0.0.1:8000/healthz/
```

Expected response:

```text
OK
```

The health endpoint is public, lightweight, and does not call Shopify, OpenAI, Gmail, Trustpilot, Kudosi, Ali Reviews, or any other external service. It must not expose secrets.

## What the script does

`scripts/safe_deploy.ps1` performs this sequence:

1. Prints the current Git branch.
2. Prints `git status --short`.
3. Warns if the working tree is dirty.
4. In `-DryRun` only, reports deployment lock awareness and whether a real
   deploy would be blocked.
5. In real mode only, acquires `.deploy/deploy.lock` before any Docker deploy
   command. If the lock exists, the script exits non-zero before build/check,
   migration, collectstatic, restart, or health check. It does not queue.
6. Builds the web image:

```powershell
docker compose build web
```

7. Runs Django checks:

```powershell
docker compose run --rm web python manage.py check
```

8. Runs migrations unless `-SkipMigrate` is set:

```powershell
docker compose run --rm web python manage.py migrate
```

9. Runs collectstatic unless `-SkipCollectstatic` is set:

```powershell
docker compose run --rm web python manage.py collectstatic --noinput
```

10. Restarts the web service:

```powershell
docker compose up -d web
```

11. Polls the health endpoint for up to 60 seconds.
12. Releases only the matching deployment lock in cleanup/finally handling,
    even when build, check, migration, collectstatic, restart, or health check
    fails.
13. Prints success only after the health endpoint returns HTTP 200.

Real-mode lock enforcement is active for this script. Future runtime-changing
blue-green, proxy switch, rolling restart, or cleanup scripts must follow the
same acquire-before-change and release-in-cleanup pattern.

## If the health check fails

The script exits non-zero and prints:

```powershell
docker compose logs --tail=100 web
```

Inspect the service state:

```powershell
docker compose ps
docker compose logs --tail=100 web
```

Check whether the failure is caused by settings, missing dependencies, failed migrations, static asset setup, database connectivity, or a container start error.

## Rollback notes

Use the approved rollback path for the environment, such as redeploying a previously validated image or release package. If the deployment included migrations, review the migration and backup state before attempting any database rollback. Do not use destructive cleanup commands or broad Git rollback commands without explicit human approval.

After restoring the intended code or image, run the safe deploy flow again and confirm `/healthz/`.

## Migration notes

Migrations can change database state. Review migration contents before deployment when models changed. If a deploy has no database changes, `-SkipMigrate` can be used only when the operator has confirmed migrations are unnecessary.

## Static files notes

This Django project defines `STATIC_ROOT`, so `collectstatic --noinput` is part of the standard deploy flow. If a future project intentionally does not use Django staticfiles, document that project-specific reason and use an explicit skip flag.

## Commit safety reminders

Do not commit generated logs, secrets, `.env`, credential files, local config, private tokens, database dumps, or deployment output. Do not stage or commit `logs/`.

## Reusable Safe Deploy Template for New Projects

Every deployable project should include:

1. A health endpoint:
   - `/healthz/`
   - or `/api/health`
2. A safe deploy script:
   - `scripts/safe_deploy.ps1` for Windows workflows
   - `scripts/safe_deploy.sh` for Linux or macOS workflows
3. Deployment docs:
   - `docs/SAFE_DEPLOY.md`
4. A standard deploy flow:
   - build
   - check or test
   - migrate if the project uses a database
   - collectstatic or build assets
   - restart
   - health check
   - print logs if failed

### Django

Use:

```powershell
python manage.py check
python manage.py migrate
python manage.py collectstatic --noinput
```

Health endpoint:

```text
/healthz/
```

### Node or Next.js

Use the package manager already used by the project:

```powershell
npm ci
npm run build
npm test
```

or:

```powershell
pnpm install --frozen-lockfile
pnpm build
pnpm test
```

Restart the app or container, then check:

```text
/api/health
```

or:

```text
/healthz/
```

### Shopify app

Use the app's established package manager and framework commands:

```powershell
npm ci
npm run lint
npm run build
```

Run database migrations if the app uses a database, restart the app, then check `/healthz/`. Deploy checks must not call Shopify write APIs or expose tokens.

### Docker Compose app

Use:

```powershell
docker compose build
docker compose run --rm app test
docker compose up -d
```

Then check:

```powershell
curl http://127.0.0.1:8000/healthz/
```

## Default rule for new projects

When Codex creates or reorganizes a new deployable project, it should proactively add or recommend:

- `/healthz/` or an equivalent health endpoint.
- A safe deploy script.
- Deployment documentation.
- A no-secrets and no-logs commit rule.
- Health check validation after restart.

This applies to Django projects, Shopify apps, Node/Next.js apps, Docker Compose apps, and future internal tools.
