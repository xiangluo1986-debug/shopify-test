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
The non-production runtime validation gate for that future path is documented
in
[BLUE_GREEN_NON_PRODUCTION_VALIDATION.md](BLUE_GREEN_NON_PRODUCTION_VALIDATION.md).
The local inactive runtime validation passed on 2026-05-18, and local/test
proxy routing validation passed on 2026-05-19. Production apply remains
blocked until the production preflight document is reviewed, a production
apply readiness checklist package / exact command review is reviewed, command
implementation is added in a later task, and a separate manual production
approval is given. The production preflight
readiness review is documented at
[BLUE_GREEN_PRODUCTION_PREFLIGHT.md](BLUE_GREEN_PRODUCTION_PREFLIGHT.md).
The production apply readiness checklist and exact command review package is
documented at
[BLUE_GREEN_PRODUCTION_APPLY_READINESS.md](BLUE_GREEN_PRODUCTION_APPLY_READINESS.md).
The dedicated production runtime command review is documented at
[BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md](BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md).
The production runtime details document is documented at
[BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md).
The production traffic path audit is documented at
[BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md](BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md).
The external routing decision package is documented at
[BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md).
The traffic path option comparison is documented at
[BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md](BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md).
The no-action Option B Cloudflare route change and rollback plan is documented
at
[BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md](BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md).
The Cloudflare route change readiness and manual cutover approval package is
documented at
[BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md).
The final pre-cutover live checklist is documented at
[BLUE_GREEN_PRE_CUTOVER_LIVE_CHECKLIST.md](BLUE_GREEN_PRE_CUTOVER_LIVE_CHECKLIST.md).
The production switch/rollback review document is documented at
[BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md).
The post-cutover observation document is documented at
[BLUE_GREEN_POST_CUTOVER_OBSERVATION.md](BLUE_GREEN_POST_CUTOVER_OBSERVATION.md).
The post-cutover hardening plan is documented at
[BLUE_GREEN_HARDENING_PLAN.md](BLUE_GREEN_HARDENING_PLAN.md).
The manual rollback runbook is documented at
[BLUE_GREEN_ROLLBACK_RUNBOOK.md](BLUE_GREEN_ROLLBACK_RUNBOOK.md).
The long-term operations document is documented at
[BLUE_GREEN_LONG_TERM_OPERATIONS.md](BLUE_GREEN_LONG_TERM_OPERATIONS.md).
The blue-green formalization plan is documented at
[BLUE_GREEN_FORMALIZATION_PLAN.md](BLUE_GREEN_FORMALIZATION_PLAN.md).
The final runtime approval design is documented at
[BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md](BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md).
These documents are READY after review; production implementation is NOT
READY, exact production runtime command implementation is still not enabled,
Cloudflare Published application routes for both tickets and shopify are
confirmed to target `http://127.0.0.1:18000`, and the rollback target remains
`http://127.0.0.1:8000`. Option A and Option B are documented; Option B is the
conservative recommendation and is now active after manual cutover. Candidate
services must remain running while Cloudflare targets `18000`. No additional
Cloudflare/domain routing change and no host port `8000` ownership change are
approved without separate future approval. The cutover approval package records
the completed target, rollback target, and manual rollback plan; this
documentation update does not perform a Cloudflare change or production apply.

The final runtime approval design is READY after review, but runtime command
execution remains NOT ENABLED and the documented future approval phrase is
inactive.

The current safe deploy flow now enforces a deployment single-flight lock in
real non-dry-run mode. The standalone helper exists at
`scripts/deploy_lock.ps1`, and `safe_deploy.ps1` reports/checks lock state in
dry-run/check-only modes without acquiring the real lock. Before any future
blue-green production apply, proxy switch, rolling restart, or cleanup work,
the deployment lock described in [DEPLOYMENT_LOCK.md](DEPLOYMENT_LOCK.md) must
also be enforced by that runtime-changing path.
`scripts/blue_green_production_apply.ps1` now exists as a blocked production
command path skeleton. It prints the future lock and apply plan, planned phases
for preflight, lock, target color preparation, switch, observe, rollback, and
cleanup, and still blocks real production apply in this phase. The draft
readiness phrase used only to prove blocked skeleton behavior is:

```text
I_APPROVE_PRODUCTION_BLUE_GREEN_APPLY_AFTER_PREFLIGHT_REVIEW
```

This phrase is NOT ACTIVE for real production apply.

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
- Blue-green production apply skeleton:
  `scripts/blue_green_production_apply.ps1`; command path skeleton implemented
  but blocked, no-action by default, and real production apply remains blocked.
- Proxy switch script: not implemented yet.
- Cleanup script: not implemented yet.
- Local inactive startup: separate local-only gate, not production traffic.
- Non-production inactive runtime validation: passed on 2026-05-18 for
  `web_green_test` on test port `18080`.
- Local/test proxy routing validation: PASSED on 2026-05-19 for
  `bluegreen_proxy_test` on test port `19080` routing to `web_green_test` on
  `18080`; production remains NO-GO.
- Non-production validation chain: PASSED for inactive runtime plus local/test
  proxy routing.
- Production apply: NO-GO until a future runtime-changing implementation uses
  deployment lock acquisition before any build/start/migrate/collectstatic,
  proxy switch, traffic switch, cleanup, or rollback action, the production
  preflight document is reviewed, and migration compatibility, scheduler
  singleton behavior, media/static/uploads, proxy ownership, rollback,
  observation, cleanup, and data safety are checked.
- Production apply readiness package:
  [BLUE_GREEN_PRODUCTION_APPLY_READINESS.md](BLUE_GREEN_PRODUCTION_APPLY_READINESS.md)
  is READY after review.
- Production command review document:
  [BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md](BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md)
  is READY after review; production implementation is NOT READY, exact runtime
  command implementation is still not enabled.
- Production runtime details document:
  [BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md](BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md)
  is READY after review for conservative defaults only. It documents nginx as
  proxy candidate, current `web` ownership of host port `8000` until final
  approval, active-color state under `.deploy/active-color.json`, rollback to
  `previous_color`, at least 10 minutes of first-apply observation,
  backward-compatible migration policy, singleton scheduler policy, and shared
  media/uploads requirements. Active-color state under `.deploy/` must not be
  committed and must not contain secrets.
- Production traffic path audit:
  [BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md](BLUE_GREEN_PRODUCTION_TRAFFIC_PATH_AUDIT.md)
  is READY after review. It confirms active Compose still declares `web` on
  `8000:8000`, no active Compose proxy service was found during the original
  audit, and both Cloudflare Published application routes now target
  `http://127.0.0.1:18000`.
- External routing decision package:
  [BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md](BLUE_GREEN_EXTERNAL_ROUTING_DECISION.md)
  is READY after review. The Cloudflare Published application route origin is
  confirmed, and the manual option decision selected Option B by changing both
  Cloudflare service targets to `http://127.0.0.1:18000`.
- Traffic path option comparison:
  [BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md](BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md)
  is READY after review. Option B is the conservative recommendation and is
  now active; `8000` takeover is NOT APPROVED, and production apply scripts
  remain no-action / blocked unless separately approved.
- Option B Cloudflare route plan:
  [BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md](BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md)
  is READY after review. Proxy port `18000` is the active Cloudflare target,
  rollback target is `http://127.0.0.1:8000`, and production apply scripts
  remain no-action / blocked unless separately approved.
- Cloudflare cutover approval package:
  [BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md)
  is READY after review. `18000` candidate validation has PASSED, proposed
  cutover target is `http://127.0.0.1:18000`, rollback target is
  `http://127.0.0.1:8000`, the `18000` candidate route has PASSED, final
  runtime rehearsal has PASSED, Cloudflare cutover has PASSED, candidate
  services must remain running, and production apply scripts remain no-action /
  blocked unless separately approved.
- Production switch/rollback review document:
  [BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md](BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md)
  is READY after review for design only. It documents the future proxy switch
  flow, active-color state design, rollback flow, cleanup boundaries, and
  remaining blockers. Proxy switch command: NOT IMPLEMENTED. Rollback command:
  NOT IMPLEMENTED.

Runtime-changing deploy paths include container start, container stop,
container restart, image build, migration, collectstatic, proxy switch, traffic
switch, cleanup of blue/green services, production apply, and rollback. Future
scripts for those paths must acquire the deployment lock before changing
runtime state. If the lock exists, they must block and exit non-zero, not
auto-queue. They must release only the matching `lock_id` in cleanup/finally
handling. Non-production runtime validation must follow the same lock rule for
test-only runtime actions. Stale locks require manual review. Normal
non-deploy tasks are not blocked.

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

Blue-green production apply skeleton:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\blue_green_production_apply.ps1
```

This skeleton is no-action by default. It does not deploy, acquire the
deployment lock, run Docker commands, run migrations, run collectstatic, switch
traffic, or modify files. Execution requests remain blocked unless the draft
readiness phrase, valid target/active colors, `.deploy/` lock path gate,
migration compatibility confirmation, scheduler singleton confirmation,
media/static shared storage confirmation, and rollback command confirmation are
present; even then real production apply remains blocked because runtime
execution is not approved in this phase. It also reports that local/test proxy
validation is passed, the production preflight document exists, the production
apply readiness package exists, the production command review document exists,
the production runtime details document exists, the production switch/rollback
review document exists, active-color state design is reviewed, conservative
defaults are documented, exact runtime command implementation is still not
enabled, the proxy switch command and rollback command are still not
implemented, the draft approval phrase is not active for real apply, and
production apply remains NO-GO.

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

## Command policy

Current safe deploy command:

```powershell
.\scripts\safe_deploy.ps1
```

Current non-deploy commands remain unchanged. Django checks, Codex runner
tasks, Review Request dry-runs, Translation dry-runs, documentation updates,
and read-only reports should keep using their existing task-specific commands
as long as they do not deploy, restart, switch traffic, write external systems,
or expose secrets.

Deployment/update commands are special. Do not rely on manual
`docker compose up -d --build` as the long-term deployment method. Use
`scripts/safe_deploy.ps1` for the current deployment safety flow. After
blue-green deployment is implemented and explicitly approved, the future
blue-green deployment script replaces only the deploy command; normal
non-deploy commands stay unchanged.

Deployment lock enforcement is active for real `safe_deploy` mode and is
required for any future runtime-changing blue-green path. If the lock exists,
the deploy task must stop and require manual rerun; it must not auto-queue.
Normal dry-run, read-only, documentation, and non-deploy tasks are not blocked
by the deployment lock.

Current status: production blue-green runtime execution is NOT ENABLED and
production apply remains NO-GO. No Cloudflare/domain routing change and no host
port `8000` ownership change are approved without separate future approval.
The confirmed Cloudflare Published application route target for both tickets
and shopify is `http://127.0.0.1:18000`; Option A and Option B are documented at
[BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md](BLUE_GREEN_TRAFFIC_PATH_OPTION_COMPARISON.md).
The no-action Option B route plan is documented at
[BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md](BLUE_GREEN_OPTION_B_CLOUDFLARE_ROUTE_PLAN.md).
The conservative recommendation was Option B, and the manual Cloudflare
cutover has PASSED. The local production-candidate proxy path on `18000` has
PASSED validation, and Cloudflare now targets `http://127.0.0.1:18000`.
The rollback target is `http://127.0.0.1:8000`. Candidate services must remain
running. The final runtime rehearsal has PASSED, and the `18000` candidate
route has PASSED. The Cloudflare cutover result is documented at
[BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md).
The post-cutover observation and hardening docs are ready for ChatGPT review;
the formalization plan is ready for ChatGPT review; the next step is review
and separately approved monitoring/proxy hardening, not a deploy.

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

## Blue-Green Runtime Helper Status

- `scripts/blue_green_runtime_commands.ps1` exists as a plan-only / no-action
  blue-green helper.
- It does not change `safe_deploy.ps1` behavior.
- It does not reload proxy, switch traffic, write active-color state, execute
  rollback, start/stop/restart/build containers, run migrations, or run
  collectstatic.
- Proxy switch execution is NOT ENABLED.
- Active-color state write is NOT ENABLED.
- Rollback execution is NOT ENABLED.
- Production apply remains NO-GO.
- Final runtime implementation requires a separate approval task before any
  executable command is connected to the blue-green helper.

## Blue-Green Production-Candidate Proxy Design Update

- Candidate compose example exists at
  [../docker-compose.bluegreen.proxy-candidate.example.yml](../docker-compose.bluegreen.proxy-candidate.example.yml).
- Candidate nginx config example exists at
  [../nginx/bluegreen.proxy-candidate.example.conf](../nginx/bluegreen.proxy-candidate.example.conf).
- The previous local `18000` candidate test failed because nginx referenced
  `web_green:8000` while the candidate Compose file did not define a
  `web_green` service on the same Docker network.
- The fixed candidate Compose example now defines `web_blue`, `web_green`, and
  `bluegreen_proxy_candidate` on one candidate network. The blue/green
  services reuse the existing `aftersales-web` image and expose only container
  port `8000`.
- A later local `18000` candidate test confirmed nginx could reach
  `web_green`, but `web_green` returned `GET /healthz/` as HTTP 404. That
  narrowed the remaining issue to candidate web source/env alignment, not
  Docker networking.
- The candidate web services now reference the active `.env` path without
  documenting values, mount `./backend:/app`, set `working_dir: /app`, mount
  workflow logs/media like active web, and keep an explicit no-migration
  `runserver` command for local candidate validation.
- Proposed production-candidate local proxy port: `18000`
  (`bluegreen_proxy_candidate`, host `18000` -> container `80`).
- Candidate validation remains local port `18000` only. Host port `8000`
  remains the current web path and is not published by the candidate example.
- Bluegreen proxy candidate `18000` validation: PASSED on 2026-05-19.
- Option B proxy candidate local path: PASSED.
- Production script requirement: wait for `web_blue` and `web_green` health
  before proxy validation or cutover because the first proxy request can return
  HTTP 502 while backends start.
- The candidate files are example-only, not active, not used by normal
  `docker compose` commands, and must not bind host port `8000`.
- Current Cloudflare routes for `tickets.kidstoyloverapps.com` and
  `shopify.kidstoyloverapps.com` now target `http://127.0.0.1:18000`.
- Previous target / rollback target: `http://127.0.0.1:8000`.
- Cloudflare cutover: PASSED before this documentation update.
- Candidate services must remain running while Cloudflare targets `18000`.
- Production blue-green external traffic path: ACTIVE through `18000`
  candidate.
- Host port `8000` takeover: NOT APPROVED.
- Production apply scripts remain no-action / blocked unless separately
  approved.
- Final runtime rehearsal: PASSED.
- Post-cutover observation and hardening docs are ready for ChatGPT review.
- Future cutover requires manual Cloudflare edit and rollback plan review at
  [BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md](BLUE_GREEN_CLOUDFLARE_CUTOVER_APPROVAL.md).

## Final Manual Checklist Link

- Pre-cutover live checklist exists at
  [BLUE_GREEN_PRE_CUTOVER_LIVE_CHECKLIST.md](BLUE_GREEN_PRE_CUTOVER_LIVE_CHECKLIST.md).
- Pre-cutover live checklist: READY after review.
- Final manual Cloudflare cutover checklist exists at
  [BLUE_GREEN_MANUAL_CLOUDFLARE_CUTOVER_CHECKLIST.md](BLUE_GREEN_MANUAL_CLOUDFLARE_CUTOVER_CHECKLIST.md).
- Manual cutover checklist: READY after review.
- Approval phrase is documentation-only:
  `I_APPROVE_MANUAL_CLOUDFLARE_CUTOVER_TO_18000_AFTER_LIVE_CHECKS`.
- No script should accept the phrase yet.
- Cloudflare cutover: PASSED.
- Current Cloudflare target: `http://127.0.0.1:18000`.
- Rollback target: `http://127.0.0.1:8000`.
- Candidate services must remain running.
- Production blue-green external traffic path: ACTIVE through `18000`
  candidate.
- Production apply scripts remain no-action / blocked unless separately
  approved.
- Post-cutover observation and hardening docs are ready for ChatGPT review.
