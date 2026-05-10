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
- Preserve Shopify HTML structure and attributes, especially product body HTML and image `alt` attributes.
- Do not remove product specs, compatibility notes, model numbers, SKU-like text, or package contents.
- Avoid keyword stuffing, fake urgency, generic AI marketing language, and inaccurate claims.
- Avoid origin / China-origin marketing claims unless the user explicitly wants them.
- For German translation, use the local glossary file when relevant: `backend/shopify_sync/translation_glossary_de.json`.
- Keep translated SEO titles and meta descriptions concise and natural.

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
