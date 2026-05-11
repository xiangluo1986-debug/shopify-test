# Local Approval Runner Workflow

## What It Is

Local Approval Runner is a Windows-first workflow for running fixed, registered project tasks from PowerShell with local human approval at key points. It is designed for the current ChatGPT -> Codex App -> PowerShell workflow: Codex prepares or runs a safe fixed task, the runner prompts locally, and the user approves, pauses, stops, or reviews logs from the console.

Telegram approval code is still present for future use, but local approval is the default.

## Good Fits

- Django checks after code changes.
- Shopify translation dry-runs for one configured test product.
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
python remote_approval_runner.py --task shopify_translation_dry_run --mode dry-run
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

### `System.Speech` Is Unavailable

The runner tries Windows PowerShell `System.Speech` for local voice prompts. If unavailable, it falls back to console text or a beep. Voice failure must not fail the task.

## Safety Boundary

- Do not add `--command`.
- Do not use `shell=True`.
- Do not build commands from user input.
- All tasks must be registered in `task_registry`.
- Default to `dry-run`.
- Failures stop by default.
- Write tasks must be separate tasks with explicit second confirmation.
