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

## Shenzhen Settlement Rules

- Settlement ERP should only display, calculate, and export Shenzhen warehouse items: `fulfillment_location == "shenzhen"`.
- Sydney / NULL / non-Shenzhen items must not enter Shenzhen settlement totals or CSV exports.
- Shenzhen sync rule: an order line must have exact Shopify tag `ship from china` on the order and the line item must be identified as Shenzhen fulfillment.
- Mixed-warehouse orders may remain in the system, but only Shenzhen item lines participate in settlement.
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
