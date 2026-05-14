# AI Project Manager Runner

This folder contains a semi-automatic local workflow for using ChatGPT as the project manager, PowerShell as the runner, and `codex exec` as the non-interactive implementation agent.

The workflow is intentionally not full auto:

1. ChatGPT writes a scoped task.
2. The user saves that task as a markdown file under `ai_project_manager/tasks/`.
3. PowerShell runs `scripts/run_codex_task.ps1` with that task file.
4. The script combines `SAFETY_RULES.md`, the saved task, and a final-response footer, then passes the prompt to `codex exec` through stdin.
5. `codex exec` performs the work in the selected sandbox.
6. The user reviews `last_message.txt`, `full_output.txt`, git status files, and safety warnings from the run folder.
7. The user pastes the important result back to ChatGPT for review and next-step planning.
8. Any commit or push remains manual and only after human review.

Example dry run:

```powershell
.\scripts\run_codex_task.ps1 -TaskFile .\ai_project_manager\TASK_TEMPLATE.md -DryRun
```

Example real local run:

```powershell
.\scripts\run_codex_task.ps1 -TaskFile .\ai_project_manager\tasks\my_task.md
```

## Clipboard Runner Workflow

Copy a scoped Codex task to the Windows clipboard, then save and run it with the clipboard wrapper. The task name becomes `ai_project_manager/tasks/<Name>.md`; names may contain only letters, numbers, dash, underscore, and dot.

Example clipboard dry run:

```powershell
.\scripts\run_codex_clipboard_task.ps1 -Name my_task -DryRun
```

Run outputs are written under `logs/codex_runs/yyyyMMdd_HHmmss/` for review. The runner never stages, commits, pushes, restores, or resets files.

Do not use `--dangerously-bypass-approvals-and-sandbox` for this workflow. Keep sandboxing enabled and keep commit/push manual.
