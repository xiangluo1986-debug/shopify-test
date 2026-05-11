# Local Approval Runner Task Template

Copy this template when adding a fixed approval task.

## Task Name

`example_task_name`

## Goal

Describe the exact outcome this task checks or produces.

## Read-Only

- Yes / No:
- If no, explain why a write is needed and where it writes.

## Dry-Run

- Dry-run only: Yes / No
- Default mode: `dry-run`

Dry-run tasks must never become write tasks. If a write is needed later, create a separate task.

## External System Writes

- Writes Shopify: No
- Writes database: No
- Writes files: review/log files only
- Other external writes:

If a task involves Shopify writes, create an independent write task and require a second confirmation after review.

For Shopify translation dry-run tasks:

- Dry-run tasks must return before any Shopify mutation or `translationsRegister` write path.
- Multi-locale dry-run tasks may generate one review per locale plus a summary review, but must not publish or write translations.
- Supported first-phase locales are `de`, `fr`, `es`, `it`, and `ja`.
- Multi-locale dry-run tasks should continue after a single locale fails and record `failure_type` per locale.
- Per-locale Shopify translation results should include `no_shopify_writes_confirmed`; this is true only after the command succeeds and stdout contains `Dry run complete. No Shopify writes performed.`
- Validate each configured glossary before running the locale. Invalid or missing glossary files should fail only that locale with `failure_type=glossary_invalid`.
- Unsupported locale configuration should be recorded as `failure_type=unsupported_locale` and must not be passed into a command.
- Real translation writes must be implemented as a separate task with explicit second confirmation.

## Fixed Command Or Function

Use one of:

```python
FIXED_COMMAND = ["tool", "fixed", "args"]
```

or:

```python
def run_example_task(mode: str) -> dict:
    ...
```

Do not accept arbitrary command parameters.
Do not use `shell=True`.
Do not concatenate user input into shell commands.

## Allowed Approval Actions

- `Y` / `1`:
- `N` / `0`:
- `P`:
- `STOP`:
- `SHOW_LOG`:
- `SUMMARY`:

## Forbidden Actions

- Arbitrary PowerShell command execution
- Shopify publish / mutation / product update / tag update
- Price or inventory changes
- Refunds or order cancellations
- Migrations or bulk database changes unless the user explicitly confirms a separate task
- `git push`, `git reset`, or `git restore` unless explicitly requested

## Review File Path

`logs/example_task_review.json`

## Log Fields

Recommended fields:

- `task`
- `mode`
- `approval_mode`
- `command_label`
- `start_time`
- `end_time`
- `duration_seconds`
- `exit_code`
- `success`
- `detected_issue_summary`
- `stdout_tail`
- `stderr_tail`
- `review_file_path`
- `selected_action`
- `result`

## Safety Checklist

- [ ] Task is registered in `task_registry`.
- [ ] Task metadata is added for `--list-tasks`.
- [ ] Only fixed commands or fixed Python functions are used.
- [ ] No `--command` argument is added.
- [ ] No `shell=True`.
- [ ] No user input is concatenated into commands.
- [ ] Default mode is `dry-run`.
- [ ] Failure stops by default, except multi-locale dry-run tasks may continue to later locales while keeping writes disabled.
- [ ] Secrets are read only from `.env` or existing project config.
- [ ] Secrets are not printed, logged, committed, or added to review files.
- [ ] Review file path is under `logs/`.
- [ ] The local approval Skill is updated if workflow rules changed.
- [ ] Shopify translation dry-run tasks cannot become write tasks.
- [ ] Multi-locale Shopify translation tasks keep glossary files valid JSON and avoid shipping origin / exaggerated marketing glossary entries.
- [ ] Multi-locale Shopify translation tasks record per-locale review paths, `failure_type`, and `no_shopify_writes_confirmed`.
- [ ] This checklist is revisited before commit.

## Git Safety Checklist

For tasks that inspect Git state:

- [ ] Use only fixed read-only `git` commands.
- [ ] Do not run `git add`.
- [ ] Do not run `git commit`.
- [ ] Do not run `git push`.
- [ ] Do not run `git reset`.
- [ ] Do not run `git restore`.
- [ ] Do not run `git clean`.
- [ ] Do not run rebase.
- [ ] Do not delete files.
- [ ] Do not print secret matches; report only file path, pattern type, and risk level.
- [ ] Treat `.env`, logs, review files, approval history/state, scheduler logs, scripts, and Shopify write-sensitive files as suspicious.
- [ ] The task should only generate a review file and approval summary.
