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

The clipboard wrapper performs a preflight before saving or running anything:

- shows the clipboard length, first five preview lines, `-Name`, task save path, and runner path
- blocks short clipboard contents and command-like starts such as `cd`, `powershell`, `git`, `Get-Clipboard`, or `$taskPath`
- warns if the task does not include recommended structure keywords such as `Goal`, `Allowed`, `Validation`, and `Final response`
- asks `Proceed with this clipboard task? Type Y to continue`; `Y`, `YES`, `y`, or `yes` saves the task file and calls `run_codex_task.ps1`
- writes trace metadata into the saved task file so `task_used.md` can be traced back to the matching `-Name` task file

Use `-Force` only when intentionally skipping the interactive confirmation prompt. Basic clipboard safety checks still run. Use `-DryRun` to show the preview and intended paths without saving the task file or calling the Codex runner.

Example clipboard dry run:

```powershell
.\scripts\run_codex_clipboard_task.ps1 -Name my_task -DryRun
```

Run outputs are written under `logs/codex_runs/yyyyMMdd_HHmmss_<task-file-stem>/` for review when the task file stem can be safely used in a folder name. If the task name cannot be made safe, the runner falls back to `logs/codex_runs/yyyyMMdd_HHmmss/`. The runner never stages, commits, pushes, restores, or resets files.

At the end of each real run, the runner prints a copy-ready command that reads that exact run directory:

```powershell
$run = "C:\path\to\aftersales\logs\codex_runs\20260514_151234_my_task"
Get-Content "$run\last_message.txt" -Raw
Get-Content "$run\safety_warnings.txt" -Raw
Get-Content "$run\changed_files_after.txt" -Raw
Get-Content "$run\staged_files_after.txt" -Raw
git status --short --branch
git diff --cached --name-only
```

Use the exact `$run` path printed by the task that just finished. When multiple PowerShell windows run tasks in parallel, do not rely only on "latest" lookup patterns because another task may finish later and become the newest run. `logs/codex_runs/latest_run_path.txt` is only a convenience helper; for parallel tasks, use the exact per-run command printed by that runner.

## Reviewing a completed Codex run

Use the review helper with the exact per-run folder printed by the runner:

```powershell
$run = "C:\Users\xiang\OneDrive\桌面\aftersales\logs\codex_runs\YYYYMMDD_HHMMSS_taskname"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\review_codex_run.ps1 -RunPath $run
```

Add `-ShowFullOutput` to include `full_output.txt` after the main summary. Add `-OpenFolder` to open the run folder in Explorer.

Do not use `--dangerously-bypass-approvals-and-sandbox` for this workflow. Keep sandboxing enabled and keep commit/push manual.
