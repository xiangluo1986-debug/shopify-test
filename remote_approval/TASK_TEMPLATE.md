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
- [ ] Failure stops by default.
- [ ] Secrets are read only from `.env` or existing project config.
- [ ] Secrets are not printed, logged, committed, or added to review files.
- [ ] Review file path is under `logs/`.
- [ ] The local approval Skill is updated if workflow rules changed.
- [ ] This checklist is revisited before commit.
