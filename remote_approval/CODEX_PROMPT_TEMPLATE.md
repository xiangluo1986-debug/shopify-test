# Codex Prompt Template

Copy and adapt this template when asking Codex App to perform a larger task in this project.

```text
Please handle this task using the Local Approval Runner workflow.

Workspace:
[path to clean worktree, for example aftersales-local-approval]

Branch:
codex/local-approval-runner

Goal:
[Describe the task clearly.]

Scope:
- Expected files/modules:
  - [file or module]
  - [file or module]
- Do not modify:
  - .env
  - logs/
  - backend/reviews/
  - unrelated Shopify translation files
  - unrelated scheduler logs

Risk level:
[low / medium / high]

Required workflow:
1. Restate the goal and risk level.
2. Split the work into 2-5 small phases.
3. State which files each phase may change.
4. Make minimal edits only.
5. Use fixed checks through Local Approval Runner.
6. Before commit or push preparation, run:
   python remote_approval_runner.py --task git_safety_check --mode dry-run --approval local
7. Stop and ask me if the task needs migration, database write, Shopify write, production data change, or unclear scope decisions.
8. Do not run git push.

Allowed checks:
python remote_approval_runner.py --list-tasks
python remote_approval_runner.py --task django_check --mode dry-run --approval local
python remote_approval_runner.py --task shopify_translation_dry_run --mode dry-run --approval local
python remote_approval_runner.py --task git_safety_check --mode dry-run --approval local

Approval options:
Y / 1 = approve
N / 0 = stop
P = pause
STOP = stop immediately
SHOW_LOG = show recent log
SUMMARY = show current summary

Hard safety rules:
- No arbitrary PowerShell command input.
- No --command.
- No shell=True.
- No command built from user input.
- Do not read or print .env secrets.
- Do not run Shopify writes, publish, mutation, product update, tag update, price update, inventory update, refunds, or order cancellation.
- Do not run migration or collectstatic unless I explicitly confirm.
- Do not run git push/reset/restore/clean/rebase unless I explicitly confirm that exact operation.
- Dry-run tasks must stay dry-run.

Final summary must include:
- Files changed
- Commands run
- Check results
- Risks or blockers
- Whether commit is recommended
- Suggested commit message
- Whether push is forbidden or requires explicit confirmation
```

## Small Task Variant

Use this shorter prompt for low-risk documentation or small code edits:

```text
Use the Local Approval Runner workflow.

Task:
[Describe the small task.]

Constraints:
- Minimal edits only.
- Do not touch .env, logs/, backend/reviews/, or unrelated files.
- Run git_safety_check before suggesting commit.
- Do not git push.

Final summary:
Files changed, checks run, risks, commit recommendation, suggested commit message.
```

## Shopify Dry-Run Variant

Use this for Shopify translation preview only:

```text
Use the Local Approval Runner workflow for Shopify translation dry-run only.

Task:
[Describe the product translation preview/check.]

Rules:
- No Shopify writes.
- No publish/mutation/update.
- One configured test product only.
- Use:
  python remote_approval_runner.py --task shopify_translation_dry_run --mode dry-run --approval local
- Then run:
  python remote_approval_runner.py --task git_safety_check --mode dry-run --approval local

Stop if product_id is missing, Docker is blocked, secrets are at risk, or any write action is needed.
```
