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

`no_shopify_writes_confirmed` is true only when that combination succeeds and stdout contains `Dry run complete. No Shopify writes performed.` The summary `all_no_write_confirmed` covers successful runs only; failed runs are not marked confirmed.

Allowed approval actions for this task are:

```text
Y / 1 = keep review files
SHOW_LOG = show recent logs
SUMMARY = show summary
N / 0 = stop
```

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
