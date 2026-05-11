# Local Approval Runner Skill

## Purpose

Use this skill in the Windows local environment to let Codex and PowerShell run fixed, registered tasks while pausing at key points for local voice and console approval. The default approval mode is local approval. Telegram remote approval may be added back later, but it is not the default workflow.

## Current Project Context

Project path: `aftersales`

Existing Remote / Local Approval Runner framework:

- `remote_approval_runner.py`
- `remote_approval/`
- `task_registry`
- `approval_runner`
- `approval_client`
- `demo` task
- `django_check` task
- `shopify_translation_dry_run` task

## Core Workflow

1. The user describes a larger task in ChatGPT.
2. ChatGPT breaks the task into concrete Codex instructions.
3. Codex modifies code or runs a fixed registered task.
4. PowerShell runs the task through the approval runner.
5. At key points, local voice prompts ask the user to review the console.
6. The user enters `Y`, `N`, `P`, `STOP`, `SHOW_LOG`, or `SUMMARY`.
7. The runner continues, pauses, stops, or shows logs based only on fixed options.
8. After completion, local voice prompts the user to review the result.

## Safety Rules

Always preserve these rules:

- Do not allow arbitrary PowerShell command input.
- Do not add a `--command` argument.
- Do not use `shell=True`.
- Do not build shell commands from user input.
- All tasks must be registered through `task_registry`.
- Default to `dry-run`.
- `shopify_translation_dry_run` must never write to Shopify.
- Do not publish translations, call mutation/write paths, update products, update tags, update price, or update inventory.
- Do not refund, cancel orders, bulk edit prices, or bulk edit inventory.
- Do not run `git push`, `git reset`, or `git restore` unless the user explicitly requests that exact operation.
- Do not read, print, or commit `.env` secrets.
- Tokens, chat IDs, API keys, and secrets must live in `.env`.
- On failure, stop by default and do not continue into write actions.

## Existing Fixed Tasks

- `demo`
- `django_check`
- `shopify_translation_dry_run`

## `django_check` Task

Fixed command:

```powershell
docker compose exec -T web python manage.py check
```

Requirements:

- Use `subprocess` list arguments.
- Do not use `shell=True`.
- If Docker permission is denied, stop and generate a review file.
- Do not run migrations.
- Do not run `collectstatic`.
- Do not modify the database.

## `shopify_translation_dry_run` Task

Requirements:

- Only allow `--mode dry-run`.
- Require `SHOPIFY_TRANSLATION_TEST_PRODUCT_ID`.
- Do not automatically scan many products.
- Reuse the existing `translate_shopify_product.py` management command in dry-run mode.
- Generate `logs/shopify_translation_dry_run_review.json`.
- Do not write to Shopify.

## Local Approval Mode

Default approval mode should be `local`.

CLI examples:

```powershell
python remote_approval_runner.py --task demo --mode dry-run
python remote_approval_runner.py --task demo --mode dry-run --approval local
python remote_approval_runner.py --task django_check --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_dry_run --mode dry-run --approval local
```

Telegram remains available only when explicitly selected, for example:

```powershell
python remote_approval_runner.py --task demo --mode dry-run --approval telegram
```

## Voice Prompt

On Windows, prefer PowerShell `System.Speech`.

If speech is unavailable, degrade to console text or beep. Do not fail the task just because voice output failed.

Approval prompt:

```text
Approval required. Please check the console.
```

Completion prompt:

```text
Task completed. Please review the summary.
```

Failure prompt:

```text
Task failed. Please check the log.
```

## Console Approval Options

Supported options:

- `Y` = approve / continue
- `N` = stop
- `P` = pause
- `STOP` = stop immediately
- `SHOW_LOG` = show recent log
- `SUMMARY` = show current summary

Legacy compatible options:

- `1` = approve / keep review
- `0` = stop

Do not interpret any console reply as a shell command.

## Pause Mode

If the user enters `P`:

- Pause the task.
- Voice prompt: `Task paused.`
- Show:

```text
C = continue
STOP = stop
SHOW_LOG = show recent log
SUMMARY = show current summary
```

If the user enters `C`, return to the approval flow. If the user enters `STOP`, stop the task.

## Interrupt Mode

Before task stages, check:

```text
logs/interrupt.flag
```

If the file exists:

- Pause the task.
- Voice prompt: `Interrupt requested. Task paused.`
- Show:

```text
C = continue and remove interrupt flag
STOP = stop task
SHOW_LOG = show recent log
SUMMARY = show current summary
```

If the user enters `C`, delete `logs/interrupt.flag` and continue. If the user enters `STOP`, stop the task.

## Logs

Continue writing:

- `logs/remote_approval.log`
- `logs/approval_history.jsonl`
- `logs/approval_state.json`

Recommended history fields:

- `approval_mode`
- `voice_prompt_sent`
- `interrupt_detected`
- `paused`
- `selected_action`
- `result`

## Future Phases

Possible future work:

1. Telegram true-device testing
2. Shopify translation test write
3. Second confirmation before any write
4. Read-only verification after writes
5. Shenzhen settlement check task
6. Remote approval mode

## Development Rule

If a future change adds an approval task, PowerShell fixed task, Shopify dry-run/write task, or Shenzhen settlement check task, update this skill in the same change.
