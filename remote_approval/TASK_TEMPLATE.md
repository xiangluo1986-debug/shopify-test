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
- Batch multi-locale dry-run tasks may generate one review per product/locale plus a summary review, but must not publish or write translations.
- Batch multi-locale dry-run tasks may also generate a local HTML dashboard for human review only; the dashboard must not trigger write, publish, apply, update, commit, or push actions.
- Batch multi-locale dry-run review results should include QA gate fields: `qa_status`, `qa_warnings`, `qa_failures`, and `qa_checks`.
- Batch QA gates should check title/meta length, body HTML presence, forbidden shipping/origin phrases, forbidden CTA phrases, exaggerated military/combat wording, mojibake / encoding corruption, image alt text presence, HTML structure preservation, and no-write confirmation.
- Batch review JSON must be written with a JSON serializer in an ASCII-safe escaped form, sanitize unsafe control characters from command output, and validate with `json.loads` after writing. If validation fails, report `review_json_invalid`.
- Batch apply plan tasks may read the latest batch dry-run review and write local JSON/HTML plan files only. They must not call Shopify APIs, `translationsRegister`, mutations, publish, apply, update, database writes, or git push.
- Batch apply plan tasks should validate the source dry-run review before creating plan items and classify each product/locale as `ready_for_apply`, `needs_review`, or `blocked`.
- Batch apply plan items should include manual review template fields: `manual_decision`, `manual_decision_allowed_values`, `manual_reviewer`, `manual_review_notes`, `manual_review_required`, and `manual_approval_ready`.
- Batch apply plan summaries should explicitly report `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.
- Batch apply plan validation tasks may read manually edited apply plan JSON and write local validation JSON/HTML reports only. They must not call Shopify APIs, `translationsRegister`, mutations, publish, apply, update, database writes, or git push.
- Batch apply plan validation should allow `manual_decision=approve` only for items that were already ready for human approval, have `qa_status=pass`, `eligible_for_apply=true`, no QA failures, and confirmed no-write status.
- Batch apply execution preview tasks may read the latest apply plan validation JSON and write local preview JSON/HTML reports only. They must not call Shopify APIs, `translationsRegister`, mutations, publish, apply, update, database writes, or git push.
- Batch apply execution previews should list only future-approved items in `preview_apply_items` and list every excluded item in `not_apply_items` with reasons.
- Batch apply execution previews should include `final_approval_summary` with `final_approval_status=pending`, allowed values `pending`, `approved`, and `rejected`, and `final_apply_allowed=false`; they should also report `shopify_write_performed=false`.
- Batch apply execution final validation tasks may read the latest execution preview JSON and write local final validation JSON/HTML reports only. They must not call Shopify APIs, `translationsRegister`, mutations, publish, apply, update, database writes, or git push.
- Batch apply execution final validation should block approved status unless a final approver is present, at least one preview apply item exists, and every preview apply item is final-approved, final-ready, QA-passing, future-apply eligible, and still no-write.
- Batch apply command generation tasks may read the latest final validation JSON and write local command/payload plan JSON/HTML reports only. They must not call Shopify APIs, `translationsRegister`, mutations, publish, apply, update, database writes, or git push.
- Batch apply command generation should produce zero commands when `final_apply_allowed=false`. If future final validation allows apply, generated command plans remain preview-only and still require a separate explicitly confirmed write task before execution.
- Batch apply command generation should include a command approval template with `command_approval_status=pending`, allowed values `pending`, `approved`, and `rejected`, and `command_execution_allowed=false`.
- Batch apply command validation tasks may read the latest command plan JSON and write local command validation JSON/HTML reports only. They must not execute commands, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, database writes, or git push.
- Batch apply command validation should block approved status unless a command approver is present, at least one generated command exists, every command item is approved and ready, command previews contain no secret-like markers, and all write flags remain false.
- Batch apply execution dry-run tasks may read the latest command validation JSON and write local execution dry-run JSON/HTML reports only. They must not execute commands, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, database writes, or git push.
- Batch apply execution dry-run should output a blocked dry-run report with zero simulated executions when `command_execution_allowed=false`; if future command validation allows execution, it still only simulates the flow and must report `command_executed=false`.
- Supported first-phase locales are `de`, `fr`, `es`, `it`, and `ja`.
- Batch multi-locale dry-run tasks are limited to 3 products and 5 locales and must not auto-scan the whole Shopify store.
- Multi-locale dry-run tasks should continue after a single locale fails and record `failure_type` per locale.
- Batch multi-locale dry-run tasks should continue after a single product/locale fails and record `failure_type` per product/locale.
- Per-locale Shopify translation results should include `no_shopify_writes_confirmed`; this is true only after the command succeeds and stdout contains `Dry run complete. No Shopify writes performed.`
- Per-product/locale Shopify translation results should include `no_shopify_writes_confirmed` with the same stdout confirmation rule.
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
- [ ] Failure stops by default, except multi-locale dry-run tasks may continue to later locales or product/locale combinations while keeping writes disabled.
- [ ] Secrets are read only from `.env` or existing project config.
- [ ] Secrets are not printed, logged, committed, or added to review files.
- [ ] Review file path is under `logs/`.
- [ ] The local approval Skill is updated if workflow rules changed.
- [ ] Shopify translation dry-run tasks cannot become write tasks.
- [ ] Multi-locale Shopify translation tasks keep glossary files valid JSON and avoid shipping origin / exaggerated marketing glossary entries.
- [ ] Multi-locale Shopify translation tasks record per-locale review paths, `failure_type`, and `no_shopify_writes_confirmed`.
- [ ] Batch multi-locale Shopify translation tasks enforce the 3 product / 5 locale limit and never auto-scan the store.
- [ ] Batch multi-locale Shopify translation tasks record per-product/locale review paths, `failure_type`, and `no_shopify_writes_confirmed`.
- [ ] Batch multi-locale Shopify translation tasks record QA gate status and keep QA failures in review-only mode.
- [ ] Batch multi-locale Shopify translation tasks validate generated JSON review files after writing.
- [ ] Batch apply plan tasks are review-only and never perform Shopify apply/write/publish actions.
- [ ] Batch apply plan tasks include manual review fields while keeping all items pending until a future confirmed write workflow.
- [ ] Batch apply plan validation tasks are validation-only and never perform Shopify apply/write/publish actions.
- [ ] Batch apply execution preview tasks are preview-only and never perform Shopify apply/write/publish actions.
- [ ] Batch apply execution previews keep final approval pending and do not treat preview generation as permission to write.
- [ ] Batch apply execution final validation tasks are validation-only and never perform Shopify apply/write/publish actions.
- [ ] Batch apply command generation tasks are command-generation-only and never execute generated commands or perform Shopify apply/write/publish actions.
- [ ] Batch apply command generation tasks keep command approval pending and do not treat command plan generation as permission to execute writes.
- [ ] Batch apply command validation tasks are command-validation-only and never execute generated commands or perform Shopify apply/write/publish actions.
- [ ] Batch apply execution dry-run tasks are execution-dry-run-only and never execute generated commands or perform Shopify apply/write/publish actions.
- [ ] Batch multi-locale Shopify translation tasks keep generated HTML/JSON review files ignored by Git.
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
