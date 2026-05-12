# Local Approval Runner Workflow

## What It Is

Local Approval Runner is a Windows-first workflow for running fixed, registered project tasks from PowerShell with local human approval at key points. It is designed for the current ChatGPT -> Codex App -> PowerShell workflow: Codex prepares or runs a safe fixed task, the runner prompts locally, and the user approves, pauses, stops, or reviews logs from the console.

Telegram approval code is still present for future use, but local approval is the default.

## Good Fits

- Django checks after code changes.
- Shopify translation dry-runs for one configured test product.
- Shopify multi-locale translation dry-runs for one configured test product across `de`, `fr`, `es`, `it`, and `ja`.
- Shopify batch multi-locale translation dry-runs for up to 3 configured products across up to 5 locales.
- Git safety checks before local commits or any future push.
- Future Shenzhen settlement check tasks.
- Low-risk validation after Codex edits code.
- Review-file generation and local audit workflows.

## Poor Fits

- Arbitrary command execution.
- Shopify writes or translation publishing.
- Bulk database modifications.
- `git push`, `git reset`, or `git restore`.
- Refunds, order cancellations, bulk price edits, or inventory edits.

## How To Run

```powershell
python remote_approval_runner.py --task demo --mode dry-run
python remote_approval_runner.py --task django_check --mode dry-run
python remote_approval_runner.py --task git_safety_check --mode dry-run
python remote_approval_runner.py --task shopify_translation_dry_run --mode dry-run
python remote_approval_runner.py --task shopify_translation_multi_locale_dry_run --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_batch_multi_locale_dry_run --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_batch_apply_plan --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_batch_apply_plan_validate --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_batch_apply_execution_preview --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_batch_apply_execution_final_validate --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_batch_apply_command_generate --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_batch_apply_command_validate --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_batch_apply_execution_dry_run --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_batch_apply_execution_approval_validate --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_batch_apply_locked_runner --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_single_field_apply_sandbox_design --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_single_field_apply_sandbox_runner --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_single_field_apply_preflight_package --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_single_field_backup_fetch --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_single_field_readback_rollback_plan --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_single_field_final_write_gate --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_single_field_real_write_runner_design --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_single_field_real_write_locked_runner --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_single_field_real_write_pre_execution_validate --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_single_field_final_human_approval_package --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_single_field_real_write_runner_final_safe_shell --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_single_field_real_write_execution_plan --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_single_field_real_write_one_shot_locked_shell --mode dry-run --approval local
```

Task discovery:

```powershell
python remote_approval_runner.py --list-tasks
```

Summary-only run:

```powershell
python remote_approval_runner.py --task demo --mode dry-run --summary-only
```

## Approval Options

- `Y` / `1` = approve
- `N` / `0` = stop
- `P` = pause
- `C` = continue from pause
- `STOP` = stop immediately
- `SHOW_LOG` = show recent log
- `SUMMARY` = show current task summary

Console replies are fixed options only. They are never treated as PowerShell commands.

## Interrupt Flag

Create this file to request a pause before the next checked task stage:

```powershell
New-Item logs/interrupt.flag
```

When the runner sees `logs/interrupt.flag`, it pauses and shows:

```text
C = continue and remove interrupt flag
STOP = stop task
SHOW_LOG = show recent log
SUMMARY = show current summary
```

## Common Issues

### Docker Access Is Denied

If Docker reports access denied, the task stops and writes a review file. Do not retry with automated elevation. Close Codex App, reopen it as administrator, and confirm Docker Desktop is running.

### Missing `SHOPIFY_TRANSLATION_TEST_PRODUCT_ID`

`shopify_translation_dry_run` requires one configured safe test product:

```env
SHOPIFY_TRANSLATION_TEST_PRODUCT_ID=
```

If it is missing, the task fails safely and does not contact Shopify.

### Multi-Locale Shopify Translation Dry-Run

`shopify_translation_multi_locale_dry_run` runs the fixed Shopify product translation command once per locale for:

```text
de,fr,es,it,ja
```

Override locales only with the fixed environment variable:

```env
SHOPIFY_TRANSLATION_TEST_LOCALES=de,fr,es,it,ja
```

The task is dry-run only. It must never publish translations, call Shopify write mutations, update products, update tags, update prices, update inventory, change orders, run migrations, or write to the database. It writes only local review/log files:

```text
logs/shopify_translation_multi_locale_dry_run_review.json
backend/logs/shopify_translation_command_review_de.json
backend/logs/shopify_translation_command_review_fr.json
backend/logs/shopify_translation_command_review_es.json
backend/logs/shopify_translation_command_review_it.json
backend/logs/shopify_translation_command_review_ja.json
```

Each locale runs independently. A failure in one locale must be recorded and must not stop the remaining configured locales. Each locale result records `failure_type`, `stdout_tail`, `stderr_tail`, `review_file_path`, `warnings_count`, and `no_shopify_writes_confirmed`.

`failure_type` values include `docker_permission_denied`, `missing_product_id`, `missing_env`, `command_error`, `timeout`, `unknown`, `glossary_invalid`, and `unsupported_locale`. Docker access errors are classified as Docker permission failures, not translation logic failures.

`no_shopify_writes_confirmed` is true only when that locale command succeeds and stdout contains `Dry run complete. No Shopify writes performed.` The summary `all_no_write_confirmed` only covers successful locales; failed locales are not marked confirmed.

Before running a locale command, the task validates that locale's glossary file exists and is valid JSON. Unsupported `SHOPIFY_TRANSLATION_TEST_LOCALES` entries are reported in the review and are never passed into a shell command.

Allowed approval actions for this task are:

```text
Y / 1 = keep review files
SHOW_LOG = show recent logs
SUMMARY = show summary
N / 0 = stop
```

Any real Shopify write or publish workflow must be created later as a separate task with explicit second confirmation.

### Batch Multi-Locale Shopify Translation Dry-Run

`shopify_translation_batch_multi_locale_dry_run` runs the fixed Shopify product translation command once per configured product/locale combination. It reads product IDs from:

```env
SHOPIFY_TRANSLATION_TEST_PRODUCT_IDS=gid://shopify/Product/7655686799427,gid://shopify/Product/...
```

If that is empty, it falls back to `SHOPIFY_TRANSLATION_TEST_PRODUCT_ID`. It never scans Shopify for products automatically.

The batch task is limited to 3 products and 5 locales. If either limit is exceeded, it fails safely and writes only the summary review:

```text
logs/shopify_translation_batch_multi_locale_dry_run_review.json
logs/shopify_translation_batch_multi_locale_dry_run_review.html
```

The HTML dashboard is for local human review only. It must not trigger write, publish, apply, update, commit, or push actions, and generated review dashboards must remain ignored by Git.

Each successful command attempt also writes a per-product/locale review such as:

```text
backend/logs/shopify_translation_command_review_7655686799427_de.json
```

Each product/locale combination runs independently. A failure in one combination must be recorded and must not stop the remaining combinations. Each result records `product_id`, `locale`, `failure_type`, `stdout_tail`, `stderr_tail`, `review_file_path`, `warnings_count`, and `no_shopify_writes_confirmed`.

Each batch result also records QA gate fields: `qa_status` (`pass`, `warning`, or `fail`), `qa_warnings`, `qa_failures`, and `qa_checks`. QA gates check translated title/meta lengths, body HTML presence, forbidden shipping/origin phrases, forbidden CTA phrases, exaggerated military/combat wording, mojibake / encoding corruption, image alt text presence, HTML structure preservation, and no-write confirmation. QA failures block acceptance of the dry-run review but must never trigger Shopify writes.

Batch summary JSON must remain strict parseable JSON. Command output strings should be sanitized for unsafe control characters such as the terminal bell, and the JSON is written in an ASCII-safe escaped form so Windows PowerShell can parse it without relying on code-page detection. The task should validate the JSON after writing. If validation fails, the task reports `review_json_invalid`.

`no_shopify_writes_confirmed` is true only when that combination succeeds and stdout contains `Dry run complete. No Shopify writes performed.` The summary `all_no_write_confirmed` covers successful runs only; failed runs are not marked confirmed.

Allowed approval actions for this task are:

```text
Y / 1 = keep review files
SHOW_LOG = show recent logs
SUMMARY = show summary
N / 0 = stop
```

### Batch Translation Apply Plan

`shopify_translation_batch_apply_plan` reads only the latest batch dry-run review:

```text
logs/shopify_translation_batch_multi_locale_dry_run_review.json
```

It validates that the source review is a batch dry-run, has `success_count > 0`, `failed_count == 0`, `all_no_write_confirmed == true`, `no_shopify_writes_performed == true`, and stays within the 3 product / 5 locale limit. It then writes local plan files only:

```text
logs/shopify_translation_batch_apply_plan.json
logs/shopify_translation_batch_apply_plan.html
```

Each plan item is marked `ready_for_apply`, `needs_review`, or `blocked`. Each item also includes manual review template fields: `manual_decision`, `manual_decision_allowed_values`, `manual_reviewer`, `manual_review_notes`, `manual_review_required`, and `manual_approval_ready`. Every item starts with `manual_decision=pending` and `manual_approval_ready=false`.

The plan is for human review only and must not call Shopify APIs, `translationsRegister`, mutations, publish, apply, update, database writes, or git push. The plan summary should explicitly show `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Batch Translation Apply Plan Validation

`shopify_translation_batch_apply_plan_validate` reads only the manually reviewable apply plan:

```text
logs/shopify_translation_batch_apply_plan.json
```

It validates manual decisions and writes local validation reports only:

```text
logs/shopify_translation_batch_apply_plan_validation.json
logs/shopify_translation_batch_apply_plan_validation.html
```

Allowed manual decisions are `pending`, `approve`, `revise`, and `block`. `approve` is only valid for items that were already ready for human approval, have `qa_status=pass`, `eligible_for_apply=true`, no QA failures, and confirmed no Shopify writes. `needs_review` or `blocked` items cannot be approved directly; they are marked blocked in the validation report.

The validation task is validation-only. It must not call Shopify APIs, `translationsRegister`, mutations, publish, apply, update, database writes, or git push. Its summary must explicitly show `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Batch Translation Apply Execution Preview

`shopify_translation_batch_apply_execution_preview` reads only the latest validation report:

```text
logs/shopify_translation_batch_apply_plan_validation.json
```

It may also read the source apply plan to display field names, then writes local preview reports only:

```text
logs/shopify_translation_batch_apply_execution_preview.json
logs/shopify_translation_batch_apply_execution_preview.html
```

Only items with an approved manual decision, validated future-apply status, QA pass, no-write confirmation, and future-apply eligibility are shown in `preview_apply_items`. All other items are listed in `not_apply_items` with reasons.

The preview includes a final approval template under `final_approval_summary`. It starts as `final_approval_status=pending`, allows only `pending`, `approved`, and `rejected`, and keeps `final_apply_allowed=false`.

The preview is for human review only. It must not call Shopify APIs, `translationsRegister`, mutations, publish, apply, update, database writes, or git push. Its summary must explicitly show `preview_only=true`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Batch Translation Final Approval Validation

`shopify_translation_batch_apply_execution_final_validate` reads only the execution preview:

```text
logs/shopify_translation_batch_apply_execution_preview.json
```

It validates the final approval status and writes local validation reports only:

```text
logs/shopify_translation_batch_apply_execution_final_validation.json
logs/shopify_translation_batch_apply_execution_final_validation.html
```

`final_approval_status=pending` keeps `final_apply_allowed=false` and does not make any item eligible for real apply. `final_approval_status=rejected` also keeps apply blocked. `final_approval_status=approved` is only valid when a final approver is present, at least one preview apply item exists, and every preview apply item is final-approved, final-ready, QA-passing, future-apply eligible, and still no-write.

The final validation task is validation-only. It must not call Shopify APIs, `translationsRegister`, mutations, publish, apply, update, database writes, or git push. Its summary must explicitly show `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Batch Translation Apply Command Generation

`shopify_translation_batch_apply_command_generate` reads only the final approval validation report:

```text
logs/shopify_translation_batch_apply_execution_final_validation.json
```

It writes local command/payload plan reports only:

```text
logs/shopify_translation_batch_apply_command_plan.json
logs/shopify_translation_batch_apply_command_plan.html
```

When `final_apply_allowed=false`, the task must generate zero commands and explain that final validation has not approved real apply. If a future final validation approves items, this task may generate command/payload plans for those items, but it must not execute them.

The command plan includes a command approval template. It starts as `command_approval_status=pending`, allows only `pending`, `approved`, and `rejected`, and keeps `command_execution_allowed=false`. Any later real execution must be a separate write task with explicit confirmation.

The command generation task is command-generation-only. It must not call Shopify APIs, `translationsRegister`, mutations, publish, apply, update, database writes, or git push. Its summary must explicitly show `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Batch Translation Apply Command Validation

`shopify_translation_batch_apply_command_validate` reads only the command plan:

```text
logs/shopify_translation_batch_apply_command_plan.json
```

It validates command approval status and writes local validation reports only:

```text
logs/shopify_translation_batch_apply_command_validation.json
logs/shopify_translation_batch_apply_command_validation.html
```

`command_approval_status=pending` keeps `command_execution_allowed=false` and does not make any command eligible for future execution. `command_approval_status=rejected` also keeps execution blocked. `command_approval_status=approved` is only valid when a command approver is present, at least one generated command exists, every command item has `command_decision=approve`, `command_approval_ready=true`, and all no-write / preview-only safety fields remain intact.

The command validation task is command-validation-only. It must not execute commands, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, write the database, or git push. Its summary must explicitly show `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Batch Translation Apply Execution Dry-Run

`shopify_translation_batch_apply_execution_dry_run` reads only the command validation report:

```text
logs/shopify_translation_batch_apply_command_validation.json
```

It may read the command plan for reference, then writes local dry-run reports only:

```text
logs/shopify_translation_batch_apply_execution_dry_run.json
logs/shopify_translation_batch_apply_execution_dry_run.html
```

If `command_execution_allowed=false`, the task outputs a blocked dry-run report with `simulated_execution_count=0` and `command_executed=false`. If a future command validation allows execution, this task still only simulates the flow and must not execute command previews or call Shopify.

The execution dry-run report includes an execution approval template. It starts as `execution_approval_status=pending`, allows only `pending`, `approved`, and `rejected`, and keeps `real_execution_allowed=false`. Editing this template does not execute commands or write to Shopify; any real execution must be a later separate write task with explicit confirmation.

The execution dry-run task is execution-dry-run-only. It must not execute commands, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, write the database, or git push. Its summary must explicitly show `command_executed=false`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Batch Translation Apply Execution Approval Validation

`shopify_translation_batch_apply_execution_approval_validate` reads only the execution dry-run report:

```text
logs/shopify_translation_batch_apply_execution_dry_run.json
```

It validates the execution approval status and writes local validation reports only:

```text
logs/shopify_translation_batch_apply_execution_approval_validation.json
logs/shopify_translation_batch_apply_execution_approval_validation.html
```

`execution_approval_status=pending` keeps `real_execution_allowed=false` and does not make any simulated item eligible for real execution. `execution_approval_status=rejected` also keeps execution blocked. `execution_approval_status=approved` is only valid when an execution approver is present, at least one simulated execution exists, every simulated item has `execution_decision=approve`, `execution_approval_ready=true`, payload preview available, and all no-write / no-command-execution fields remain false.

The execution approval validation task is validation-only. It must not execute commands, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, write the database, or git push. Its summary must explicitly show `command_executed=false`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Batch Translation Locked Apply Runner

`shopify_translation_batch_apply_locked_runner` reads only the execution approval validation report:

```text
logs/shopify_translation_batch_apply_execution_approval_validation.json
```

It writes local locked runner reports only:

```text
logs/shopify_translation_batch_apply_locked_runner.json
logs/shopify_translation_batch_apply_locked_runner.html
```

When `real_execution_allowed=false`, the task outputs `locked_runner_status=locked`, `real_apply_allowed=false`, `real_apply_performed=false`, and `command_executed=false`. If a future validation report sets `real_execution_allowed=true`, this phase still outputs `locked_runner_status=ready_but_locked`, keeps `real_apply_allowed=false`, and only displays eligible item summaries.

The locked runner is a shell only. It must not execute commands, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, write the database, or git push. Its summary must explicitly show `real_apply_performed=false`, `command_executed=false`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Single-Field Apply Sandbox Design

`shopify_translation_single_field_apply_sandbox_design` reads only the locked runner report:

```text
logs/shopify_translation_batch_apply_locked_runner.json
```

It writes local sandbox design reports only:

```text
logs/shopify_translation_single_field_apply_sandbox_design.json
logs/shopify_translation_single_field_apply_sandbox_design.html
```

The sandbox design hard-codes a future write scope of 1 product, 1 locale, and 1 field. The only allowed field is `meta_title`, and the default field is `meta_title`. `title`, `body_html`, and `meta_description` are not allowed in this sandbox design.

The sandbox design task is design-only. It must not execute commands, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, write the database, or git push. It must explicitly report `real_write_allowed=false`, `translations_register_allowed=false`, `command_executed=false`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Single-Field Apply Sandbox Runner

`shopify_translation_single_field_apply_sandbox_runner` reads only the sandbox design report:

```text
logs/shopify_translation_single_field_apply_sandbox_design.json
```

It requires one manually supplied product, locale, and field through environment variables:

```env
SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID=gid://shopify/Product/...
SHOPIFY_TRANSLATION_SANDBOX_LOCALE=ja
SHOPIFY_TRANSLATION_SANDBOX_FIELD=meta_title
```

It writes local sandbox runner reports only:

```text
logs/shopify_translation_single_field_apply_sandbox_runner.json
logs/shopify_translation_single_field_apply_sandbox_runner.html
```

The sandbox runner is forced dry-run only. It accepts exactly 1 product, 1 locale, and 1 field, and the only allowed field is `meta_title`. It must not read product ID batch files, auto-scan Shopify products, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, write the database, or git push.

The sandbox runner must explicitly report `real_write_allowed=false`, `real_write_attempted=false`, `translations_register_allowed=false`, `translations_register_called=false`, `command_executed=false`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Single-Field Apply Preflight Package

`shopify_translation_single_field_apply_preflight_package` reads only the sandbox runner report:

```text
logs/shopify_translation_single_field_apply_sandbox_runner.json
```

It requires one manually supplied product, locale, field, and proposed value through environment variables:

```env
SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID=gid://shopify/Product/...
SHOPIFY_TRANSLATION_SANDBOX_LOCALE=ja
SHOPIFY_TRANSLATION_SANDBOX_FIELD=meta_title
SHOPIFY_TRANSLATION_SANDBOX_PROPOSED_VALUE=Concise SEO title
```

It writes local preflight package reports only:

```text
logs/shopify_translation_single_field_apply_preflight_package.json
logs/shopify_translation_single_field_apply_preflight_package.html
```

The preflight package is preflight-only. It accepts exactly 1 product, 1 locale, and 1 field, and the only allowed field is `meta_title`. The proposed value must be non-empty and no longer than 60 characters. The requested scope must match the previous sandbox runner report exactly.

The preflight package task must not call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, write the database, or git push. It must explicitly report `real_write_allowed=false`, `real_write_attempted=false`, `translations_register_allowed=false`, `translations_register_called=false`, `command_executed=false`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Single-Field Backup Fetch

`shopify_translation_single_field_backup_fetch` reads only the preflight package:

```text
logs/shopify_translation_single_field_apply_preflight_package.json
```

It requires one manually supplied product, locale, and field through environment variables:

```env
SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID=gid://shopify/Product/...
SHOPIFY_TRANSLATION_SANDBOX_LOCALE=ja
SHOPIFY_TRANSLATION_SANDBOX_FIELD=meta_title
```

It writes local backup fetch reports only:

```text
logs/shopify_translation_single_field_backup_fetch.json
logs/shopify_translation_single_field_backup_fetch.html
```

The backup fetch task is read-only. It accepts exactly 1 product, 1 locale, and 1 field, and the only allowed field is `meta_title`. The requested scope must match the previous preflight package exactly, and the preflight package must be `ready_for_manual_review`.

This task may perform one read-only Shopify GraphQL `translatableResource` query to fetch the current `meta_title` translation for the requested locale, or the current translatable source value if the locale translation is missing. It must not scan products, read multiple locales, read multiple fields, call mutations, call `translationsRegister`, publish, apply, update, write the database, or git push.

The backup report includes a readback plan and rollback plan for a future separate write task. It must explicitly report `real_write_allowed=false`, `translations_register_allowed=false`, `translations_register_called=false`, `mutation_performed=false`, `shopify_mutations_called=[]`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Single-Field Readback / Rollback Plan

`shopify_translation_single_field_readback_rollback_plan` reads only local reports:

```text
logs/shopify_translation_single_field_apply_preflight_package.json
logs/shopify_translation_single_field_backup_fetch.json
```

It writes local readback / rollback plan reports only:

```text
logs/shopify_translation_single_field_readback_rollback_plan.json
logs/shopify_translation_single_field_readback_rollback_plan.html
```

The plan task accepts exactly 1 product, 1 locale, and 1 field from the source reports. The only allowed field is `meta_title`, and the preflight scope must match the backup scope exactly.

The plan task must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. If the backup fetch report shows `read_only_shopify_query_performed=false`, the plan must mark `backup_source_is_verified=false` and use a non-write-ready status such as `needs_verified_backup`.

The readback plan must require a future separate write task to reread only the same product / locale / `meta_title` and compare the Shopify value to the proposed value. The rollback plan must require a verified backup value from the backup fetch report and must stay limited to the same product / locale / `meta_title`.

The plan must explicitly report `shopify_api_call_performed=false`, `readback_performed=false`, `rollback_performed=false`, `real_write_allowed=false`, `translations_register_allowed=false`, `translations_register_called=false`, `mutation_performed=false`, `shopify_mutations_called=[]`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Single-Field Final Write Gate

`shopify_translation_single_field_final_write_gate` reads only local reports:

```text
logs/shopify_translation_single_field_apply_preflight_package.json
logs/shopify_translation_single_field_backup_fetch.json
logs/shopify_translation_single_field_readback_rollback_plan.json
```

It writes local final gate package reports only:

```text
logs/shopify_translation_single_field_final_write_gate.json
logs/shopify_translation_single_field_final_write_gate.html
```

The final gate task accepts exactly 1 product, 1 locale, and 1 field from the source reports. The only allowed field is `meta_title`; the proposed value must be non-empty and no longer than 60 characters; the backup must be verified by a completed read-only query; and the readback / rollback plan must be in a safe ready status such as `ready_for_manual_review`.

The final gate task must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It may output `ready_for_human_final_approval` or `ready_for_final_write_gate_review`, but it must never output `ready_for_real_write`, `write_allowed`, or `execution_allowed`.

The final gate package must make clear that a future separate write task would call Shopify `translationsRegister`, would be limited to 1 product x 1 locale x 1 field=`meta_title`, would require immediate readback verification, and would require a separate rollback approval if readback fails.

The final gate must explicitly report `final_real_write_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `readback_performed=false`, `rollback_performed=false`, `translations_register_allowed=false`, `translations_register_called=false`, `mutation_performed=false`, `shopify_mutations_called=[]`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Single-Field Real Write Runner Design

`shopify_translation_single_field_real_write_runner_design` reads only local reports:

```text
logs/shopify_translation_single_field_apply_preflight_package.json
logs/shopify_translation_single_field_backup_fetch.json
logs/shopify_translation_single_field_readback_rollback_plan.json
logs/shopify_translation_single_field_final_write_gate.json
```

It writes local runner design reports only:

```text
logs/shopify_translation_single_field_real_write_runner_design.json
logs/shopify_translation_single_field_real_write_runner_design.html
```

The design task accepts exactly 1 product, 1 locale, and 1 field from the source reports. The only allowed field is `meta_title`; the proposed value must be non-empty and no longer than 60 characters; the backup must be verified; and the final write gate must be ready while still reporting `final_real_write_allowed=false`.

The design task must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, git push, or generate directly executable real-write commands. It may describe a future runner only.

The future runner design must require the later real-write phase to reject batch mode, multiple products, multiple locales, multiple fields, and any field other than `meta_title`. It must require a verified backup, final gate readiness, the dangerous flag `--i-understand-this-writes-shopify`, immediate readback after a future write, and a separate rollback approval if readback fails.

The design task must explicitly report `design_only=true`, `final_real_write_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `readback_performed=false`, `rollback_performed=false`, `translations_register_allowed=false`, `translations_register_called=false`, `mutation_performed=false`, `shopify_mutations_called=[]`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.

### Single-Field Real Write Locked Runner

`shopify_translation_single_field_real_write_locked_runner` reads only local reports and manually supplied environment variables:

```text
logs/shopify_translation_single_field_apply_preflight_package.json
logs/shopify_translation_single_field_backup_fetch.json
logs/shopify_translation_single_field_readback_rollback_plan.json
logs/shopify_translation_single_field_final_write_gate.json
logs/shopify_translation_single_field_real_write_runner_design.json
```

Required environment variables:

```env
SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID=gid://shopify/Product/...
SHOPIFY_TRANSLATION_SANDBOX_LOCALE=ja
SHOPIFY_TRANSLATION_SANDBOX_FIELD=meta_title
SHOPIFY_TRANSLATION_SANDBOX_PROPOSED_VALUE=Concise SEO title
```

Optional dangerous flag:

```env
SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true
```

The optional dangerous flag is recorded for review only. It is not effective in this phase and must never unlock a Shopify write.

The locked runner writes local reports only:

```text
logs/shopify_translation_single_field_real_write_locked_runner.json
logs/shopify_translation_single_field_real_write_locked_runner.html
```

The locked runner validates that the preflight package, verified backup, readback / rollback plan, final gate package, design package, and environment scope are consistent for exactly 1 product, 1 locale, and field `meta_title`.

Even when every precondition passes, this task may only output `locked_not_executed` or `ready_but_locked`. It must never output `ready_for_real_write`, `write_allowed`, `execution_allowed`, or `real_write_allowed`.

The locked runner must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, execute commands, publish, apply, update, write the database, or git push. It must explicitly report `locked_shell=true`, `dangerous_flag_effective=false`, `final_real_write_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `command_executed=false`, `readback_performed=false`, `rollback_performed=false`, `real_apply_performed=false`, and `shopify_write_performed=false`.

### Single-Field Real Write Pre-Execution Validation

`shopify_translation_single_field_real_write_pre_execution_validate` reads only local reports and manually supplied environment variables:

```text
logs/shopify_translation_single_field_apply_preflight_package.json
logs/shopify_translation_single_field_backup_fetch.json
logs/shopify_translation_single_field_readback_rollback_plan.json
logs/shopify_translation_single_field_final_write_gate.json
logs/shopify_translation_single_field_real_write_runner_design.json
logs/shopify_translation_single_field_real_write_locked_runner.json
```

Required environment variables:

```env
SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID=gid://shopify/Product/...
SHOPIFY_TRANSLATION_SANDBOX_LOCALE=ja
SHOPIFY_TRANSLATION_SANDBOX_FIELD=meta_title
SHOPIFY_TRANSLATION_SANDBOX_PROPOSED_VALUE=Concise SEO title
SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true
```

The dangerous flag is a validation precondition only. It never triggers a write in this phase.

The task writes local reports only:

```text
logs/shopify_translation_single_field_real_write_pre_execution_validate.json
logs/shopify_translation_single_field_real_write_pre_execution_validate.html
```

The validator checks that the preflight package, verified backup, readback / rollback plan, final gate, design package, locked runner, and environment scope are consistent for exactly 1 product, 1 locale, and field `meta_title`. It also checks the proposed value matches across all source reports and the environment.

If all checks pass and the dangerous flag is exactly `true`, the task may output `ready_for_manual_write_approval` or `pre_execution_validation_passed_pending_human_approval`. It must never output `ready_for_real_write`, `write_allowed`, `execution_allowed`, or `real_write_allowed`.

The pre-execution validator must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, execute commands, publish, apply, update, write the database, or git push. It must explicitly report `pre_execution_validation_only=true`, `write_execution_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `command_executed=false`, `readback_performed=false`, `rollback_performed=false`, `real_apply_performed=false`, and `shopify_write_performed=false`.

### Single-Field Final Human Approval Package

`shopify_translation_single_field_final_human_approval_package` reads only local reports and manually supplied environment variables:

```text
logs/shopify_translation_single_field_apply_preflight_package.json
logs/shopify_translation_single_field_backup_fetch.json
logs/shopify_translation_single_field_readback_rollback_plan.json
logs/shopify_translation_single_field_final_write_gate.json
logs/shopify_translation_single_field_real_write_runner_design.json
logs/shopify_translation_single_field_real_write_locked_runner.json
logs/shopify_translation_single_field_real_write_pre_execution_validate.json
```

Required environment variables:

```env
SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID=gid://shopify/Product/...
SHOPIFY_TRANSLATION_SANDBOX_LOCALE=ja
SHOPIFY_TRANSLATION_SANDBOX_FIELD=meta_title
SHOPIFY_TRANSLATION_SANDBOX_PROPOSED_VALUE=Concise SEO title
SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true
```

The task writes local reports only:

```text
logs/shopify_translation_single_field_final_human_approval_package.json
logs/shopify_translation_single_field_final_human_approval_package.html
```

The package checks that the preflight package, verified backup, readback / rollback plan, final gate, design package, locked runner, pre-execution validation, and environment scope are consistent for exactly 1 product, 1 locale, and field `meta_title`.

If every check passes, the task may output `ready_for_final_human_review` or `ready_for_phase_12_manual_approval_review`. It must never output `ready_for_real_write`, `write_allowed`, `execution_allowed`, or `real_write_allowed`. Phase 12 must still be a separate task and must require a new explicit human confirmation.

The final human approval package must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, execute commands, publish, apply, update, write the database, or git push. It must explicitly report `final_human_approval_package_only=true`, `phase_12_entry_allowed=false`, `write_execution_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `command_executed=false`, `readback_performed=false`, `rollback_performed=false`, `real_apply_performed=false`, and `shopify_write_performed=false`.

### Single-Field Real Write Runner Final-Safe Shell

`shopify_translation_single_field_real_write_runner_final_safe_shell` reads only local reports and manually supplied environment variables:

```text
logs/shopify_translation_single_field_apply_preflight_package.json
logs/shopify_translation_single_field_backup_fetch.json
logs/shopify_translation_single_field_readback_rollback_plan.json
logs/shopify_translation_single_field_final_write_gate.json
logs/shopify_translation_single_field_real_write_runner_design.json
logs/shopify_translation_single_field_real_write_locked_runner.json
logs/shopify_translation_single_field_real_write_pre_execution_validate.json
logs/shopify_translation_single_field_final_human_approval_package.json
```

Required environment variables:

```env
SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID=gid://shopify/Product/...
SHOPIFY_TRANSLATION_SANDBOX_LOCALE=ja
SHOPIFY_TRANSLATION_SANDBOX_FIELD=meta_title
SHOPIFY_TRANSLATION_SANDBOX_PROPOSED_VALUE=Concise SEO title
SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true
```

Optional review-only ack:

```env
SHOPIFY_TRANSLATION_PHASE_12_FINAL_SAFE_SHELL_ACK=true
```

The ack is not effective for writing. The task writes local reports only:

```text
logs/shopify_translation_single_field_real_write_runner_final_safe_shell.json
logs/shopify_translation_single_field_real_write_runner_final_safe_shell.html
```

The final-safe shell validates that all prior reports, the verified backup, final gate, pre-execution validation, final human approval package, and environment scope are consistent for exactly 1 product, 1 locale, and field `meta_title`.

If every check passes, the task may output `final_safe_shell_ready_for_manual_review` or `ready_for_phase_12_1_design_review`. It must never output `ready_for_real_write`, `write_allowed`, `execution_allowed`, `real_write_allowed`, or `phase_12_entry_allowed`. Phase 12.1 must still be a separate task and must require a new explicit human confirmation.

The final-safe shell must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, execute commands, publish, apply, update, write the database, or git push. It must explicitly report `final_safe_shell_only=true`, `phase_12_1_entry_allowed=false`, `phase_12_entry_allowed=false`, `write_execution_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `command_executed=false`, `readback_performed=false`, `rollback_performed=false`, `real_apply_performed=false`, and `shopify_write_performed=false`.

### Single-Field Real Write Execution Plan

`shopify_translation_single_field_real_write_execution_plan` reads only local reports and manually supplied environment variables:

```text
logs/shopify_translation_single_field_apply_preflight_package.json
logs/shopify_translation_single_field_backup_fetch.json
logs/shopify_translation_single_field_readback_rollback_plan.json
logs/shopify_translation_single_field_final_write_gate.json
logs/shopify_translation_single_field_real_write_runner_design.json
logs/shopify_translation_single_field_real_write_locked_runner.json
logs/shopify_translation_single_field_real_write_pre_execution_validate.json
logs/shopify_translation_single_field_final_human_approval_package.json
logs/shopify_translation_single_field_real_write_runner_final_safe_shell.json
```

Required environment variables:

```env
SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID=gid://shopify/Product/...
SHOPIFY_TRANSLATION_SANDBOX_LOCALE=ja
SHOPIFY_TRANSLATION_SANDBOX_FIELD=meta_title
SHOPIFY_TRANSLATION_SANDBOX_PROPOSED_VALUE=Concise SEO title
SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true
SHOPIFY_TRANSLATION_PHASE_12_FINAL_SAFE_SHELL_ACK=true
SHOPIFY_TRANSLATION_PHASE_12_1A_PLAN_ACK=true
```

The task writes local execution plan reports only:

```text
logs/shopify_translation_single_field_real_write_execution_plan.json
logs/shopify_translation_single_field_real_write_execution_plan.html
```

The execution plan validates that all prior reports, the final-safe shell, verified backup, final gate, final human approval package, and environment scope are consistent for exactly 1 product, 1 locale, and field `meta_title`.

If every check passes, the task may output `execution_plan_ready_for_manual_review` or `ready_for_phase_12_1b_manual_review`. It may include a `translationsRegister` payload preview, but that preview is not executable and must keep `payload_preview_only=true` and `translations_register_called=false`.

The execution plan must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, execute commands, publish, apply, update, write the database, or git push. It must explicitly report `execution_plan_only=true`, `payload_preview_only=true`, `phase_12_1b_entry_allowed=false`, `phase_12_1_entry_allowed=false`, `phase_12_entry_allowed=false`, `write_execution_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `command_executed=false`, `readback_performed=false`, `rollback_performed=false`, `real_apply_performed=false`, and `shopify_write_performed=false`.

### Single-Field Real Write One-Shot Locked Shell

`shopify_translation_single_field_real_write_one_shot_locked_shell` reads only local reports and manually supplied environment variables:

```text
logs/shopify_translation_single_field_apply_preflight_package.json
logs/shopify_translation_single_field_backup_fetch.json
logs/shopify_translation_single_field_readback_rollback_plan.json
logs/shopify_translation_single_field_final_write_gate.json
logs/shopify_translation_single_field_real_write_runner_design.json
logs/shopify_translation_single_field_real_write_locked_runner.json
logs/shopify_translation_single_field_real_write_pre_execution_validate.json
logs/shopify_translation_single_field_final_human_approval_package.json
logs/shopify_translation_single_field_real_write_runner_final_safe_shell.json
logs/shopify_translation_single_field_real_write_execution_plan.json
```

Required environment variables:

```env
SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID=gid://shopify/Product/...
SHOPIFY_TRANSLATION_SANDBOX_LOCALE=ja
SHOPIFY_TRANSLATION_SANDBOX_FIELD=meta_title
SHOPIFY_TRANSLATION_SANDBOX_PROPOSED_VALUE=Concise SEO title
SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true
SHOPIFY_TRANSLATION_PHASE_12_FINAL_SAFE_SHELL_ACK=true
SHOPIFY_TRANSLATION_PHASE_12_1A_PLAN_ACK=true
```

Review-only locked-shell ack:

```env
SHOPIFY_TRANSLATION_PHASE_12_1B_LOCKED_SHELL_ACK=true
```

The task writes local locked shell reports only:

```text
logs/shopify_translation_single_field_real_write_one_shot_locked_shell.json
logs/shopify_translation_single_field_real_write_one_shot_locked_shell.html
```

The one-shot locked shell validates that all prior reports, execution plan, verified backup, final human approval, final-safe shell, and environment scope are consistent for exactly 1 product, 1 locale, and field `meta_title`.

If every check passes, the task may output `one_shot_locked_ready_for_manual_review` or `ready_for_real_write_shell_review_but_locked`. It must never output `ready_for_real_write`, `write_allowed`, `execution_allowed`, `real_write_allowed`, `phase_12_entry_allowed`, `phase_12_1_entry_allowed`, or `phase_12_1b_entry_allowed`.

The one-shot locked shell must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, execute commands, publish, apply, update, write the database, or git push. It must explicitly report `one_shot_locked_shell_only=true`, `phase_12_1b_real_execution_allowed=false`, `phase_12_1b_entry_allowed=false`, `phase_12_1_entry_allowed=false`, `phase_12_entry_allowed=false`, `write_execution_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `command_executed=false`, `readback_performed=false`, `rollback_performed=false`, `real_apply_performed=false`, and `shopify_write_performed=false`.

### Single-Field Real Write One-Shot Execute

`shopify_translation_single_field_real_write_one_shot_execute` reads the full local single-field report chain through the one-shot locked shell plus manually supplied environment variables.

Fixed allowed scope:

```text
product_id: gid://shopify/Product/7655686799427
locale: ja
field: meta_title
proposed_value: MOFLY P-51D Aileron Link Connector
```

Required environment variables:

```env
SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID=gid://shopify/Product/7655686799427
SHOPIFY_TRANSLATION_SANDBOX_LOCALE=ja
SHOPIFY_TRANSLATION_SANDBOX_FIELD=meta_title
SHOPIFY_TRANSLATION_SANDBOX_PROPOSED_VALUE=MOFLY P-51D Aileron Link Connector
SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true
SHOPIFY_TRANSLATION_PHASE_12_FINAL_SAFE_SHELL_ACK=true
SHOPIFY_TRANSLATION_PHASE_12_1A_PLAN_ACK=true
SHOPIFY_TRANSLATION_PHASE_12_1B_LOCKED_SHELL_ACK=true
SHOPIFY_TRANSLATION_PHASE_12_1B_REAL_EXECUTION_ACK=YES_I_APPROVE_ONE_REAL_SHOPIFY_TRANSLATION_WRITE
```

Supported modes are `dry-run`, `real-run`, and `execute-real-write`. In `dry-run`, this task must never call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, execute commands, publish, apply, update, write the database, or git push. Dry-run must report `translations_register_called=false`, `shopify_write_performed=false`, `mutation_performed=false`, `shopify_api_call_performed=false`, `readback_performed=false`, `real_apply_performed=false`, and `all_no_write_confirmed=true`.

Only an explicitly requested future `real-run` or `execute-real-write` command may attempt exactly one Shopify `translationsRegister` mutation for the fixed scope above. Real-run must immediately read back the same product / locale / field and mark success only when the readback value exactly matches the proposed value. Rollback must never be automatic; failures must preserve the verified backup and require a separate rollback approval flow.

### Single-Field Post-Write Audit Package

`shopify_translation_single_field_post_write_audit_package` reads only local JSON reports:

- `logs/shopify_translation_single_field_apply_preflight_package.json`
- `logs/shopify_translation_single_field_backup_fetch.json`
- `logs/shopify_translation_single_field_readback_rollback_plan.json`
- `logs/shopify_translation_single_field_final_write_gate.json`
- `logs/shopify_translation_single_field_real_write_pre_execution_validate.json`
- `logs/shopify_translation_single_field_final_human_approval_package.json`
- `logs/shopify_translation_single_field_real_write_execution_plan.json`
- `logs/shopify_translation_single_field_real_write_one_shot_execute.json`

It writes:

```text
logs/shopify_translation_single_field_post_write_audit_package.json
logs/shopify_translation_single_field_post_write_audit_package.html
```

The audit must confirm the source execution report succeeded for exactly `gid://shopify/Product/7655686799427`, locale `ja`, field `meta_title`, with backup value `MOFLY P-51D Aileron Linkage Connector | RC Plane Clevis` and written/readback value `MOFLY P-51D Aileron Link Connector`.

This audit is local-report-only. It must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. The audit report may preserve source execution facts such as `source_shopify_write_performed=true`, `source_translations_register_called=true`, `source_mutation_performed=true`, and `source_readback_performed=true`, but the audit task itself must report `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### Single-Field Rollback Approval Package

`shopify_translation_single_field_rollback_approval_package` reads only local JSON reports:

- `logs/shopify_translation_single_field_backup_fetch.json`
- `logs/shopify_translation_single_field_readback_rollback_plan.json`
- `logs/shopify_translation_single_field_real_write_one_shot_execute.json`
- `logs/shopify_translation_single_field_post_write_audit_package.json`

It writes:

```text
logs/shopify_translation_single_field_rollback_approval_package.json
logs/shopify_translation_single_field_rollback_approval_package.html
```

The rollback approval package describes only a possible future restore from the current value `MOFLY P-51D Aileron Link Connector` back to the verified backup value `MOFLY P-51D Aileron Linkage Connector | RC Plane Clevis` for exactly `gid://shopify/Product/7655686799427`, locale `ja`, field `meta_title`.

This task must not execute rollback, call Shopify APIs, call mutations, call `translationsRegister`, perform readback, publish, apply, update, write the database, or git push. It must output `rollback_approval_package_ready_for_manual_review` only when the source execution succeeded, the post-write audit passed, the backup is verified, the scope matches, no rollback was already performed, and source readback matched the written value. It must report `rollback_approval_package_only=true`, `rollback_execution_allowed=false`, `rollback_performed=false`, `automatic_rollback_performed=false`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### Second Single-Field Test Preparation

`shopify_translation_second_single_field_test_prepare` reads only local JSON reports:

- `logs/shopify_translation_single_field_post_write_audit_package.json`
- `logs/shopify_translation_single_field_rollback_approval_package.json`
- `logs/shopify_translation_single_field_real_write_one_shot_execute.json`
- `logs/shopify_translation_single_field_backup_fetch.json`

It also reads manually supplied second-test scope environment variables:

```env
SHOPIFY_TRANSLATION_SECOND_TEST_PRODUCT_ID=
SHOPIFY_TRANSLATION_SECOND_TEST_LOCALE=
SHOPIFY_TRANSLATION_SECOND_TEST_FIELD=meta_title
SHOPIFY_TRANSLATION_SECOND_TEST_PROPOSED_VALUE=
```

It writes:

```text
logs/shopify_translation_second_single_field_test_prepare.json
logs/shopify_translation_second_single_field_test_prepare.html
```

If any second-test scope variable is missing, the task must output `blocked_missing_second_test_scope` or `needs_second_test_scope`. It must not guess a product, must not automatically reuse the first-test product as a real plan, and must not scan Shopify. When the supplied scope is complete, it may output `second_single_field_test_prepare_ready_for_manual_review` only for exactly one product, one locale, one field `meta_title`, and proposed value length <= 60.

This task must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It must state that the second test needs a fresh verified backup and the full safety chain again before any future real write. It must report `second_test_prepare_only=true`, `second_test_real_write_allowed=false`, `batch_mode_allowed=false`, `full_store_scan_allowed=false`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### Second Single-Field Verified Backup Fetch

`shopify_translation_second_single_field_verified_backup_fetch` reads:

- `logs/shopify_translation_second_single_field_test_prepare.json`

It also reads the manually supplied second-test scope environment variables:

```env
SHOPIFY_TRANSLATION_SECOND_TEST_PRODUCT_ID=
SHOPIFY_TRANSLATION_SECOND_TEST_LOCALE=
SHOPIFY_TRANSLATION_SECOND_TEST_FIELD=meta_title
SHOPIFY_TRANSLATION_SECOND_TEST_PROPOSED_VALUE=
```

It writes:

```text
logs/shopify_translation_second_single_field_verified_backup_fetch.json
logs/shopify_translation_second_single_field_verified_backup_fetch.html
```

This task may perform exactly one read-only Shopify GraphQL `translatableResource` query to fetch the current online value for the prepared second-test scope. It must block with `blocked_missing_second_test_prepare_report` if the prepare report is missing, `blocked_second_test_prepare_not_ready` if the prepare report is not ready, `blocked_missing_second_test_scope` when any required environment variable is missing, `blocked_scope_mismatch` when environment scope differs from the prepare report, `blocked_invalid_field` for any field other than `meta_title`, and `blocked_backup_query_failed` if the read-only query fails.

The verified backup fetch must not write Shopify, call mutations, call `translationsRegister`, perform rollback, perform readback beyond the backup query, publish, apply, update, batch, scan the store, write the database, or git push. On success it must output `backup_fetch_status=second_verified_backup_ready`, `second_backup_source_is_verified=true`, `read_only_shopify_query_performed=true`, and keep `second_test_real_write_allowed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### Second Single-Field Real Write Readiness

`shopify_translation_second_single_field_real_write_readiness` reads only local JSON reports:

- `logs/shopify_translation_second_single_field_test_prepare.json`
- `logs/shopify_translation_second_single_field_verified_backup_fetch.json`

It also reads the manually supplied second-test scope environment variables:

```env
SHOPIFY_TRANSLATION_SECOND_TEST_PRODUCT_ID=
SHOPIFY_TRANSLATION_SECOND_TEST_LOCALE=
SHOPIFY_TRANSLATION_SECOND_TEST_FIELD=meta_title
SHOPIFY_TRANSLATION_SECOND_TEST_PROPOSED_VALUE=
```

It writes:

```text
logs/shopify_translation_second_single_field_real_write_readiness.json
logs/shopify_translation_second_single_field_real_write_readiness.html
```

This task is the final human readiness package for the second one-shot single-field real write. It must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, batch, scan the store, write the database, or git push. It does not create an execution preview or locked shell.

The readiness task must require the environment scope to match both the Phase 12.4 prepare report and Phase 12.5 verified backup report exactly. It must block missing prepare reports, missing verified backup reports, prepare-not-ready reports, backup-not-ready reports, missing scope, scope mismatch, any field other than `meta_title`, empty proposed value, proposed value over 60 characters, and unverified backup reports.

On success it may output `readiness_status=second_real_write_ready_for_human_approval`, but it must still keep `readiness_package_only=true`, `second_test_real_write_allowed=false`, `human_approval_required_before_real_write=true`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### Second Single-Field Real Write Execute

`shopify_translation_second_single_field_real_write_execute` reads only local JSON reports before any eligible real-run path:

- `logs/shopify_translation_second_single_field_test_prepare.json`
- `logs/shopify_translation_second_single_field_verified_backup_fetch.json`
- `logs/shopify_translation_second_single_field_real_write_readiness.json`

It also reads the manually supplied second-test scope environment variables and the second real execution ACK:

```env
SHOPIFY_TRANSLATION_SECOND_TEST_PRODUCT_ID=gid://shopify/Product/7655686799427
SHOPIFY_TRANSLATION_SECOND_TEST_LOCALE=ja
SHOPIFY_TRANSLATION_SECOND_TEST_FIELD=meta_title
SHOPIFY_TRANSLATION_SECOND_TEST_PROPOSED_VALUE=MOFLY P-51D Aileron Link Connector Test
SHOPIFY_TRANSLATION_SECOND_TEST_REAL_EXECUTION_ACK=YES_I_APPROVE_SECOND_REAL_SHOPIFY_TRANSLATION_WRITE
```

It writes:

```text
logs/shopify_translation_second_single_field_real_write_execute.json
logs/shopify_translation_second_single_field_real_write_execute.html
```

Supported modes are `dry-run`, `real-run`, and `execute-real-write`. In `dry-run`, this task must never call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, execute commands, publish, apply, update, write the database, or git push. Dry-run must output `execution_status=dry_run_second_real_write_not_executed` when all preconditions pass, and must report `translations_register_called=false`, `shopify_write_performed=false`, `mutation_performed=false`, `shopify_api_call_performed=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `bulk_write_performed=false`, and `all_new_actions_no_write_confirmed=true`.

Only an explicitly requested future `real-run` or `execute-real-write` command may attempt exactly one Shopify `translationsRegister` mutation for `gid://shopify/Product/7655686799427`, locale `ja`, field `meta_title`, proposed value `MOFLY P-51D Aileron Link Connector Test`, after the prepare, verified backup, readiness, scope, and ACK checks all pass. Real-run must immediately read back the same product / locale / field and mark success only when the readback value exactly matches the proposed value. Rollback must never be automatic; readback mismatch must output `second_real_write_completed_but_readback_mismatch` and require rollback approval.

### Second Single-Field Post-Write Audit Package

`shopify_translation_second_single_field_post_write_audit_package` reads the local Phase 12.7 execution report:

- `logs/shopify_translation_second_single_field_real_write_execute.json`

It may also read local reference reports:

- `logs/shopify_translation_second_single_field_verified_backup_fetch.json`
- `logs/shopify_translation_second_single_field_real_write_readiness.json`

It writes:

```text
logs/shopify_translation_second_single_field_post_write_audit_package.json
logs/shopify_translation_second_single_field_post_write_audit_package.html
```

This audit is local-report-only. It must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It may preserve Phase 12.7 source execution facts such as `source_shopify_write_performed=true`, `source_translations_register_called=true`, `source_mutation_performed=true`, and `source_readback_performed=true`, but the audit task itself must report `audit_package_only=true`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

The audit must pass only when the source execution report is task `shopify_translation_second_single_field_real_write_execute`, mode `real-run`, status `second_real_write_succeeded_and_verified`, scope `gid://shopify/Product/7655686799427` / `ja` / `meta_title`, proposed and readback value `MOFLY P-51D Aileron Link Connector Test`, exactly one real write, no bulk write, no publish, no automatic rollback, no rollback approval requirement, and empty source blocking conditions. On success it outputs `audit_status=second_post_write_audit_passed`, `rollback_needed=false`, `rollback_optional_restore_possible=true`, and `rollback_optional_restore_requires_separate_approval=true`.

### Small Batch Apply Plan Package

`shopify_translation_small_batch_apply_plan_package` reads the local second post-write audit report:

- `logs/shopify_translation_second_single_field_post_write_audit_package.json`

It may also read local reference reports:

- `logs/shopify_translation_second_single_field_real_write_execute.json`
- `logs/shopify_translation_second_single_field_verified_backup_fetch.json`

It writes:

```text
logs/shopify_translation_small_batch_apply_plan_package.json
logs/shopify_translation_small_batch_apply_plan_package.html
```

This task is a local plan package only. It must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. The generated plan must stay within one product, one locale, at most 5 translation entries, and allowed fields `meta_title` / `meta_description` only.

The default sample plan uses `gid://shopify/Product/7655686799427`, locale `ja`, current known `meta_title` value `MOFLY P-51D Aileron Link Connector Test`, and two entries: `meta_title=MOFLY P-51D Aileron Link Connector` plus `meta_description=High-quality replacement aileron linkage connector for MOFLY P-51D RC airplane repairs and maintenance.` On success it outputs `plan_status=small_batch_apply_plan_ready_for_manual_review`, `entry_count=2`, `manual_review_required=true`, `real_write_allowed=false`, and `next_step_requires_separate_execute_task=true`.

For local blocking tests only, `SHOPIFY_TRANSLATION_SMALL_BATCH_PLAN_TEST_SCENARIO=invalid-field` or `too-many-entries` may be used to exercise plan validation while still performing no Shopify actions.

### Small Batch Apply Execute

`shopify_translation_small_batch_apply_execute` reads:

- `logs/shopify_translation_small_batch_apply_plan_package.json`

It writes:

```text
logs/shopify_translation_small_batch_apply_execute.json
logs/shopify_translation_small_batch_apply_execute.html
```

Dry-run mode must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push.

In `dry-run` mode, a ready small batch plan outputs `execution_status=dry_run_small_batch_write_not_executed`, keeps `entry_count=2` for the sample plan, and reports `real_write_allowed=false`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `bulk_write_performed=false`, `real_apply_performed=false`, and `all_new_actions_no_write_confirmed=true`.

The future small batch execution ACK is:

```env
SHOPIFY_TRANSLATION_SMALL_BATCH_EXECUTION_ACK=YES_I_APPROVE_SMALL_BATCH_SHOPIFY_TRANSLATION_WRITE
```

Missing or invalid ACK blocks `real-run` / `execute-real-write`. A valid ACK is necessary but not sufficient: the source plan must still be ready, the runner must be invoked with local approval, the scope must remain one product / one locale / at most 5 entries, and fields must be limited to `meta_title` and `meta_description`.

When a future human explicitly runs `real-run` or `execute-real-write` with the correct ACK, the task performs one small-batch Shopify `translationsRegister` mutation, immediately reads back every planned entry, and can output `execution_status=small_batch_real_write_succeeded_and_verified` only when every readback value matches the proposed value. Readback mismatch must output `small_batch_real_write_completed_but_readback_mismatch`, require rollback approval, and never trigger automatic rollback. Bulk write, publish, full-store scan, unsupported fields, and scope expansion remain forbidden.

### Small Batch Post-Write Audit Package

`shopify_translation_small_batch_post_write_audit_package` reads:

- `logs/shopify_translation_small_batch_apply_execute.json`

It may also read:

- `logs/shopify_translation_small_batch_apply_plan_package.json`

It writes:

```text
logs/shopify_translation_small_batch_post_write_audit_package.json
logs/shopify_translation_small_batch_post_write_audit_package.html
```

This task is local-report-only. It must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It may preserve source execution facts from a prior successful small-batch real-run, but the audit task itself must report `audit_package_only=true`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

The audit passes only when the source execute report is task `shopify_translation_small_batch_apply_execute`, mode `real-run` or `execute-real-write`, status `small_batch_real_write_succeeded_and_verified`, product `gid://shopify/Product/7655686799427`, locale `ja`, `entry_count=2`, fields `meta_title` and `meta_description`, `translations_register_called=true`, `shopify_write_performed=true`, `mutation_performed=true`, `readback_performed=true`, `readback_all_entries_match=true`, `readback_matched_entry_count=2`, no rollback approval requirement, no rollback performed, no automatic rollback, no publish, no bulk write, `small_batch_write_performed=true`, and empty source blocking conditions.

### Small Batch Rollback Approval Package

`shopify_translation_small_batch_rollback_approval_package` reads:

- `logs/shopify_translation_small_batch_apply_plan_package.json`
- `logs/shopify_translation_small_batch_apply_execute.json`
- `logs/shopify_translation_small_batch_post_write_audit_package.json`

It writes:

```text
logs/shopify_translation_small_batch_rollback_approval_package.json
logs/shopify_translation_small_batch_rollback_approval_package.html
```

This task is local-report-only. It must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, perform restore, publish, apply, update, write the database, or git push. It may preserve source write facts from the prior successful small-batch real-run, but the rollback approval task itself must report `rollback_approval_package_only=true`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `restore_performed=false`, `publish_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

The package passes only when the source execute report is successful, the small-batch post-write audit has passed, product `gid://shopify/Product/7655686799427`, locale `ja`, `entry_count=2`, fields are exactly `meta_title` and `meta_description`, readback matched, no rollback is required, no rollback approval is currently required, and source blocking conditions are empty. If locally recorded restore values are incomplete, the package still generates for manual review but must output `restore_plan_status=restore_values_incomplete_manual_review_required`, `rollback_optional_restore_possible=false`, and `manual_backup_review_required=true` instead of guessing missing values.

### CSV/JSON Small Batch Apply Plan Package

`shopify_translation_csv_json_small_batch_apply_plan_package` reads one local input file:

```text
remote_approval/inputs/shopify_translation_small_batch_input.json
remote_approval/inputs/shopify_translation_small_batch_input.csv
```

If both input files exist, JSON is used and the report sets `input_source=json`. If only CSV exists, CSV is used. If neither exists, the task writes a blocked report with `plan_status=blocked_missing_input_file`.

The input rows must contain `product_id`, `locale`, `field`, and `proposed_value`. This Phase 14.0 package is limited to at most 5 entries, exactly one `gid://shopify/Product/...` product, exactly one locale `ja`, and fields `meta_title` / `meta_description` only. `meta_title` values must be <= 60 characters, `meta_description` values <= 160 characters, and proposed values must be non-empty.

It writes:

```text
logs/shopify_translation_csv_json_small_batch_apply_plan_package.json
logs/shopify_translation_csv_json_small_batch_apply_plan_package.html
```

This task is local-input-only. It must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. On success it outputs `plan_status=csv_json_small_batch_apply_plan_ready_for_manual_review`, `manual_review_required=true`, `real_write_allowed=false`, and `next_step_requires_separate_execute_task=true`. It must also report `plan_package_only=true`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `bulk_write_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### `System.Speech` Is Unavailable

The runner tries Windows PowerShell `System.Speech` for local voice prompts. If unavailable, it falls back to console text or a beep. Voice failure must not fail the task.

### Git Safety Risks

Run this before local commits or any later push request:

```powershell
python remote_approval_runner.py --task git_safety_check --mode dry-run
```

This task is read-only. It checks status, branch, ahead commits, changed/staged/untracked files, suspicious paths, and secret-risk patterns. It never runs `git add`, `git commit`, `git push`, `git reset`, `git restore`, `git clean`, or rebase.

## Safety Boundary

- Do not add `--command`.
- Do not use `shell=True`.
- Do not build commands from user input.
- All tasks must be registered in `task_registry`.
- Default to `dry-run`.
- Failures stop by default, except multi-locale dry-run tasks may continue through remaining locales or product/locale combinations while writes stay disabled.
- Write tasks must be separate tasks with explicit second confirmation.
- Git safety checks are advisory only and must not perform Git writes.
- Batch Shopify translation dry-run tasks must not auto-scan the whole store and are limited to 3 products and 5 locales.
- Batch Shopify translation dry-run summaries should include QA pass/warning/fail counts and keep QA gates in review-only mode.
