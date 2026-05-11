# Codex Task Workflow

## Purpose

This workflow standardizes how Codex App should handle larger tasks in this project. The goal is to avoid large unreviewed edits, accidental Shopify writes, accidental commits of logs or secrets, and accidental pushes to `main`.

## Default Process

Every larger task should follow these steps.

### 1. Understand Task

- Restate the user's goal.
- Identify the affected modules.
- Mark risk level: `low`, `medium`, or `high`.

Treat Shopify API work, orders, inventory, price changes, refunds, customer data, database writes, migrations, and production data changes as `high` risk.

### 2. Plan Small Steps

- Split the work into 2-5 small phases.
- For each phase, state which files are expected to change.
- Pause before high-risk phases and wait for explicit user confirmation.

### 3. Make Minimal Changes

- Complete one small phase at a time.
- Do not mix unrelated changes.
- Do not modify `logs/`, `backend/reviews/`, `.env`, generated review files, or local secrets.

### 4. Run Fixed Checks

Choose fixed checks by task type:

```powershell
python remote_approval_runner.py --list-tasks
python remote_approval_runner.py --task django_check --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_dry_run --mode dry-run --approval local
python remote_approval_runner.py --task git_safety_check --mode dry-run --approval local
```

Use only registered fixed tasks. Do not add arbitrary command execution.

### 5. Local Approval

- If the task reaches a key decision point, use local approval.
- The user may enter `Y`, `N`, `P`, `STOP`, `SHOW_LOG`, or `SUMMARY`.
- Do not bypass approval.
- Do not interpret approval replies as shell commands.

### 6. Git Safety Check

Before preparing any commit or push request, run:

```powershell
python remote_approval_runner.py --task git_safety_check --mode dry-run --approval local
```

Review the output before staging or committing. Do not push without explicit user approval.

### 7. Summary

At the end, report:

- Files changed
- Commands run
- Check results
- Remaining risks
- Whether a commit is recommended
- Suggested commit message
- Whether pushing `main` is forbidden or needs explicit confirmation

## Safety Rules

- Do not allow arbitrary PowerShell command input.
- Do not add `--command`.
- Do not use `shell=True`.
- Do not concatenate user input into commands.
- Do not read or print `.env` secrets.
- Do not run `git push main` unless the user explicitly confirms.
- Do not run `git reset --hard` unless the user explicitly confirms that exact operation.
- Do not perform Shopify writes unless using an independent write task with second confirmation.
- Dry-run tasks must never become write tasks.
- Treat Shopify API, orders, inventory, prices, refunds, and customer data as `high` risk.

## Recommended Command Sequence

```powershell
python remote_approval_runner.py --list-tasks
python remote_approval_runner.py --task django_check --mode dry-run --approval local
python remote_approval_runner.py --task git_safety_check --mode dry-run --approval local
```

For Shopify translation preview only:

```powershell
python remote_approval_runner.py --task shopify_translation_dry_run --mode dry-run --approval local
python remote_approval_runner.py --task git_safety_check --mode dry-run --approval local
```

## When To Stop

Stop and ask the user if any of these occur:

- Docker `Access is denied`
- Git `.git/index.lock` or permission problem
- Secret risk
- Dirty `main` with unrelated changes
- Shopify write risk
- Unclear task scope
- Migration required
- Database write required
- Production data modification
- Request involves refunds, order cancellation, price changes, or inventory changes

## Output Discipline

Keep final summaries concise and specific. Mention what changed, what was checked, and what remains risky. If a task was blocked, say exactly where it stopped and why.
