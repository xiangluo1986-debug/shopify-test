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

The current safe deploy flow also does not yet enforce a deployment
single-flight lock. The standalone helper exists at `scripts/deploy_lock.ps1`,
but `safe_deploy.ps1` does not call it yet. Before any production apply, proxy
switch, rolling restart, or cleanup work, the deployment lock described in
[DEPLOYMENT_LOCK.md](DEPLOYMENT_LOCK.md) must be integrated and enforced.
The runtime-only lock path is:

```text
.deploy/deploy.lock
```

The existing local inactive-color startup success on non-production port
`18080` does not remove this requirement. The lock protects against overlapping
deploy-related tasks, which is separate from proving that an inactive local
service can become healthy.

## Current project deploy command

From the project root:

```powershell
.\scripts\safe_deploy.ps1
```

Dry run:

```powershell
.\scripts\safe_deploy.ps1 -DryRun
```

Deployment lock dry-run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock_dry_run.ps1 -Purpose "safe-deploy-preflight" -Target "production" -ShowPlan
```

This helper is read-only. It does not create or delete `.deploy/deploy.lock`.
`scripts/safe_deploy.ps1` does not enforce the lock yet.

Deployment lock helper status:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action status
```

Acquire/release examples are documented in
[DEPLOYMENT_LOCK.md](DEPLOYMENT_LOCK.md). Release requires the exact `lock_id`
from the current lock. Active deploy scripts still do not acquire or release
this lock automatically.

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
4. Builds the web image:

```powershell
docker compose build web
```

5. Runs Django checks:

```powershell
docker compose run --rm web python manage.py check
```

6. Runs migrations unless `-SkipMigrate` is set:

```powershell
docker compose run --rm web python manage.py migrate
```

7. Runs collectstatic unless `-SkipCollectstatic` is set:

```powershell
docker compose run --rm web python manage.py collectstatic --noinput
```

8. Restarts the web service:

```powershell
docker compose up -d web
```

9. Polls the health endpoint for up to 60 seconds.
10. Prints success only after the health endpoint returns HTTP 200.

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
