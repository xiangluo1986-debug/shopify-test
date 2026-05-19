# Aftersales Project Rules for Codex

## Project Context

This is the kidstoylover aftersales / Shopify integration / ticket system project.
The project includes:

- Django ticket system
- Shopify OAuth / sync / translation related features
- Shenzhen warehouse settlement and profit reporting
- Docker Compose local development environment
- Windows PowerShell / cloudflared local deployment workflows

Codex should prioritize safety, minimal edits, and read-only inspection before changes.

## General Safety Rules

- Do not read, print, expose, or copy `.env`, API keys, Shopify access tokens, Django `SECRET_KEY`, cloudflared tokens, database passwords, or any other secret.
- Do not write tokens or secrets into code, documentation, logs, shell output, or Git.
- Do not run destructive commands such as `flush`, `reset`, `drop`, `truncate`, `clean`, `prune`, or `docker compose down -v`.
- Do not run Git reset / revert / checkout to roll back user files unless the user explicitly asks for that exact operation.
- If `.git/index.lock Permission denied` or another Git permission problem appears, report it first. Do not force-delete lock files.
- Default to read-only inspection first, then explain the plan, then modify only the necessary files.
- Keep changes minimal and scoped. Do not refactor unrelated code.
- If the worktree has existing uncommitted changes, do not overwrite or mix unrelated changes.
- If a task involves Shopify writes, database migrations, data cleanup, settlement data updates, or bulk data fixes, explain the risk and wait for explicit confirmation.

## Default Workflow

1. Inspect related files and current state using read-only commands.
2. Summarize the problem and likely cause.
3. State which files will be changed and why.
4. Make the smallest necessary change.
5. After editing, report changed files, behavior changes, relevant diff or code paths, and commands the user should run.
6. If safe, run or request a low-risk validation command.

For local approval execution, PowerShell fixed tasks, Codex automation workflows, voice reminders, pause mode, or `logs/interrupt.flag` handling, refer to `.codex/skills/local-approval-runner/SKILL.md`.

## Completion Notification

- When Codex finishes a task, play a short sound notification from the Windows host PowerShell when possible so the user does not need to watch the screen.
- Use a success sound for completed work and a different lower/error sound if the task fails or is blocked.
- Do not rely only on sounds emitted inside Docker containers or Docker logs; they may not reach the Windows speaker.
- If a browser or OAuth flow needs notification, prefer browser-based audio or a host-side PowerShell wrapper.

## Django / Docker Validation

After Django code changes, prefer this validation command:

```powershell
docker compose exec -T web python manage.py check
```

Before running Docker / Django commands, show:

- command to run
- why it is needed
- whether it changes database or files
- risk level

Safe commands commonly used in this project:

```powershell
docker ps
docker compose ps
docker compose exec -T web python manage.py check
docker compose exec -T web python manage.py showmigrations
docker compose logs --tail=100 web
docker compose logs --tail=100 scheduler
```

Commands requiring extra confirmation:

```powershell
docker compose exec -T web python manage.py migrate
docker compose up -d --build
docker compose restart web
```

Never run:

```powershell
docker compose down -v
docker volume rm
docker system prune
python manage.py flush
```

## Deployment Command Policy

Normal development and internal task commands remain unchanged. Examples
include:

```powershell
docker compose exec -T web python manage.py check
python remote_approval_runner.py --task <task-name> --approval local
.\scripts\run_codex_clipboard_task.ps1
```

Django checks, Codex runner tasks, Review Request dry-runs, Translation
dry-runs, documentation updates, and read-only reports may continue to use
their existing task-specific commands as long as they do not deploy, restart,
switch traffic, write external systems, or expose secrets.

Deployment and update commands are special:

- Do not rely on manual `docker compose up -d --build` as the long-term
  deployment method.
- Use `scripts/safe_deploy.ps1` for the current deployment safety flow.
- After blue-green deployment is implemented and explicitly approved, use the
  future blue-green deployment script instead of the current safe deploy
  command.
- Production blue-green runtime execution is currently NOT ENABLED.
- Production blue-green apply is currently NO-GO.

Deployment lock rule:

- Any task that may build, restart, deploy, switch, clean up, or otherwise
  change the web runtime must use the deployment lock.
- Only one deployment or runtime-changing task may run at a time.
- If the lock exists, the second deployment task must stop and require a
  manual rerun after the current deploy completes.
- Do not auto-queue deployment tasks behind the lock.
- Normal non-deploy tasks are not blocked by the deployment lock.

New deployable project default rule:

- Add `/healthz/` or `/api/health` early.
- Add `scripts/safe_deploy.ps1` or `scripts/safe_deploy.sh`.
- Add `docs/SAFE_DEPLOY.md`.
- Add health check validation to the deploy flow.
- Add rollback and log inspection notes.
- Do not commit secrets, logs, local config, tokens, credentials, database
  dumps, or runtime state.
- Do not depend on unsafe manual deploy commands forever.

This default applies especially to Docker, Django, Shopify App, Node, and
Laravel projects.

Current blue-green status:

- Local inactive runtime validation: PASSED.
- Local/test proxy routing validation: PASSED.
- `safe_deploy` lock enforcement: active.
- Production apply: NO-GO.
- Runtime execution: NOT ENABLED.
- Future production apply requires separate implementation, review, deployment
  lock enforcement, and explicit approval.

## Shopify API / Token Rules

- Treat Shopify tokens as secrets. Never print them.
- Do not modify `.env` or token-related settings unless the user explicitly asks and confirms.
- Default Shopify API work should be read-only.
- Shopify writes, product updates, translation publishing, and bulk data changes require explicit user confirmation.
- For REST pagination, use the `Link` response header and only `rel="next"` page links with `page_info`.
- Do not parse pagination from the JSON body.
- Do not use cursor parameters for Shopify REST orders/products pagination.
- Handle Shopify `429 Too Many Requests` by respecting `Retry-After` and retrying with a bounded limit.
- For Shopify orders, preserve logic around `tags`, `line_items`, `note`, `note_attributes`, and `total_tip_received`.

## Shopify Review Request Automation Rules

- Phase 0 is integration preparation only: documentation, `.env.example` placeholders, checklist updates, and local safety notes.
- Phase 0.1 may add a read-only Shopify order tag discovery report, but it must not add sending logic or write Shopify data.
- Phase 0.2 is Ali Reviews / Kudosi capability discovery only: docs, support questions, dashboard checklist, and local reports.
- Phase 0.3 is Gmail / Trustpilot send permission readiness only: docs, `.env.example` placeholders, template draft, and local reports.
- Phase 0.4 is Shopify tag write permission readiness only: docs, planned tag names, scope checks, and local reports.
- Phase 1 candidate scanning is read-only, dry-run, and report-only. It may query recent Shopify orders for candidate classification, but must not send email, call Gmail, call Ali Reviews / Kudosi, write Shopify, run Shopify mutations, or modify tags.
- Phase 1.1 adds a read-only support ticket / risk filter before any future send or tag action. Review request automation must filter unresolved tickets, refund/return risks, shipping or delivery issues, complaints, disputes, and chargebacks before any customer-facing or Shopify-writing workflow.
- Phase 1.1 ticket matching may use raw email only in memory. Reports must mask customer emails and must not output ticket body, ticket comments, customer addresses, phone numbers, or full raw emails.
- Blocking or uncertain ticket status must move the order/customer to a blocked or manual-review bucket, not a ready-to-send bucket.
- No Ali Reviews / Kudosi API call is allowed until official API documentation, authentication method, and token handling are confirmed.
- No real Ali Reviews / Kudosi review request may be sent until send-by-order and sent-status API support are confirmed.
- If Ali Reviews / Kudosi cannot confirm send/status API support, future automation must only produce Shopify candidate reports and may require manual sending in the Ali Reviews dashboard.
- Never assume Shopify tag `1: reveiw request` means Ali Reviews / Kudosi has sent or has not sent the email; send/status must be confirmed from Ali Reviews / Kudosi before any action.
- No Gmail sending is allowed until Gmail OAuth and send permission for `info@kidstoylover.com` are confirmed.
- Gmail / Trustpilot automation must start with preview-only reports; no email may be sent during readiness or template phases.
- No email may be sent unless Gmail OAuth is configured, the sender is verified or authorized to send as `info@kidstoylover.com`, the customer is selected as repeat/high-value and not blocked by tickets/refunds/shipping issues, and final human approval is present.
- Use least-privilege Gmail scope `https://www.googleapis.com/auth/gmail.send` by default.
- Never use the Gmail API to read inbox or message contents unless a future phase explicitly approves a Gmail read scope.
- No Shopify `tagsAdd` or `tagsRemove` mutation is allowed until `write_orders` and `write_customers` scopes are confirmed for the relevant app.
- No Shopify tag write may run until scopes are confirmed and a dry-run tag plan is manually approved.
- Never update or overwrite the full Shopify `tags` field directly for review request automation.
- Use Shopify GraphQL Admin API `tagsAdd` and `tagsRemove` only for any later approved tag write phase.
- Phase 0.1 confirmed the exact existing Shopify order tag is `1: reveiw request`.
- `Delivered` is also confirmed as an exact existing Shopify order tag.
- Future review request automation must use exact string matching for Shopify tags.
- Never hard-code `1: review request` as the review request tag.
- First read real Shopify order tags through a read-only discovery report and use only the exact tag string returned by the Shopify API.
- Preserve the exact colon, spelling, spacing, and character width from Shopify tag values; do not normalize, correct, trim, translate, or rewrite tag strings.
- Treat `1: reveiw request` and `1: review request` as different tags.
- Treat half-width colon `:` / U+003A and full-width colon `：` / U+FF1A as different characters.
- Never remove `Delivered`.
- Never remove `1: reveiw request` until a later phase has confirmed Ali Reviews / Kudosi sent-status handling.
- The first implementation phase must produce a dry-run report only.
- No customer email may be sent during Phase 0 or Phase 1.
- No Shopify write or mutation may be performed during Phase 0 or Phase 1.
- Phase 1 must use exact tag matching for `Delivered` and `1: reveiw request`; `1: review request` is not equivalent, and half-width `:` / U+003A is not equivalent to full-width colon U+FF1A.
- Do not store real Ali Reviews / Kudosi tokens, Gmail OAuth credentials, Shopify tokens, Trustpilot private links, or other secrets in docs, logs, `.env.example`, or Git.
- Ticket system review-request filtering rules must be documented and reviewed before any customer-facing or Shopify-writing workflow is built.

## Shopify Product Translation Rules

- Existing translation entry point: `backend/shopify_sync/management/commands/translate_shopify_product.py`.
- Default workflow must be dry-run first. Do not directly write Shopify translations on the first run.
- Do not enable or create batch product translation until the single-product review workflow is stable and the user explicitly asks for it.
- Only run one `product_id` and one `target_locale` at a time for product translation.
- Batch product translation dry-runs may read up to 3 product IDs from `SHOPIFY_TRANSLATION_TEST_PRODUCT_IDS`, `backend/reviews/translation_product_ids.txt`, or `SHOPIFY_TRANSLATION_TEST_PRODUCT_ID`; they must never auto-scan Shopify for products.
- Batch product translation dry-run reviews should include QA gates with `qa_status`, `qa_warnings`, `qa_failures`, and `qa_checks` for each product/locale result.
- Batch QA gates should check title/meta length, body HTML presence, forbidden shipping/origin phrases, forbidden CTA phrases, exaggerated military/combat wording, image alt text presence, HTML structure preservation, and no-write confirmation.
- Batch review JSON must be strict parseable JSON. Control characters from command output should be sanitized, the summary should be written in an ASCII-safe escaped form, and the file should be validated after write.
- Batch QA gates should detect mojibake / encoding corruption markers such as `Pr盲zise`, `f眉r`, `鈥檃`, or Japanese mojibake fragments like `銉`.
- Batch apply plan generation is review-only. It may read `logs/shopify_translation_batch_multi_locale_dry_run_review.json` and write local plan files, but it must not call Shopify APIs, mutations, `translationsRegister`, publish, apply, or update paths.
- Batch apply plans should mark product/locale items as `ready_for_apply`, `needs_review`, or `blocked`; this is a planning decision only and not approval to write Shopify.
- Batch apply plan items should include manual review template fields: `manual_decision`, `manual_decision_allowed_values`, `manual_reviewer`, `manual_review_notes`, `manual_review_required`, and `manual_approval_ready`.
- Batch apply plan summaries should explicitly report `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.
- Batch apply plan validation may read manually edited `logs/shopify_translation_batch_apply_plan.json` and write local validation JSON/HTML reports only. It must not apply, publish, update, call mutations, or call `translationsRegister`.
- Batch apply plan validation should only treat manually approved items as future-apply eligible when the item was already ready for human approval, QA passed, `eligible_for_apply=true`, `qa_failures` is empty, and no-write was confirmed.
- Batch apply execution preview may read `logs/shopify_translation_batch_apply_plan_validation.json` and write local preview JSON/HTML reports only. It must only show which product / locale / fields would be prepared for a future apply task.
- Batch apply execution preview must report `preview_only=true`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`; it must not call Shopify APIs, mutations, `translationsRegister`, publish, apply, or update paths.
- Batch apply execution preview should include a final approval template with `final_approval_status=pending`, allowed values `pending`, `approved`, and `rejected`, and `final_apply_allowed=false` until a future separate write task is explicitly confirmed.
- Batch apply execution final validation may read `logs/shopify_translation_batch_apply_execution_preview.json` and write local final validation JSON/HTML reports only. It must validate final approval status and still report `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.
- Batch apply execution final validation must block `final_approval_status=approved` unless the preview has approved, final-ready, QA-passing items and a non-empty final approver.
- Batch apply command generation may read `logs/shopify_translation_batch_apply_execution_final_validation.json` and write local command/payload plan JSON/HTML reports only. It must report `command_generation_only=true`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.
- Batch apply command generation must produce zero commands when `final_apply_allowed=false`. Even when final approval allows future apply, generated commands are preview-only plans and require a separate explicitly confirmed write task before execution.
- Batch apply command plans should include a command approval template with `command_approval_status=pending`, allowed values `pending`, `approved`, and `rejected`, and `command_execution_allowed=false` until a later separate write task is explicitly confirmed.
- Batch apply command validation may read `logs/shopify_translation_batch_apply_command_plan.json` and write local command validation JSON/HTML reports only. It must validate command approval status, block command execution unless approval is complete, and still report `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.
- Batch apply command validation must never execute generated commands. It must block approved command plans with no commands, missing approver, non-approved command items, unsafe command preview text, or secret-like command preview markers.
- Batch apply execution dry-run may read `logs/shopify_translation_batch_apply_command_validation.json` and write local execution dry-run JSON/HTML reports only. It must simulate the final execution flow while reporting `command_executed=false`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.
- Batch apply execution dry-run must not execute command previews, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, write the database, or git push. If `command_execution_allowed=false`, it must output a blocked dry-run report with zero simulated executions.
- Batch apply execution dry-run reports should include an execution approval template with `execution_approval_status=pending`, allowed values `pending`, `approved`, and `rejected`, and `real_execution_allowed=false` until a later separate write task is explicitly confirmed.
- Batch apply execution approval validation may read `logs/shopify_translation_batch_apply_execution_dry_run.json` and write local execution approval validation JSON/HTML reports only. It must validate execution approval status while reporting `command_executed=false`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.
- Batch apply execution approval validation must block approved status unless an execution approver is present, at least one simulated execution exists, every simulated item is approved and ready, payload preview is available, and all no-write / no-command-execution safety fields remain false.
- Batch apply locked runner may read `logs/shopify_translation_batch_apply_execution_approval_validation.json` and write local locked runner JSON/HTML reports only. It is a shell only and must report `real_apply_allowed=false`, `real_apply_performed=false`, `command_executed=false`, `shopify_write_performed=false`, `apply_performed=false`, `publish_performed=false`, and `translations_register_performed=false`.
- Batch apply locked runner must not execute commands, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, write the database, or git push. Even if prior approval validation allows real execution in the future, this phase must output `ready_but_locked` and keep real apply disabled.
- Single-field apply sandbox design may read `logs/shopify_translation_batch_apply_locked_runner.json` and write local sandbox design JSON/HTML reports only. It must hard-code the future sandbox scope to 1 product, 1 locale, 1 field, allowed field `meta_title`, with `real_write_allowed=false` and `translations_register_allowed=false`.
- Single-field apply sandbox design must not execute commands, call Shopify APIs, call `translationsRegister`, mutate Shopify, publish, apply, update, write the database, or git push. Future real writes must be a separate task with explicit confirmation, backup before write, and post-write readback verification.
- Single-field apply sandbox runner may read `logs/shopify_translation_single_field_apply_sandbox_design.json` and write local sandbox runner JSON/HTML reports only. It must require manually supplied `SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID`, `SHOPIFY_TRANSLATION_SANDBOX_LOCALE`, and `SHOPIFY_TRANSLATION_SANDBOX_FIELD`.
- Single-field apply sandbox runner is forced dry-run only. It must accept only `field=meta_title`, must not fall back to product ID files or Shopify scans, and must report `real_write_allowed=false`, `real_write_attempted=false`, `translations_register_allowed=false`, `translations_register_called=false`, `command_executed=false`, and `shopify_write_performed=false`.
- Single-field apply preflight package may read `logs/shopify_translation_single_field_apply_sandbox_runner.json` and write local preflight JSON/HTML reports only. It must require manually supplied `SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID`, `SHOPIFY_TRANSLATION_SANDBOX_LOCALE`, `SHOPIFY_TRANSLATION_SANDBOX_FIELD`, and `SHOPIFY_TRANSLATION_SANDBOX_PROPOSED_VALUE`.
- Single-field apply preflight package must accept only `field=meta_title`, require proposed value length <= 60 characters, match the sandbox runner scope exactly, and report `real_write_allowed=false`, `real_write_attempted=false`, `translations_register_allowed=false`, `translations_register_called=false`, `command_executed=false`, and `shopify_write_performed=false`.
- Single-field backup fetch may read `logs/shopify_translation_single_field_apply_preflight_package.json` and use manually supplied `SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID`, `SHOPIFY_TRANSLATION_SANDBOX_LOCALE`, and `SHOPIFY_TRANSLATION_SANDBOX_FIELD` to fetch one read-only Shopify backup value.
- Single-field backup fetch must accept only `field=meta_title`, must match the preflight scope exactly, may perform only a read-only GraphQL `translatableResource` query, and must report `real_write_allowed=false`, `translations_register_allowed=false`, `translations_register_called=false`, `mutation_performed=false`, `shopify_mutations_called=[]`, and `shopify_write_performed=false`.
- Single-field readback / rollback plan may read only `logs/shopify_translation_single_field_apply_preflight_package.json` and `logs/shopify_translation_single_field_backup_fetch.json`, then write local plan JSON/HTML reports only.
- Single-field readback / rollback plan must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. If the backup fetch did not perform a read-only Shopify query, the plan must mark the backup unverified and block future real writes until a verified backup exists.
- Single-field final write gate may read only the single-field preflight package, backup fetch report, and readback / rollback plan, then write local final gate JSON/HTML reports only.
- Single-field final write gate must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It may output `ready_for_human_final_approval` only when the verified backup, readback plan, rollback plan, scope, proposed value, and no-write safety checks pass; it must still report `final_real_write_allowed=false`.
- Single-field real write runner design may read only the single-field preflight package, backup fetch report, readback / rollback plan, and final write gate package, then write local design JSON/HTML reports only.
- Single-field real write runner design must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, git push, or generate directly executable write commands. It may describe a future runner design only and must still report `design_only=true`, `final_real_write_allowed=false`, and `real_write_allowed=false`.
- Single-field real write locked runner may read the single-field preflight package, backup fetch report, readback / rollback plan, final write gate package, real write runner design, and manually supplied sandbox environment variables, then write local locked runner JSON/HTML reports only.
- Single-field real write locked runner must remain locked even if `SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true` is present. It must report `locked_shell=true`, `dangerous_flag_effective=false`, `final_real_write_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `command_executed=false`, `readback_performed=false`, `rollback_performed=false`, and `shopify_write_performed=false`.
- Single-field real write pre-execution validation may read the single-field preflight package, backup fetch report, readback / rollback plan, final write gate package, real write runner design, locked runner report, and manually supplied sandbox environment variables, then write local validation JSON/HTML reports only.
- Single-field real write pre-execution validation must require `SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true` before it can output `ready_for_manual_write_approval`, but the dangerous flag is still not effective for writing in this phase. It must report `pre_execution_validation_only=true`, `write_execution_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `command_executed=false`, `readback_performed=false`, `rollback_performed=false`, and `shopify_write_performed=false`.
- Single-field final human approval package may read the single-field preflight package, backup fetch report, readback / rollback plan, final write gate package, real write runner design, locked runner report, pre-execution validation report, and manually supplied sandbox environment variables, then write local final approval JSON/HTML reports only.
- Single-field final human approval package must require `SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true` and a ready pre-execution validation report, but it must still report `final_human_approval_package_only=true`, `phase_12_entry_allowed=false`, `write_execution_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `command_executed=false`, `readback_performed=false`, `rollback_performed=false`, and `shopify_write_performed=false`.
- Single-field real write runner final-safe shell may read the single-field preflight package, backup fetch report, readback / rollback plan, final write gate package, real write runner design, locked runner report, pre-execution validation report, final human approval package, and manually supplied sandbox environment variables, then write local final-safe shell JSON/HTML reports only.
- Single-field real write runner final-safe shell must require `SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true` and may record `SHOPIFY_TRANSLATION_PHASE_12_FINAL_SAFE_SHELL_ACK`, but both flags remain ineffective for writing. It must report `final_safe_shell_only=true`, `phase_12_1_entry_allowed=false`, `phase_12_entry_allowed=false`, `write_execution_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `command_executed=false`, `readback_performed=false`, `rollback_performed=false`, and `shopify_write_performed=false`.
- Single-field real write execution plan may read the single-field preflight package, backup fetch report, readback / rollback plan, final write gate package, real write runner design, locked runner report, pre-execution validation report, final human approval package, final-safe shell report, and manually supplied sandbox environment variables, then write local execution plan JSON/HTML reports only.
- Single-field real write execution plan must require `SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true`, `SHOPIFY_TRANSLATION_PHASE_12_FINAL_SAFE_SHELL_ACK=true`, and `SHOPIFY_TRANSLATION_PHASE_12_1A_PLAN_ACK=true`, but all flags remain ineffective for writing. It may generate a `translationsRegister` payload preview only and must report `execution_plan_only=true`, `payload_preview_only=true`, `phase_12_1b_entry_allowed=false`, `phase_12_1_entry_allowed=false`, `phase_12_entry_allowed=false`, `write_execution_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `command_executed=false`, `readback_performed=false`, `rollback_performed=false`, and `shopify_write_performed=false`.
- Single-field real write one-shot locked shell may read the single-field preflight package, backup fetch report, readback / rollback plan, final write gate package, real write runner design, locked runner report, pre-execution validation report, final human approval package, final-safe shell report, execution plan report, and manually supplied sandbox environment variables, then write local one-shot locked shell JSON/HTML reports only.
- Single-field real write one-shot locked shell must require `SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY=true`, `SHOPIFY_TRANSLATION_PHASE_12_FINAL_SAFE_SHELL_ACK=true`, `SHOPIFY_TRANSLATION_PHASE_12_1A_PLAN_ACK=true`, and may record `SHOPIFY_TRANSLATION_PHASE_12_1B_LOCKED_SHELL_ACK=true`, but all flags remain ineffective for writing. It must report `one_shot_locked_shell_only=true`, `phase_12_1b_real_execution_allowed=false`, `phase_12_1b_entry_allowed=false`, `phase_12_1_entry_allowed=false`, `phase_12_entry_allowed=false`, `write_execution_allowed=false`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `command_executed=false`, `readback_performed=false`, `rollback_performed=false`, and `shopify_write_performed=false`.
- Single-field real write one-shot execute may only target `gid://shopify/Product/7655686799427`, locale `ja`, field `meta_title`, value `MOFLY P-51D Aileron Link Connector`, and must read the full Phase 11.3 through Phase 12.1B-0 local report chain before any real-run path.
- Single-field real write one-shot execute must keep `mode=dry-run` completely no-write: no Shopify API call, no mutation, no `translationsRegister`, no readback, no rollback, and `all_no_write_confirmed=true`. Real write execution is only eligible in a later explicit `real-run` or `execute-real-write` command with `SHOPIFY_TRANSLATION_PHASE_12_1B_REAL_EXECUTION_ACK=YES_I_APPROVE_ONE_REAL_SHOPIFY_TRANSLATION_WRITE`; rollback must never be automatic.
- Single-field post-write audit package may read the successful one-shot execution report plus the earlier preflight, backup, readback / rollback, final gate, pre-execution, final human approval, and execution plan reports, then write local audit JSON/HTML reports only.
- Single-field post-write audit package must preserve source execution facts such as `source_shopify_write_performed=true`, `source_translations_register_called=true`, `source_mutation_performed=true`, and `source_readback_performed=true`, while the audit task itself must report `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Single-field rollback approval package may read the verified backup report, readback / rollback plan, successful one-shot execution report, and post-write audit report, then write local rollback approval JSON/HTML reports only.
- Single-field rollback approval package must never execute rollback, call Shopify APIs, call mutations, call `translationsRegister`, perform readback, publish, apply, update, write the database, or git push. It may describe a future optional restore to the verified backup value only, but must report `rollback_approval_package_only=true`, `rollback_execution_allowed=false`, `rollback_performed=false`, `automatic_rollback_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Second single-field test preparation may read the first-test post-write audit, rollback approval package, one-shot execution report, and backup fetch report, then write local second-test preparation JSON/HTML reports only.
- Second single-field test preparation must require manually supplied `SHOPIFY_TRANSLATION_SECOND_TEST_PRODUCT_ID`, `SHOPIFY_TRANSLATION_SECOND_TEST_LOCALE`, `SHOPIFY_TRANSLATION_SECOND_TEST_FIELD`, and `SHOPIFY_TRANSLATION_SECOND_TEST_PROPOSED_VALUE`. It must not guess or reuse the first product as a real plan when scope variables are missing, must accept only one product, one locale, one field `meta_title`, proposed value length <= 60, and must report `second_test_prepare_only=true`, `second_test_real_write_allowed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Second single-field verified backup fetch may read `logs/shopify_translation_second_single_field_test_prepare.json` and manually supplied second-test scope environment variables, then perform exactly one read-only Shopify GraphQL `translatableResource` query for the same product / locale / `meta_title` scope.
- Second single-field verified backup fetch must block missing scope, prepare-not-ready, scope mismatch, and any field other than `meta_title`; it must not write Shopify, call mutations, call `translationsRegister`, perform rollback, expand scope, batch, or scan the store. It must report `second_backup_source_is_verified=true` only after the read-only query succeeds, while keeping `second_test_real_write_allowed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Second single-field real write readiness may read only `logs/shopify_translation_second_single_field_test_prepare.json`, `logs/shopify_translation_second_single_field_verified_backup_fetch.json`, and matching second-test scope environment variables, then write local readiness JSON/HTML reports only.
- Second single-field real write readiness must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It may output `second_real_write_ready_for_human_approval` only when the prepare report is ready, the second verified backup is ready, the environment scope matches both reports, `field=meta_title`, proposed value length <= 60, and backup verification is confirmed; it must keep `readiness_package_only=true`, `second_test_real_write_allowed=false`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Second single-field real write execute may only target `gid://shopify/Product/7655686799427`, locale `ja`, field `meta_title`, value `MOFLY P-51D Aileron Link Connector Test`, and must read the second-test prepare, second verified backup, and second readiness reports before any real-run path.
- Second single-field real write execute must keep `mode=dry-run` completely no-write: no Shopify API call, no mutation, no `translationsRegister`, no readback, no rollback, no publish, and `all_new_actions_no_write_confirmed=true`. Real write execution is only eligible in a later explicit `real-run` or `execute-real-write` command with `SHOPIFY_TRANSLATION_SECOND_TEST_REAL_EXECUTION_ACK=YES_I_APPROVE_SECOND_REAL_SHOPIFY_TRANSLATION_WRITE`; it must perform exactly one `translationsRegister` mutation, immediately read back the same scope, and never run automatic rollback.
- Second single-field post-write audit package may read the second real-write execution report and optionally the second verified backup/readiness reports, then write local audit JSON/HTML reports only.
- Second single-field post-write audit package must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It may preserve source execution facts from Phase 12.7, but the audit task itself must report `audit_package_only=true`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Small batch apply plan package may read the second post-write audit report, second real write execution report, and second verified backup report, then write local small batch apply plan JSON/HTML reports only.
- Small batch apply plan package must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It must keep the plan to at most 5 translation entries, exactly one product, exactly one locale, and allowed fields `meta_title` / `meta_description` only. It must report `plan_package_only=true`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `bulk_write_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Small batch apply execute must prefer `logs/shopify_translation_csv_json_small_batch_apply_plan_package.json` when present and otherwise may fall back to `logs/shopify_translation_small_batch_apply_plan_package.json`. Reports must mark `plan_source=csv_json` or `plan_source=legacy_sample`, validate one product / one locale / at most 5 entries, and in a future explicit `real-run` or `execute-real-write` path perform exactly one small-batch Shopify `translationsRegister` mutation for approved fields `meta_title` / `meta_description`.
- Small batch apply execute must keep `mode=dry-run` completely no-write and output `execution_status=dry_run_small_batch_write_not_executed` when the plan is ready. Real-run requires local approval and exact `SHOPIFY_TRANSLATION_SMALL_BATCH_EXECUTION_ACK=YES_I_APPROVE_SMALL_BATCH_SHOPIFY_TRANSLATION_WRITE`, must immediately read back every entry, must mark readback mismatch as failure requiring rollback approval, and must never run automatic rollback, publish, full-store scan, unsupported-field writes, or bulk expansion.
- Small batch post-write audit package may read `logs/shopify_translation_small_batch_apply_execute.json` and optionally `logs/shopify_translation_small_batch_apply_plan_package.json`, then write local audit JSON/HTML reports only.
- Small batch post-write audit package must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It may preserve source execution facts from a prior successful small-batch real-run, but the audit task itself must report `audit_package_only=true`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Small batch rollback approval package may read `logs/shopify_translation_small_batch_apply_plan_package.json`, `logs/shopify_translation_small_batch_apply_execute.json`, and `logs/shopify_translation_small_batch_post_write_audit_package.json`, then write local rollback/restore approval JSON/HTML reports only.
- Small batch rollback approval package must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, perform restore, publish, apply, update, write the database, or git push. It may describe an optional future restore only from locally recorded before values; if restore values are missing it must mark manual backup review required instead of guessing. It must report `rollback_approval_package_only=true`, `rollback_execution_allowed=false`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `restore_performed=false`, `publish_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- CSV/JSON small batch apply plan package may read only `remote_approval/inputs/shopify_translation_small_batch_input.json` or `.csv`, preferring JSON when both exist, and write local plan JSON/HTML reports only.
- CSV/JSON small batch apply plan package must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It must keep plans to at most 5 entries, exactly one product, exactly one locale `ja`, allowed fields `meta_title` / `meta_description` only, and must report `plan_package_only=true`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `bulk_write_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- CSV/JSON small batch real-write readiness package may read only `logs/shopify_translation_csv_json_small_batch_apply_plan_package.json` and `logs/shopify_translation_small_batch_apply_execute.json`, then write local readiness JSON/HTML reports only.
- CSV/JSON small batch real-write readiness package must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It may provide a manual real-run command preview, but must not execute it. It must require `plan_source=csv_json`, dry-run `execution_status=dry_run_small_batch_write_not_executed`, at most 5 entries, one product, one locale `ja`, fields `meta_title` / `meta_description` only, and report `readiness_package_only=true`, `real_write_allowed=false`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `bulk_write_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- CSV/JSON small batch manual real-run test package may read only the CSV/JSON apply plan report, the small batch execute dry-run report, and the CSV/JSON readiness report, then write local manual test JSON/HTML reports only.
- CSV/JSON small batch manual real-run test package must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It may show the exact manual real-run and audit commands for the human operator, but must not execute them. It must require `plan_source=csv_json`, ready apply plan, no-write dry-run execute report, ready readiness report, at most 5 entries, one product, one locale `ja`, fields `meta_title` / `meta_description` only, and report `manual_test_package_only=true`, `real_run_not_executed_by_this_task=true`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `bulk_write_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- CSV/JSON small batch post-write audit package may read only the CSV/JSON apply plan report, small batch execute report, CSV/JSON readiness report, and CSV/JSON manual test package, then write local audit JSON/HTML reports only.
- CSV/JSON small batch post-write audit package must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It may preserve source real-run facts only when the execute report is a successful `plan_source=csv_json` real-run, but the audit task itself must report `audit_package_only=true`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Shopify Product Translation Console Phase 15.0 is read-only and may expose a staff-only admin page at `/admin/shopify_sync/translation-console/` for product lookup and translatable field inspection.
- Shopify Product Translation Console must not call OpenAI, generate translations, call mutations, call `translationsRegister`, write Shopify, publish, apply, rollback, write the database, add migrations, auto-scan the store, or expose access tokens. It may call read-only Shopify GraphQL queries for one product or a maximum 5-product search and must report `shopify_read_only=true`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `real_apply_performed=false`, and `rollback_performed=false`.
- Selected product missing translation draft package Phase 15.1 may call read-only Shopify GraphQL queries for one selected product and may call OpenAI only to create local draft translations for missing `title`, `meta_title`, and `meta_description` entries across `ja`, `de`, `fr`, `es`, and `it`.
- Phase 15.1A draft quality refinement must keep `title` <= 65 chars, `meta_title` <= 60 chars, and `meta_description` <= 155 chars, may run at most two natural rewrite attempts for over-length drafts, must avoid CTA/shipping/origin claims and mechanical English phrases, and may mark `eligible_for_apply_plan=true` only for `draft_ready_for_manual_review` entries.
- Phase 15.1B Google SEO checks must add per-draft `seo_validation_status`, `seo_notes`, recommended character ranges, core keyword/model/forbidden phrase checks, and may keep `eligible_for_apply_plan=true` only when both `validation_status=draft_ready_for_manual_review` and `seo_validation_status=seo_ready`.
- Selected product missing translation draft package must not call Shopify mutations, call `translationsRegister`, write Shopify, publish, apply, rollback, overwrite existing translations, add migrations, expose tokens, or git push. Existing current translations must be skipped, outdated translations must be marked for manual review, and the task must report `draft_package_only=true`, `shopify_read_only=true`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Phase 15.3 selected product apply plan generation may read a trusted selected-product draft result and write local apply-plan JSON/HTML reports only. It must include only entries with `eligible_for_apply_plan=true`, `validation_status=draft_ready_for_manual_review`, and `seo_validation_status=seo_ready`, must skip existing current translations and outdated translations, and must report `apply_plan_only=true`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `apply_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Phase 15.4 selected product final review generation may read a trusted apply plan result and write local final-review JSON/HTML reports only. It is the final no-write review gate before any future separate write phase, must require future manual ACK for Shopify writes, must reject missing digests, missing values, unsupported fields, existing translations, outdated translations, draft-needs-review entries, and SEO-needs-review entries, and must report `final_review_only=true`, `apply_plan_only=true`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `apply_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `existing_translation_overwrite_allowed=false`, `outdated_translation_overwrite_allowed=false`, `no_new_shopify_writes_performed=true`, and `manual_ack_required_for_future_write=true`.
- Phase 15.5 selected product real-write readiness generation may read a trusted final review result and write local readiness JSON/HTML reports only. It is a no-write readiness package, not an execution entry point. It must verify the final review is ready, every entry is ready for final manual review, digests and proposed translations are present, locales are limited to `ja`, `de`, `fr`, `es`, and `it`, fields are limited to `title`, `meta_title`, and `meta_description`, and no existing or outdated translations are being overwritten. It must report `readiness_package_only=true`, `final_review_only=true`, `future_write_allowed=false`, `manual_ack_required_for_future_write=true`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `apply_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `existing_translation_overwrite_allowed=false`, `outdated_translation_overwrite_allowed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Phase 15.6 selected product locked execution plan generation may read a trusted real-write readiness result and write local execution-plan JSON/HTML reports only. It may show planned `translationsRegister` entry details, but it must remain locked and must never execute Shopify writes, mutations, `translationsRegister`, publish, apply, real apply, rollback, or overwrite existing/outdated translations. POSTed ACK or dangerous flags must not become effective in this phase. It must report `execution_plan_only=true`, `executor_locked=true`, `real_write_allowed=false`, `future_write_allowed=false`, `dangerous_ack_effective=false`, `manual_ack_required_for_future_write=true`, `future_phase_required=true`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `apply_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `existing_translation_overwrite_allowed=false`, `outdated_translation_overwrite_allowed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Phase 15.7 selected product locked executor shell generation may read a trusted locked execution plan result and write local executor-shell JSON/HTML reports only. It may record whether an ACK preview was entered, but it must never store the ACK value or make the ACK effective. It must not execute Shopify writes, mutations, `translationsRegister`, publish, apply, real apply, rollback, or overwrite existing/outdated translations. It must report `executor_shell_only=true`, `executor_locked=true`, `execution_plan_only=true`, `real_write_allowed=false`, `future_write_allowed=false`, `dangerous_ack_effective=false`, `manual_ack_required_for_future_write=true`, `future_phase_required=true`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `apply_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `existing_translation_overwrite_allowed=false`, `outdated_translation_overwrite_allowed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Phase 16.0 selected product real write executor may read a trusted locked executor shell result and write local executor dry-run JSON/HTML reports only. It is a future real-run gate design, not a real write phase. It must rebuild the full server-side chain, validate product scope, allowed locales, allowed fields, non-empty digest, source/proposed values, no existing/current translation, no outdated translation, zero blocked entries, and no blocking conditions before marking entries as dry-run would-write candidates. Even if a manual ACK phrase is entered, it must keep `dry_run_only=true`, `real_write_allowed=false`, `future_write_allowed=false`, `dangerous_ack_effective=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `apply_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `existing_translation_overwrite_allowed=false`, `outdated_translation_overwrite_allowed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Phase 16.1 selected product real write manual action package may read a trusted real write executor dry-run result and write local manual-action JSON/HTML reports only. It may show planned `translationsRegister` variables, future PowerShell command preview, readback verification plan, and rollback approval plan, but it must not call Shopify APIs, call mutations, call `translationsRegister`, publish, apply, real apply, rollback, overwrite translations, read secrets, or execute commands. It must keep `manual_ack_required=true`, `manual_ack_effective=false`, `real_write_allowed=false`, `future_write_allowed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.
- Phase 16.1B Translation Console smoke testing keeps static validation host-safe. Full live dry-run validation must run inside the Docker web Django environment with `python scripts\smoke_test_translation_console_manual_action_package.py --live-dry-run --use-docker`; the wrapper must call `docker compose exec -T web python manage.py smoke_test_translation_console_manual_action_package --live-dry-run` so it uses the mounted Django app rather than a host-only `scripts/` file. The smoke test remains no-write and must not call Shopify mutations, `translationsRegister`, publish, apply, real apply, rollback, or expose tokens.
- Before any formal Shopify translation write, generate and review a `--review-file` output unless the user explicitly confirms an equivalent manual review.
- Use `--dry-run` for preview runs and include the payload preview in the review.
- Formal Shopify translation writes require explicit user confirmation after review.
- After a formal write, re-read Shopify `translatableResource` and verify `translationsRegister` returned no user errors, values exist for the requested locale, and `outdated=false`.
- Preserve Shopify HTML structure and attributes, especially product body HTML and image `alt` attributes.
- Preserve `href`, `src`, `class`, `style`, `id`, and `data-*` attributes exactly.
- Do not remove product specs, compatibility notes, model numbers, SKU-like text, or package contents.
- Avoid keyword stuffing, fake urgency, generic AI marketing language, and inaccurate claims.
- Filter origin/source/manufacturing-origin wording such as Origin, Herkunft, Made in China, Mainland China, and Hergestellt in Festlandchina.
- Filter shipping marketing phrases such as worldwide shipping, ships worldwide, Weltweiter Versand, Versand weltweit, and Lieferung weltweit.
- For German translation, use the local glossary file when relevant: `backend/shopify_sync/translation_glossary_de.json`.
- For German translation, preserve the German QA/localization polish rules in `translate_shopify_product.py`, including concise product titles, glossary terms, section heading normalization, and warnings for awkward German compounds.
- Keep translated SEO titles and meta descriptions concise and natural.
- Do not expose `OPENAI_API_KEY`, Shopify access tokens, or any other secret in prompts, logs, review files, shell output, docs, or Git.
- If a new repeated Shopify translation rule appears, update `.codex/skills/shopify-product-translation/SKILL.md` or create a new dedicated skill so future translation runs inherit it.

## Shopify SEO Rules

- SEO text must describe the actual product accurately.
- Do not invent features, certifications, warranty claims, or shipping promises.
- Keep keywords natural; readability is more important than repetition.
- Product title should stay compact and useful for customers.
- Meta descriptions should be written for click-through and clarity, not keyword stuffing.
- Image alt text should describe the actual product or visible part.
- Do not hide irrelevant keywords in HTML, alt text, or meta fields.

## Django Ticket Debug Rules

- Do not modify the ticket system unless the user explicitly asks.
- For ticket bugs, first inspect `tickets/models.py`, `tickets/admin.py`, `tickets/views.py`, templates, and URLs as needed.
- Default review stance: find null-related crashes, queryset issues, template field assumptions, permissions, and missing migrations.
- Preserve existing ticket status, reply, attachment, and Shopify order display behavior.
- For admin search changes, extend existing search logic instead of building a new page.
- Migrations are acceptable only when adding required fields; do not create migrations that remove data.
- `tickets.Ticket.order_no` is allowed to repeat. The same Shopify order may have multiple aftersales tickets, emails, or customer conversations.
- Do not add a unique constraint to `Ticket.order_no`.
- Do not use `Ticket.order_no` as the uniqueness source for Shenzhen warehouse settlement.

## Shenzhen Settlement Rules

- Settlement ERP should only display, calculate, and export Shenzhen warehouse items: `fulfillment_location == "shenzhen"`.
- Sydney / NULL / non-Shenzhen items must not enter Shenzhen settlement totals or CSV exports.
- Shenzhen sync rule: an order line must have exact Shopify tag `ship from china` on the order and the line item must be identified as Shenzhen fulfillment.
- Mixed-warehouse orders may remain in the system, but only Shenzhen item lines participate in settlement.
- Shenzhen settlement order uniqueness is based on `shopify_sync.ShopifyOrder`, not `tickets.Ticket.order_no`.
- `ShopifyOrder` uses `installation + shopify_order_id` as its business unique key.
- `order_number` and `order_name` are for display, search, and manual identification only. Do not use them as settlement uniqueness keys.
- `ShopifyOrderItem` uses `order + shopify_line_item_id` to prevent duplicate order item rows.
- `ShopifyOrderPackage` uses `order + package_no` to prevent duplicate package numbers within one order.
- `SettlementBatch` totals should be based on unique `ShopifyOrder` records so the same Shopify order is not settled twice.
- `handling_fee_rmb` means ordering cost / order placement cost. It is a deduction, not an added fee.
- Single-item or no-package settlement formula: `locked_product_cost_rmb * quantity + locked_shipping_cost_rmb - handling_fee_rmb`.
- Package settlement formula: package item product costs + `package.shipping_cost_rmb` - `package.ordering_cost_rmb`.
- Cost completeness should be enforced before confirmation / settlement / CSV export, not during ordinary package drafting.
- Product cost changes must be recorded in `ShopifyProductCostHistory`.
- If product default cost is empty or zero, the first valid order item cost can fill it automatically.
- If product default cost already exists, only overwrite it when the user explicitly chooses the overwrite option.
- Profit data is visible only to Admin / Finance, never Shenzhen Warehouse.
- Profit is tracked in AUD and should deduct payment fee, PL note ordering cost, and Shenzhen settlement cost converted by the maintained AUD/CNY rate.
- For mixed orders, do not count Sydney / other-warehouse revenue as Shenzhen revenue.
- For 100% off aftersales replacement orders, cap Shenzhen revenue by actual Shopify order total.
- Only Shopify-confirmed tips, such as `total_tip_received`, should be counted as additional Shenzhen revenue.
- Before changing Shenzhen order de-duplication, settlement totals, or order sync lookup logic, run read-only duplicate checks first.
- Before adding any unique constraint, verify that historical data has no duplicates.
- If duplicates are found, do not delete, merge, or overwrite automatically. Report the duplicate rows and wait for user confirmation.

## Verified Order Uniqueness Snapshot

Recorded on 2026-05-12:

- `Ticket.order_no` has duplicates, and this is allowed by business rules.
- `ShopifyOrderItem` duplicate check for `order + shopify_line_item_id`: `[]`.
- `ShopifyOrder` duplicate check for `installation + shopify_order_id`: `[]`.
- `ShopifyOrder.order_number` non-empty duplicate check: `[]`.
- `ShopifyOrder.order_name` non-empty duplicate check: `[]`.
- No migration is needed for this uniqueness review.

## Docker / Windows / cloudflared Notes

- The local shell is usually Windows PowerShell.
- Docker Desktop must be running before Docker commands work.
- If Docker reports `open //./pipe/docker_engine: Access is denied`, tell the user to close Codex App, reopen it as administrator, and confirm Docker Desktop is running.
- `backend/run_scheduler.sh` must use LF line endings. CRLF can break the scheduler container with `$'\r': command not found`.
- `quick start.txt` contains a cloudflared startup pattern. Do not document or expose real tunnel tokens.
- The scheduler container runs `bash /app/run_scheduler.sh`.
- Order auto-sync should stay incremental and small-range by default. Long historical syncs should remain manual.

## Git Rules

- Use Git only after checking current status.
- Do not stage unrelated files such as logs.
- Do not commit secrets, local database files, generated logs, or debug dumps.
- If Git cannot create `.git/index.lock`, report the permission problem and ask the user to save the version manually.
- Avoid `git reset`, `git checkout --`, or `git revert` unless explicitly requested.
- When asked to save a version, commit only the files changed for that task.
