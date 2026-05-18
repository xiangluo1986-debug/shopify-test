# Deployment Lock Design

## Purpose

The deployment lock prevents more than one deploy, update, switch, or cleanup
flow from running at the same time. It is intended to protect both the current
`safe_deploy` flow and the future blue-green deploy flow.

The standalone helper now exists at `scripts/deploy_lock.ps1`, but the lock is
not yet enforced by active deployment scripts. Production apply remains NO-GO
until enforcement is integrated into `safe_deploy` and the future blue-green
runtime-changing deploy paths.

## What The Lock Protects

The lock should be acquired before any task that could change the runtime web
deployment state, including:

- `scripts/safe_deploy.ps1`.
- Future blue-green deploy scripts.
- Future proxy switch scripts.
- Future production cleanup scripts.
- Future rolling restart scripts.
- Any task that could build, restart, switch, stop, or clean up the web runtime.

The goal is to prevent overlapping operations such as two builds racing, one
task switching traffic while another restarts a service, or one cleanup command
stopping a service another task just made active.

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

## Lock Behavior

Future deploy scripts should follow this behavior:

1. Acquire the deployment lock before any deploy, build, restart, switch, or
   cleanup action.
2. If the lock exists, block the operation and exit non-zero.
3. Print sanitized lock owner metadata, including who owns the lock and when it
   was created.
4. Do not automatically delete another active lock.
5. Allow stale lock review only through an explicit manual command and approval.
6. Release the lock in a `finally` or cleanup block owned by the process that
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
- The future blue-green deploy script.
- The future proxy switch script.
- Future production cleanup and rolling restart scripts.

Local simulation may use a separate local-simulation lock if needed, especially
when test ports or temporary inactive services are involved. Production and
runtime-changing actions should use the shared deployment lock.

## Current Status

- Real helper exists: `scripts/deploy_lock.ps1`.
- Read-only helper: `scripts/deploy_lock_dry_run.ps1`.
- Default lock path: `.deploy/deploy.lock`.
- Active deploy scripts do not enforce the lock yet.
- Current task adds the helper only, not active deploy enforcement.
- Production apply remains NO-GO until the deployment lock is integrated into
  active deploy scripts and enforced before build, restart, switch, and cleanup
  actions.
