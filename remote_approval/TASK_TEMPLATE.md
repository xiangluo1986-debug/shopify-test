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
- Batch apply execution dry-run reports should include an execution approval template with `execution_approval_status=pending`, allowed values `pending`, `approved`, and `rejected`, and `real_execution_allowed=false`; editing this template must not execute commands or write Shopify.
- Batch apply execution approval validation tasks may read the latest execution dry-run JSON and write local execution approval validation JSON/HTML reports only. They must not execute commands, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, database writes, or git push.
- Batch apply execution approval validation should block approved status unless an execution approver is present, at least one simulated execution exists, every simulated item is approved and ready, payload preview is available, and all no-write / no-command-execution fields remain false.
- Batch apply locked runner tasks may read the latest execution approval validation JSON and write local locked runner JSON/HTML reports only. They must not execute commands, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, database writes, or git push.
- Batch apply locked runner should output `locked` when `real_execution_allowed=false` and `ready_but_locked` when a future validation reports eligible execution, but it must always keep `real_apply_allowed=false`, `real_apply_performed=false`, and `command_executed=false`.
- Single-field apply sandbox design tasks may read the latest locked runner JSON and write local sandbox design JSON/HTML reports only. They must not execute commands, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, database writes, or git push.
- Single-field apply sandbox design must hard-code a future sandbox scope of 1 product, 1 locale, 1 field, allowed field `meta_title`, default field `meta_title`, `real_write_allowed=false`, and `translations_register_allowed=false`.
- Single-field apply sandbox runner tasks may read the latest sandbox design JSON and write local sandbox runner JSON/HTML reports only. They must be forced dry-run only, require manually supplied product/locale/field environment variables, accept only `field=meta_title`, and must not fall back to product ID files or scan Shopify.
- Single-field apply sandbox runner tasks must not execute commands, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, database writes, or git push. They must report `real_write_allowed=false`, `real_write_attempted=false`, `translations_register_allowed=false`, `translations_register_called=false`, and `shopify_write_performed=false`.
- Single-field apply preflight package tasks may read the latest sandbox runner JSON and write local preflight package JSON/HTML reports only. They must require manually supplied product/locale/field/proposed-value environment variables, accept only `field=meta_title`, require proposed value length <= 60 characters, and match the sandbox runner scope exactly.
- Single-field apply preflight package tasks must not call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, database writes, or git push. They must report `real_write_allowed=false`, `real_write_attempted=false`, `translations_register_allowed=false`, `translations_register_called=false`, and `shopify_write_performed=false`.
- Single-field backup fetch tasks may read the latest preflight package JSON and write local backup JSON/HTML reports only. They must require manually supplied product/locale/field environment variables, accept only `field=meta_title`, match the preflight package scope exactly, and may perform only one read-only Shopify GraphQL `translatableResource` query.
- Single-field backup fetch tasks must not call Shopify mutations, call `translationsRegister`, publish, apply, update, database writes, or git push. They must report `real_write_allowed=false`, `translations_register_allowed=false`, `translations_register_called=false`, `mutation_performed=false`, `shopify_mutations_called=[]`, and `shopify_write_performed=false`.
- Single-field readback / rollback plan tasks may read only the latest single-field preflight package and backup fetch JSON files and write local JSON/HTML plan files only. They must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push.
- Single-field readback / rollback plan tasks must mark the backup unverified and block future writes when `read_only_shopify_query_performed=false`; verified empty backups are allowed only when the read-only backup query really ran and confirmed an empty value.
- Single-field final write gate tasks may read only the latest single-field preflight package, backup fetch report, and readback / rollback plan JSON files and write local JSON/HTML final gate files only.
- Single-field final write gate tasks must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push. They may prepare a human final approval package but must keep `final_real_write_allowed=false`.
- Single-field real write runner design tasks may read only the latest single-field preflight package, backup fetch report, readback / rollback plan, and final write gate JSON files and write local JSON/HTML design files only.
- Single-field real write runner design tasks must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, git push, or generate directly executable real-write commands. They may describe a future runner design but must keep `design_only=true` and `real_write_allowed=false`.
- Single-field real write locked runner tasks may read only the latest single-field preflight package, backup fetch report, readback / rollback plan, final write gate, real write runner design, and manually supplied sandbox environment variables. They must write local JSON/HTML locked-runner reports only.
- Single-field real write locked runner tasks must stay locked even when `SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true` is present. They must not call Shopify APIs, execute commands, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push. They must report `locked_shell=true`, `dangerous_flag_effective=false`, `real_write_allowed=false`, and `shopify_write_performed=false`.
- Single-field real write pre-execution validation tasks may read only the latest single-field preflight package, backup fetch report, readback / rollback plan, final write gate, real write runner design, locked runner, and manually supplied sandbox environment variables. They must write local JSON/HTML validation reports only.
- Single-field real write pre-execution validation tasks must require `SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true` before reporting `ready_for_manual_write_approval`, but the flag must not trigger writing in this phase. They must not call Shopify APIs, execute commands, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push. They must report `pre_execution_validation_only=true`, `write_execution_allowed=false`, `real_write_allowed=false`, and `shopify_write_performed=false`.
- Single-field final human approval package tasks may read only the latest single-field preflight package, backup fetch report, readback / rollback plan, final write gate, real write runner design, locked runner, pre-execution validation report, and manually supplied sandbox environment variables. They must write local JSON/HTML final approval reports only.
- Single-field final human approval package tasks must require `SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true`, a ready pre-execution validation report, verified backup, and matching scope before reporting `ready_for_final_human_review`. They must not call Shopify APIs, execute commands, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push. They must report `final_human_approval_package_only=true`, `phase_12_entry_allowed=false`, `write_execution_allowed=false`, `real_write_allowed=false`, and `shopify_write_performed=false`.
- Single-field real write runner final-safe shell tasks may read only the latest single-field preflight package, backup fetch report, readback / rollback plan, final write gate, real write runner design, locked runner, pre-execution validation report, final human approval package, and manually supplied sandbox environment variables. They must write local JSON/HTML final-safe shell reports only.
- Single-field real write runner final-safe shell tasks must require `SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true` and may record `SHOPIFY_TRANSLATION_PHASE_12_FINAL_SAFE_SHELL_ACK=true`, but neither flag can trigger writing in this phase. They must not call Shopify APIs, execute commands, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push. They must report `final_safe_shell_only=true`, `phase_12_1_entry_allowed=false`, `phase_12_entry_allowed=false`, `write_execution_allowed=false`, `real_write_allowed=false`, and `shopify_write_performed=false`.
- Single-field real write execution plan tasks may read only the latest single-field preflight package, backup fetch report, readback / rollback plan, final write gate, real write runner design, locked runner, pre-execution validation report, final human approval package, final-safe shell report, and manually supplied sandbox environment variables. They must write local JSON/HTML execution plan reports only.
- Single-field real write execution plan tasks must require `SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true`, `SHOPIFY_TRANSLATION_PHASE_12_FINAL_SAFE_SHELL_ACK=true`, and `SHOPIFY_TRANSLATION_PHASE_12_1A_PLAN_ACK=true`, but none of these flags can trigger writing in this phase. They may generate a `translationsRegister` payload preview only and must not call Shopify APIs, execute commands, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push. They must report `execution_plan_only=true`, `payload_preview_only=true`, `phase_12_1b_entry_allowed=false`, `phase_12_1_entry_allowed=false`, `phase_12_entry_allowed=false`, `write_execution_allowed=false`, `real_write_allowed=false`, and `shopify_write_performed=false`.
- Single-field real write one-shot locked shell tasks may read only the latest single-field preflight package, backup fetch report, readback / rollback plan, final write gate, real write runner design, locked runner, pre-execution validation report, final human approval package, final-safe shell report, execution plan report, and manually supplied sandbox environment variables. They must write local JSON/HTML one-shot locked shell reports only.
- Single-field real write one-shot locked shell tasks must require `SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true`, `SHOPIFY_TRANSLATION_PHASE_12_FINAL_SAFE_SHELL_ACK=true`, `SHOPIFY_TRANSLATION_PHASE_12_1A_PLAN_ACK=true`, and `SHOPIFY_TRANSLATION_PHASE_12_1B_LOCKED_SHELL_ACK=true`, but none of these flags can trigger writing in this phase. They must not call Shopify APIs, execute commands, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push. They must report `one_shot_locked_shell_only=true`, `phase_12_1b_real_execution_allowed=false`, `phase_12_1b_entry_allowed=false`, `phase_12_1_entry_allowed=false`, `phase_12_entry_allowed=false`, `write_execution_allowed=false`, `real_write_allowed=false`, and `shopify_write_performed=false`.
- Single-field real write one-shot execute tasks must default to no-write dry-run. Dry-run mode must not call Shopify APIs, execute commands, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push.
- Single-field real write one-shot execute tasks may only enter a future real execution path in `real-run` or `execute-real-write` mode with the fixed product `gid://shopify/Product/7655686799427`, locale `ja`, field `meta_title`, proposed value `MOFLY P-51D Aileron Link Connector`, every prior local report ready, and `SHOPIFY_TRANSLATION_PHASE_12_1B_REAL_EXECUTION_ACK=YES_I_APPROVE_ONE_REAL_SHOPIFY_TRANSLATION_WRITE`. The task must perform at most one `translationsRegister` mutation, must immediately read back the same scope, and must never run automatic rollback.
- Single-field post-write audit package tasks may read only local JSON reports, including the successful one-shot execution report, and write local JSON/HTML audit files only. They must not call Shopify APIs, execute commands, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push.
- Single-field post-write audit package tasks must distinguish source execution facts from new audit actions: source report fields may show the prior real write, but the audit task itself must report no new Shopify API call, no new Shopify write, no mutation, no `translationsRegister`, no readback, no rollback, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Single-field rollback approval package tasks may read only local backup, readback / rollback plan, one-shot execution, and post-write audit JSON reports, then write local JSON/HTML rollback approval package files only. They must not call Shopify APIs, execute commands, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push.
- Single-field rollback approval package tasks may describe an optional future restore to the verified backup value only, for the same product / locale / `meta_title` scope. They must keep `rollback_execution_allowed=false`, `rollback_performed=false`, `automatic_rollback_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Second single-field test preparation tasks may read only the prior post-write audit, rollback approval package, one-shot execution, and backup fetch JSON reports, plus manually supplied second-test scope environment variables, then write local JSON/HTML preparation files only. They must not call Shopify APIs, execute commands, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push.
- Second single-field test preparation tasks must block when second-test scope variables are missing, must not guess or reuse the previous product without explicit environment variables, must accept only one product, one locale, field `meta_title`, and proposed value length <= 60, and must keep `second_test_prepare_only=true`, `second_test_real_write_allowed=false`, `batch_mode_allowed=false`, `full_store_scan_allowed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Second single-field verified backup fetch tasks may read the second-test preparation JSON report and matching second-test scope environment variables, then perform exactly one read-only Shopify GraphQL `translatableResource` query for the same product / locale / `meta_title` scope. They must not write Shopify, execute write commands, call mutations, call `translationsRegister`, perform rollback, publish, apply, update, database writes, or git push.
- Second single-field verified backup fetch tasks must block missing prepare reports, prepare-not-ready reports, missing scope, scope mismatch, any field other than `meta_title`, and read-only query failures. They must output `second_backup_source_is_verified=true` only after a successful read-only query and must keep `second_test_real_write_allowed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Second single-field real write readiness tasks may read only the second-test preparation report, second verified backup report, and matching second-test scope environment variables, then write local JSON/HTML readiness files only. They must not call Shopify APIs, execute commands, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push.
- Second single-field real write readiness tasks must block missing reports, prepare-not-ready, backup-not-ready, missing scope, scope mismatch, invalid field, empty proposed value, proposed value over 60 chars, and unverified backup. They may output `second_real_write_ready_for_human_approval` only as a human readiness status and must keep `readiness_package_only=true`, `second_test_real_write_allowed=false`, `human_approval_required_before_real_write=true`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Second single-field real write execute tasks must default to no-write dry-run. Dry-run mode must not call Shopify APIs, execute commands, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push.
- Second single-field real write execute tasks may only enter a future real execution path in `real-run` or `execute-real-write` mode with product `gid://shopify/Product/7655686799427`, locale `ja`, field `meta_title`, proposed value `MOFLY P-51D Aileron Link Connector Test`, the second-test prepare / verified backup / readiness reports ready, and `SHOPIFY_TRANSLATION_SECOND_TEST_REAL_EXECUTION_ACK=YES_I_APPROVE_SECOND_REAL_SHOPIFY_TRANSLATION_WRITE`. The task must perform at most one `translationsRegister` mutation, must immediately read back the same scope, and must never run automatic rollback.
- Second single-field post-write audit package tasks may read only the successful second one-shot execution report, with optional second verified backup and readiness reports, and write local JSON/HTML audit files only. They must not call Shopify APIs, execute commands, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, database writes, or git push.
- Second single-field post-write audit package tasks must distinguish source execution facts from new audit actions: source report fields may show the prior Phase 12.7 real write, but the audit task itself must report no new Shopify API call, no new Shopify write, no mutation, no `translationsRegister`, no readback, no rollback, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
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
- [ ] Batch apply execution dry-run reports keep execution approval pending and do not treat dry-run output as permission to execute commands or write Shopify.
- [ ] Batch apply execution approval validation tasks are validation-only and never execute generated commands or perform Shopify apply/write/publish actions.
- [ ] Batch apply locked runner tasks are locked-shell-only and never execute generated commands or perform Shopify apply/write/publish actions.
- [ ] Single-field apply sandbox design tasks are sandbox-design-only and never execute generated commands or perform Shopify apply/write/publish actions.
- [ ] Single-field apply sandbox runner tasks are sandbox-runner-dry-run-only and never execute generated commands or perform Shopify apply/write/publish actions.
- [ ] Single-field apply preflight package tasks are preflight-only and never execute generated commands or perform Shopify apply/write/publish actions.
- [ ] Single-field backup fetch tasks are read-only and never execute generated commands, Shopify mutations, or Shopify apply/write/publish actions.
- [ ] Single-field readback / rollback plan tasks are local-plan-only and never call Shopify APIs or perform readback, rollback, mutation, or Shopify apply/write/publish actions.
- [ ] Single-field final write gate tasks are local-package-only and never call Shopify APIs or perform readback, rollback, mutation, or Shopify apply/write/publish actions.
- [ ] Single-field real write runner design tasks are design-only and never call Shopify APIs, generate executable write commands, or perform readback, rollback, mutation, or Shopify apply/write/publish actions.
- [ ] Single-field real write locked runner tasks are locked-shell-only and never let a dangerous flag trigger Shopify API calls, commands, readback, rollback, mutations, or Shopify apply/write/publish actions.
- [ ] Single-field real write pre-execution validation tasks are validation-only and never let a dangerous flag trigger Shopify API calls, commands, readback, rollback, mutations, or Shopify apply/write/publish actions.
- [ ] Single-field final human approval package tasks are package-only and never let approval text or a dangerous flag trigger Shopify API calls, commands, readback, rollback, mutations, or Shopify apply/write/publish actions.
- [ ] Single-field real write runner final-safe shell tasks are shell-only and never let a dangerous flag or final-safe ack trigger Shopify API calls, commands, readback, rollback, mutations, or Shopify apply/write/publish actions.
- [ ] Single-field real write execution plan tasks are plan-only and never let a dangerous flag, final-safe ack, plan ack, or payload preview trigger Shopify API calls, commands, readback, rollback, mutations, or Shopify apply/write/publish actions.
- [ ] Single-field real write one-shot locked shell tasks are shell-only and never let any dangerous flag or Phase 12.1B locked-shell ack trigger Shopify API calls, commands, readback, rollback, mutations, or Shopify apply/write/publish actions.
- [ ] Single-field real write one-shot execute tasks keep dry-run no-write, limit any future real-run path to exactly 1 product x 1 locale x 1 field=meta_title, require the exact real execution ack, perform immediate readback after a real mutation, and never perform automatic rollback.
- [ ] Single-field post-write audit package tasks are audit-only, read local JSON reports only, preserve prior source write facts separately, and never perform new Shopify API calls, writes, mutations, readback, rollback, or Shopify apply/publish actions.
- [ ] Single-field rollback approval package tasks are approval-package-only, never perform rollback or new Shopify actions, and only describe a future independently approved restore to the verified backup value for the same 1 product x 1 locale x 1 field scope.
- [ ] Second single-field test preparation tasks are prepare-only, never perform Shopify actions, never reuse old backup as the new backup, and require explicit second-test scope environment variables before producing a ready status.
- [ ] Second single-field verified backup fetch tasks perform at most one read-only Shopify query, require exact scope match with the second-test prepare report, accept only field `meta_title`, and never perform write, mutation, `translationsRegister`, rollback, batch, or store-scan actions.
- [ ] Second single-field real write readiness tasks are package-only, read local reports and environment variables only, require exact scope match with the prepare and verified backup reports, and never call Shopify APIs, write, mutate, read back, rollback, batch, or scan the store.
- [ ] Second single-field real write execute tasks keep dry-run no-write, limit any future real-run path to exactly 1 product x 1 locale x 1 field=meta_title, require the exact second real execution ACK, perform immediate readback after a real mutation, and never perform automatic rollback.
- [ ] Second single-field post-write audit package tasks are audit-only, read local JSON reports only, preserve second source write facts separately, and never perform new Shopify API calls, writes, mutations, readback, rollback, or Shopify apply/publish actions.
- [ ] Small batch apply plan package tasks are plan-only, read local JSON reports only, limit plans to one product, one locale, at most 5 entries, fields `meta_title` / `meta_description` only, and never perform Shopify API calls, writes, mutations, readback, rollback, publish, or apply actions.
- [ ] Small batch apply execute tasks keep dry-run no-write, limit any future real-run path to exactly one product, one locale, at most 5 entries, fields `meta_title` / `meta_description` only, require the exact small batch execution ACK, perform immediate readback after a real mutation, and never perform automatic rollback, publish, full-store scan, unsupported-field writes, or bulk expansion.
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
