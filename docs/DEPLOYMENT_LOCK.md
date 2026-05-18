# Deployment Lock Design

## Purpose

The deployment lock prevents more than one deploy, update, switch, or cleanup
flow from running at the same time. It is intended to protect both the current
`safe_deploy` flow and the future blue-green deploy flow.

The standalone helper now exists at `scripts/deploy_lock.ps1`.
`scripts/safe_deploy.ps1` now enforces the deployment lock in real
non-dry-run mode. It also has dry-run/check-only lock awareness for validation
without deployment. `scripts/blue_green_production_apply.ps1` now exists as a
no-action production apply skeleton that documents the future lock gates, but
real production blue-green apply remains NO-GO until a future apply task
implements exact runtime commands and uses the same lock before any
runtime-changing action.

## What The Lock Protects

The lock should be acquired before any task that could change the runtime web
deployment state, including:

- `scripts/safe_deploy.ps1`.
- `scripts/blue_green_production_apply.ps1` in any future runtime-changing
  phase.
- Future blue-green deploy scripts.
- Future proxy switch scripts.
- Future production cleanup scripts.
- Future rolling restart scripts.
- Any task that could build, restart, switch, stop, or clean up the web runtime.

The goal is to prevent overlapping operations such as two builds racing, one
task switching traffic while another restarts a service, or one cleanup command
stopping a service another task just made active.

## Runtime-Changing Path Inventory

The following current or future actions are runtime-changing deployment paths.
Each one must acquire the deployment lock before it starts, must block and exit
non-zero if the lock already exists, must not auto-queue, and must release only
the matching `lock_id` in cleanup/finally handling:

- Container start for an inactive blue/green service.
- Container stop for an inactive, previous-active, or cleanup service.
- Container restart or replacement for any serving web path.
- Image build or image preparation tied to a deploy.
- Django migration during a deploy.
- `collectstatic` or another deploy-time static asset update.
- Proxy reload, proxy upstream edit, or proxy configuration apply.
- Traffic switch from one color to another.
- Cleanup of blue/green services after an observation window.
- Production apply for `safe_deploy` or future blue-green deploys.
- Rollback, including proxy switchback, service restart, service stop/start, or
  restoring a previously approved runtime target.

Stale locks require manual review before any release attempt. Normal
non-deploy tasks, read-only diagnostics, and documentation updates are not
blocked by the deployment lock.

## What The Lock Does Not Protect

The deployment lock is not required for normal read-only or non-runtime work,
including:

- Normal read-only checks.
- Normal Django admin usage.
- Normal customer service workflows.
- Review Request or Translation dry-run tasks that do not deploy.
- Local one-off diagnostics that do not modify runtime state.

Read-only checks should still avoid exposing secrets and should not modify
containers, files, traffic, or external systems.

Normal non-deploy tasks are not blocked by this deployment lock. The lock is
for deploy, restart, switch, cleanup, and other runtime-changing deployment
tasks.

## Proposed Lock Location

Use a local runtime-only path that is never treated as source-controlled state:

```text
.deploy/deploy.lock
```

The `.deploy/` directory should be ignored, or at minimum lock files inside it
must not be committed. Do not store secrets, tokens, credentials, database
passwords, private URLs, or environment values in the lock file.

## Lock Contents

The lock file contains enough sanitized metadata for another operator to
understand who owns the deployment flow and what phase it is in:

- `lock_id`
- `created_at`
- `user`
- `host`
- `process_id`
- `command`
- `purpose`
- `target`
- `max_age_minutes`
- `project_path`

The command should be a human-readable command label or sanitized command text.
It must not include secret-bearing arguments or private environment values.

## Helper Commands

The real helper is:

```powershell
scripts/deploy_lock.ps1
```

Check status without modifying files:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action status
```

Acquire the default deployment lock:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action acquire -Purpose "safe-deploy" -Target "production"
```

Acquire uses atomic file creation for `.deploy/deploy.lock`. It creates the
`.deploy/` directory if needed, then fails non-zero if the lock file already
exists. On success, it prints the generated `lock_id`.

Release requires the exact `lock_id` from the current lock:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action release -LockId <lock_id>
```

If `-LockId` is missing or does not match the current lock metadata, release is
blocked and exits non-zero. This protects another task's lock from accidental
deletion.

Validate the helper and any existing lock metadata without modifying files:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action validate
```

`-LockPath` may be used for test locks under `.deploy/`, such as:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action status -LockPath .\.deploy\test-deploy.lock
```

The helper intentionally restricts lock paths to the project `.deploy/`
directory.

## safe_deploy Enforcement, Dry-Run, And Check-Only

`scripts/safe_deploy.ps1 -DryRun` now reports:

- Deployment lock path.
- Whether `scripts/deploy_lock.ps1` exists.
- Whether a deployment lock currently exists.
- That real safe deploy acquires the lock before
  build/check/migrate/collectstatic/restart.
- That real safe deploy releases the lock in cleanup/finally
  handling.
- Whether a real safe deploy would be blocked by an existing lock.

Dry-run does not create, acquire, release, or delete the real deployment lock.

`scripts/safe_deploy.ps1 -CheckDeployLock` checks lock status only. It does not
create, delete, acquire, release, deploy, build, run migrations, run
collectstatic, restart containers, or switch traffic. It exits `0` when no lock
exists and exits non-zero when a lock exists.

For validation against a temporary test lock under `.deploy/`, use
`-DeployLockPath`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\safe_deploy.ps1 -CheckDeployLock -DeployLockPath .\.deploy\test-safe-deploy.lock
```

Validate the acquire/release cleanup path without deployment:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\safe_deploy.ps1 -ValidateDeployLockOnly -DeployLockPath .\.deploy\test-safe-deploy.lock
```

This validation may create and release the selected test lock under `.deploy/`,
but it does not run Docker, build images, run checks, run migrations, run
collectstatic, restart containers, call the health check, or switch traffic.

Real non-dry-run `safe_deploy.ps1` acquires the deployment lock before the
first Docker deploy command and holds it through restart and health check. It
releases only the matching `lock_id` in cleanup/finally handling. If the lock
already exists, safe deploy blocks before build/check/migrate/collectstatic or
restart and requires a manual rerun after the current deployment finishes.

## Blue-Green Production Apply Skeleton

The production apply skeleton is:

```powershell
scripts/blue_green_production_apply.ps1
```

Current status: skeleton only / no-action. Default execution prints the
production apply plan, required lock behavior, future steps, and exits `0`
without acquiring the deployment lock or changing runtime state.

The required approval phrase for any future production apply execution request
is:

```text
I_APPROVE_PRODUCTION_BLUE_GREEN_APPLY_WITH_DEPLOYMENT_LOCK
```

The skeleton blocks execution requests without the exact phrase, blocks missing
or same target/active color choices, and blocks any `DeployLockPath` outside
`.deploy/`. Even with the correct phrase, it still blocks real production apply
with:

```text
Real production blue-green apply is not implemented in this phase.
```

The skeleton does not run Docker Compose commands, start/stop/restart/build
containers, run migrations, run collectstatic, switch proxy traffic, modify
active `docker-compose.yml`, modify production nginx/proxy configuration, or
call Shopify/Gmail/review/translation workflows.

## Lock Behavior

Future deploy scripts should follow this behavior:

1. Acquire the deployment lock before any deploy, build, restart, switch, or
   cleanup action.
2. If the lock exists, block the operation and exit non-zero.
3. Print sanitized lock owner metadata, including who owns the lock and when it
   was created.
4. Do not auto-queue deployment tasks behind the lock.
5. If a second deploy task sees the lock, stop and require a manual rerun after
   the first deploy is complete.
6. Do not automatically delete another active lock.
7. Allow stale lock review only through an explicit manual command and approval.
8. Release the lock in a `finally` or cleanup block owned by the process that
   acquired it.

Lock acquisition should be atomic. The implementation should avoid a
check-then-create race where two processes both decide the lock is available.

## Stale Lock Policy

The default stale threshold is 120 minutes.

A stale-looking lock should require manual review before removal. The review
should confirm:

- The original process is not still running.
- No deploy, restart, switch, or cleanup is still in progress.
- The lock metadata matches the expected host and environment.
- The operator understands which deployment phase may have been interrupted.

Never auto-remove a lock if the current process status is unclear.

The current helper reports a stale candidate when `created_at` is older than
`-MaxAgeMinutes`, but it does not auto-delete stale locks. `-ForceStaleRelease`
is accepted only as an explicit signal for future/manual stale handling; this
version still requires an exact `LockId` release and does not perform stale
deletion.

## Future Integration Plan

Integrate the deployment lock into:

- `scripts/safe_deploy.ps1`.
- The future real implementation behind
  `scripts/blue_green_production_apply.ps1`.
- The future proxy switch script.
- Future production cleanup and rolling restart scripts.

Local simulation may use a separate local-simulation lock if needed, especially
when test ports or temporary inactive services are involved. Production and
runtime-changing actions should use the shared deployment lock.

## Deployment Lock Coverage Status

- `safe_deploy.ps1`: enforced in real mode.
- Blue-green production apply skeleton:
  `scripts/blue_green_production_apply.ps1`; no-action by default and real
  production apply remains blocked.
- Proxy switch script: not implemented yet.
- Cleanup script: not implemented yet.
- Local inactive startup: separate local-only gate, not production traffic.
- Production apply: NO-GO until a future runtime-changing implementation uses
  deployment lock acquisition before build/start/migrate/collectstatic/proxy
  switch/cleanup and releases only the matching `lock_id`.

## Current Status

- Real helper exists: `scripts/deploy_lock.ps1`.
- Read-only helper: `scripts/deploy_lock_dry_run.ps1`.
- Default lock path: `.deploy/deploy.lock`.
- `scripts/safe_deploy.ps1` has real-mode lock enforcement.
- `scripts/safe_deploy.ps1 -DryRun` reports lock state but does not acquire or
  release the lock.
- `scripts/safe_deploy.ps1 -CheckDeployLock` is read-only.
- `scripts/safe_deploy.ps1 -ValidateDeployLockOnly` validates acquire/release
  with a selected lock path and runs no deploy commands.
- `scripts/blue_green_production_apply.ps1` exists as a no-action skeleton. It
  prints the future lock flow but does not acquire the lock in default or
  blocked execution modes.
- Production blue-green apply remains NO-GO until a separate future apply task
  approves exact runtime commands and confirms every runtime-changing path uses
  the deployment lock.
