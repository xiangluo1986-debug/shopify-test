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
- Review request automation integration preparation, checklists, and future dry-run report-only tasks.

## Poor Fits

- Arbitrary command execution.
- Shopify writes or translation publishing.
- Review request customer email sending.
- Shopify review request tag writes such as `tagsAdd` or `tagsRemove`.
- Ali Reviews / Kudosi API calls before API docs and token handling are confirmed.
- Gmail API send calls before OAuth and send permission are confirmed.
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
python remote_approval_runner.py --task shopify_review_request_ali_reviews_capability_discovery --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_candidate_scan --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_last_60_days_candidate_scan --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_shopify_order_sync_coverage --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_order_tags_persistence_audit --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_trustpilot_tag_exclusion_audit --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_tag_alias_and_candidate_correction_audit --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_customer_history_trustpilot_guard_audit --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_on_demand_customer_history_lookup --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_review_send_reuse_gmail_helper_audit --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_review_send_post_send_audit --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_trustpilot_post_send_tag_write --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_dashboard_counts_audit --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_dashboard_snapshot_refresh --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_gmail_readiness_package --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_shopify_tag_permission_readiness --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_tag_discovery --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_trustpilot_automation_dry_run --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_trustpilot_locked_send_readiness_package --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_trustpilot_auto_queue_refresh --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_trustpilot_candidate_simulator --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_trustpilot_locked_gmail_send_gate --mode dry-run --approval local
python remote_approval_runner.py --task shopify_review_request_trustpilot_gmail_real_send_readiness_audit --mode dry-run --approval local
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

## Review Request Trustpilot Auto Queue Refresh

## Review Request Shopify Order Sync Coverage

`shopify_review_request_shopify_order_sync_coverage` is a Phase 5.28B
local-only coverage check. It checks whether local ShopifyOrder data covers the
last 60 days, checks #22530 and #22562, runs the local candidate scan, and
prepares exact manual sync commands. It does not call Shopify APIs, write
Shopify tags, call Gmail APIs, create drafts, send emails, or call external
review APIs.

Initial setup command prepared by the task:

```powershell
docker compose exec -T web python manage.py sync_review_request_shopify_orders --days 60 --request-delay 1.0 --apply-local --skip-fulfillment-orders
```

Daily refresh command:

```powershell
docker compose exec -T web python manage.py sync_review_request_shopify_orders --days 3 --request-delay 1.0 --apply-local --skip-fulfillment-orders
```

Run the dry-run preview first when validating credentials or coverage:

```powershell
docker compose exec -T web python manage.py sync_review_request_shopify_orders --days 60 --request-delay 1.0 --dry-run --skip-fulfillment-orders
```

`shopify_review_request_order_tags_persistence_audit` is a Phase 5.28F
local-only audit for `ShopifyOrder.shopify_tags`. It reports whether the model
and database field are present, whether #22530 and #22562 have persisted tag
data, the safe tag summaries, review-request alias matches, and the candidate
count after local tag availability. It does not call Shopify, Gmail, Trustpilot,
Kudosi, or Ali Reviews APIs and does not write Shopify data.

Phase 5.28G keeps the candidate scan broad but caps the Trustpilot admin review
queue to a 20-candidate batch. The scan report includes the full eligible total,
visible review batch count, overflow count, sort order, and per-candidate rank
diagnostics. The admin page should show only the current review batch; any
Review & Send control is limited to those visible rows.

Phase 5.28N blocks eBay-tagged orders from the Trustpilot send queue and adds
the locked post-send Shopify tag write task:

```powershell
python remote_approval_runner.py --task shopify_review_request_trustpilot_post_send_tag_write --mode dry-run --approval local
```

Without the exact approval environment value, the task must report
`blocked_missing_tag_write_approval` and must not call Shopify APIs or write
Shopify tags. A future approved one-order write for the audited sent order uses:

```powershell
$env:SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE="YES_I_APPROVE_TRUSTPILOT_TAG_WRITE_FOR_SENT_ORDER"
python remote_approval_runner.py --task shopify_review_request_trustpilot_post_send_tag_write --mode dry-run --approval local
Remove-Item Env:\SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE
```

The task is locked to the single selected order from the successful post-send
audit. It may add `1: trustpilot` and remove `1: review request` /
`1: reveiw request` aliases only after the exact approval gate passes. It must
not call Gmail, Trustpilot, Kudosi, or Ali Reviews APIs.

Phase 5.28O makes the tag-write task source selection match the Django/web
post-send audit path. A no-approval run should still stop at
`blocked_missing_tag_write_approval`, but it should report whether host logs,
the Django/web audit builder, the latest Review & Send report, and the latest
post-send audit were found. If the audited send is found, the report should show
`tag_write_ready=true`, `email_sent_confirmed=true`, `sent_count=1`, and no
Shopify API call or write.

Phase 5.30 adds `shopify_review_request_dashboard_counts_audit` for the admin
Review Requests dashboard. It reports eligible total, visible Needs review
count, Already sent total, blocked total, older eligible hidden, latest sent
order/time, sent row timing coverage, Already sent page size/visible count, and
whether the dashboard should show a stale-data warning. It reads local Django
state and local reports only; it must not call Gmail, Shopify, external review
APIs, or `translationsRegister`.

Phase 5.31C adds `shopify_review_request_on_demand_customer_history_lookup` for
selected-order customer lifetime checks when local history is incomplete or
low-confidence. The local 60-day sync is fast but can miss older Shopify orders,
so admin `Review & Send` must block with `Customer history needs live Shopify
check before sending.` until a matching clean lookup report exists.

Phase 5.31D adds `shopify_review_request_shopify_scope_verification` to verify
the active Shopify token, not just the app config, has both `read_orders` and
`read_all_orders`. Adding `read_all_orders` in Shopify app settings may leave an
old installed token unchanged; if the report shows the active token is missing
`read_all_orders`, reauthorize or reinstall the Shopify app and save the new
token before sending any Review Request email.

Phase 5.32 adds `shopify_review_request_dashboard_snapshot_refresh` for the
admin Review Requests page cache. The task builds
`logs/shopify_review_request_dashboard_snapshot.json` and
`logs/shopify_review_request_dashboard_snapshot.html` from local synced
ShopifyOrder data and local Review Request reports. Normal page loads read this
cached snapshot and must not call Shopify APIs, Gmail APIs, external review
APIs, `translationsRegister`, or recompute the full queue. If the snapshot is
missing, the page shows `Review queue has not been generated yet.` If it is
stale, the page shows the last-updated warning and Review & Send blocks until a
fresh snapshot exists.

Initial setup:

```powershell
docker compose exec -T web python manage.py sync_review_request_shopify_orders --days 60 --request-delay 1.0 --skip-fulfillment-orders --apply-local
python remote_approval_runner.py --task shopify_review_request_dashboard_snapshot_refresh --approval local
```

Daily refresh:

```powershell
docker compose exec -T web python manage.py sync_review_request_shopify_orders --days 3 --request-delay 1.0 --skip-fulfillment-orders --apply-local
python remote_approval_runner.py --task shopify_review_request_dashboard_snapshot_refresh --approval local
```

Optional schedule: run the 3-day sync and snapshot refresh every 4 hours, and
keep a daily full 60-day sync/candidate refresh for wider coverage.

Phase 5.32B unifies the dashboard snapshot cache paths between the host runner,
Docker web container, and admin page. The page checks, in order,
`REVIEW_REQUEST_DASHBOARD_SNAPSHOT_PATH`, `/app/logs`, `/app/backend/logs`,
project-root `logs/`, and `backend/logs/`, then loads the newest readable valid
JSON snapshot. The refresh task writes the main snapshot to the configured path
or project-root `logs/`, mirrors to available container-readable cache paths,
and reports `snapshot_main_path`, `snapshot_mirror_paths_written`,
`snapshot_paths_failed`, and `page_expected_paths`.

Run the scope verification with:

```powershell
python remote_approval_runner.py --task shopify_review_request_shopify_scope_verification --mode dry-run --approval local
```

Run a selected lookup with:

```powershell
$env:SHOPIFY_REVIEW_REQUEST_LOOKUP_ORDER="#21687"
python remote_approval_runner.py --task shopify_review_request_on_demand_customer_history_lookup --mode dry-run --approval local
Remove-Item Env:\SHOPIFY_REVIEW_REQUEST_LOOKUP_ORDER
```

The lookup may perform read-only Shopify order/customer history reads using the
existing installation credentials. It first checks the active token through
Shopify's read-only access-scope endpoint. Lifetime history is only considered
confirmed when the active token includes `read_all_orders`; otherwise the
selected order remains blocked with `Shopify token does not have
read_all_orders. Reauthorize app before sending.` even if the live API returns
recent orders.
It must not write Shopify data, mutate tags, call `tagsAdd` / `tagsRemove`,
send Gmail, create Gmail drafts, call external review APIs, call
`translationsRegister`, output raw email/phone/address, or output full note
text. Its report should show only counts, order names, Trustpilot evidence
booleans, evidence order name, safe keyword, final recommendation, and block
reason. For `#21687`, rerun the selected lookup above after scope verification;
the expected clean-history signal is a full Shopify customer history count that
matches Shopify UI, with historical order names listed and Trustpilot
note/tag evidence reported only as a safe keyword plus order name.

Phase 5.31E adds `shopify_review_request_shopify_oauth_reauthorization_helper`
as a docs-only runner task and `scripts/shopify_oauth_reauthorize_helper.py` as
a local manual helper for future Shopify OAuth scope updates such as
`read_all_orders`. The runner task does not call Shopify APIs, exchange tokens,
write `.env`, call Gmail, send email, or output token/client-secret/code values.

Run the helper readiness report with:

```powershell
python remote_approval_runner.py --task shopify_review_request_shopify_oauth_reauthorization_helper --mode dry-run --approval local
```

Manual Shopify scope update process:

1. Run URL mode:

```powershell
python scripts/shopify_oauth_reauthorize_helper.py --mode url
```

2. Open the printed authorization URL and approve the app in Shopify.
3. Copy only the `code` value from the callback URL.
4. Run exchange mode only when ready. To save the token to local `.env`, set the
   exact approval flag first:

```powershell
$env:SHOPIFY_OAUTH_SAVE_TOKEN="YES_I_APPROVE_UPDATING_SHOPIFY_ACCESS_TOKEN"
python scripts/shopify_oauth_reauthorize_helper.py --mode exchange --code "PASTE_CODE_HERE"
Remove-Item Env:\SHOPIFY_OAUTH_SAVE_TOKEN
```

5. Restart web after a saved local `.env` token update.
6. Run helper verify mode or the existing scope verification runner:

```powershell
python scripts/shopify_oauth_reauthorize_helper.py --mode verify
python remote_approval_runner.py --task shopify_review_request_shopify_scope_verification --mode dry-run --approval local
```

7. Confirm `read_all_orders` is present.
8. Rerun the selected `#21687` lookup.

The helper never prints the access token or client secret. Saving requires
`SHOPIFY_OAUTH_SAVE_TOKEN=YES_I_APPROVE_UPDATING_SHOPIFY_ACCESS_TOKEN`; without
that flag, exchange mode reports that the token exchange succeeded but the token
was not saved. When saving to `.env`, the helper creates
`.env.backup.YYYYMMDDTHHMMSSZ`, updates only the selected Shopify token key, and
stops if multiple token keys exist unless `SHOPIFY_OAUTH_TOKEN_ENV_KEY` selects
one of `SHOPIFY_ACCESS_TOKEN`, `SHOPIFY_ADMIN_API_ACCESS_TOKEN`, or
`SHOPIFY_API_PASSWORD`.

Phase 5.29 makes the admin `Review & Send` POST complete the same one-order
Shopify tag update automatically after Gmail drafts.send succeeds. The POST
flow first builds the post-send audit in memory; if it confirms the same
selected order, `email_sent_confirmed=true`, and `sent_count=1`, it calls the
shared tag-write helper for that order only. If Gmail send fails or the audit
fails, no Shopify tag write is attempted. The manual runner above still
requires the approval environment value and is used for existing Sent / Tag
pending rows.

Phase 5.29B fixes the manual post-send tag-write runner shell payload. The
runner passes source audit data into Django shell as a JSON string and parses it
with `json.loads(...)`, so generated Python code does not contain raw JSON
`true` / `false` literals. The approval gate is unchanged.

Phase 5.29C tightens post-send tag-write verification. A Shopify readback is
treated as written only when `1: trustpilot` is present and all
review-request aliases are absent. After that verified readback, the runner
updates local `ShopifyOrder.shopify_tags` from Shopify so the next candidate
scan no longer keeps the order in Sent / Tag pending because of stale local
tags.

Phase 5.29D adds a strict one-order repair path for existing Sent / Tag pending
rows such as `#21284`. This is not a batch repair. The runner only enters
manual repair mode when both the target order env and the approval env are
provided, and this phase allows only:

```powershell
$env:SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE_ORDER="#21284"
$env:SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE="YES_I_APPROVE_TRUSTPILOT_TAG_WRITE_FOR_SENT_ORDER"
python remote_approval_runner.py --task shopify_review_request_trustpilot_post_send_tag_write --mode dry-run --approval local
Remove-Item Env:\SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE
Remove-Item Env:\SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE_ORDER
```

Before any Shopify API call, the runner verifies from local Review Request
history/queue evidence that `#21284` is already `Sent` and still `Tag pending`.
It blocks all other target orders with
`blocked_target_order_not_allowed_for_repair_phase`. A target-only run without
the approval env must still stop at `blocked_missing_tag_write_approval` and
perform no Shopify API call or write.

Phase 5.28D makes per-order fulfillment-order details opt-in for Review Request
sync. The default and recommended path skips those detail reads so the local
candidate scan can use Shopify order tags, `fulfillment_status`, notes, and
existing local report evidence first without creating one extra Shopify API call
per order. Use `--include-fulfillment-orders` only for a small deeper test, with
`--fulfillment-request-delay 2.0` or higher and optionally
`--fulfillment-max-orders`.

`shopify_review_request_trustpilot_auto_queue_refresh` is a Phase 5.8 dry-run
dashboard refresh task. It recomputes the Trustpilot readiness queue from local
reports, reads the existing locked send readiness package status for source
context, and writes local review files only:

```text
logs/shopify_review_request_trustpilot_auto_queue_refresh.json
logs/shopify_review_request_trustpilot_auto_queue_refresh.html
```

The task is safe for a future scheduler because it does not call Gmail APIs,
create Gmail drafts, send emails, call Shopify APIs, write Shopify tags, call
Trustpilot/Kudosi/Ali Reviews APIs, create tracking redirects, or generate
tracking tokens. Its next-step output is limited to `wait_no_candidate`,
`prepare_locked_send_package`, `manual_review_required_multiple_candidates`, or
`blocked_safety_issue`.

## Review Request Trustpilot Candidate Simulator

`shopify_review_request_trustpilot_candidate_simulator` is a Phase 5.12
local-only sandbox task. It writes fake candidate fixtures that can test the
locked Gmail send gate and executor shell branches without touching real
customers or external services.

It writes local review files only:

```text
logs/shopify_review_request_trustpilot_candidate_simulator.json
logs/shopify_review_request_trustpilot_candidate_simulator.html
logs/shopify_review_request_trustpilot_locked_gmail_send_gate_simulator_fixture.json
logs/shopify_review_request_trustpilot_gmail_send_executor_shell_simulator_fixture.json
```

Supported simulator modes are configured with
`SHOPIFY_REVIEW_REQUEST_SIMULATOR_MODE`: `no_candidate`,
`one_eligible_candidate`, `multiple_eligible_candidates`, or
`unsafe_candidate`. The default is `no_candidate`.

The locked gate and executor shell ignore simulator fixture reports unless
`SHOPIFY_REVIEW_REQUEST_USE_SIMULATOR_FIXTURE=YES_I_UNDERSTAND_THIS_IS_FAKE_DATA`
is present. The simulator never calls Gmail APIs, creates/updates/deletes
drafts, sends email, calls Shopify APIs, writes Shopify tags, calls
Trustpilot/Kudosi/Ali Reviews APIs, creates tracking redirects, or uses raw
customer emails.

## Review Request Trustpilot Locked Gmail Send Gate

`shopify_review_request_trustpilot_locked_gmail_send_gate` is a Phase 5.10
dry-run gate report. It reads the latest Trustpilot auto queue refresh, locked
send readiness package, automation dry-run, and optional history ledger audit
reports, then decides whether a future Gmail send could be considered after a
separate locked ACK. For sandbox branch testing only, it can read the Phase 5.12
simulator fixture when the explicit fake-data environment variable is set.

It writes local review files only:

```text
logs/shopify_review_request_trustpilot_locked_gmail_send_gate.json
logs/shopify_review_request_trustpilot_locked_gmail_send_gate.html
```

The gate never calls Gmail APIs, creates or updates drafts, sends email, writes
Shopify tags, calls Shopify mutations, calls Trustpilot/Kudosi/Ali Reviews APIs,
or creates tracking tokens. Current send permission remains false even when the
gate is ready for a future ACK.

## Review Request Trustpilot Gmail Send Executor Shell

`shopify_review_request_trustpilot_gmail_send_executor_shell` is a Phase 5.11
no-send executor shell. It reads the latest locked Gmail send gate report and
decides whether a future real Gmail send implementation could proceed. For
sandbox branch testing only, it can read the Phase 5.12 simulator fixture when
the explicit fake-data environment variable is set.

It writes local review files only:

```text
logs/shopify_review_request_trustpilot_gmail_send_executor_shell.json
logs/shopify_review_request_trustpilot_gmail_send_executor_shell.html
```

The executor shell never calls Gmail APIs, creates/updates/deletes drafts, sends
email, writes Shopify tags, calls Shopify mutations, calls Trustpilot/Kudosi/Ali
Reviews APIs, or creates tracking tokens. Even when exactly one candidate is
gate-ready and the locked ACK is present, this phase only reports
`ready_for_future_real_send_execute`; it does not send.

## Review Request Trustpilot Real Send Final Preflight

`shopify_review_request_trustpilot_real_send_final_preflight` is a Phase 5.13
final preflight task. It reads the real production auto refresh, locked send
readiness, locked Gmail send gate, and no-send executor shell reports by
default, then decides whether a future separately approved real-send execute
task could proceed.

It writes local review files only:

```text
logs/shopify_review_request_trustpilot_real_send_final_preflight.json
logs/shopify_review_request_trustpilot_real_send_final_preflight.html
```

Simulator fixture reports are ignored unless
`SHOPIFY_REVIEW_REQUEST_REAL_PREFLIGHT_USE_SIMULATOR=YES_I_UNDERSTAND_THIS_IS_FAKE_DATA`
is present. The preflight never calls Gmail APIs, creates/updates/deletes
drafts, sends email, calls Shopify APIs, writes Shopify tags, calls
Trustpilot/Kudosi/Ali Reviews APIs, or creates tracking tokens. Current
production state should remain `blocked_no_eligible_candidate` until a real
eligible delivered order with a review-request tag alias passes all duplicate
and risk checks.

## Review Request Trustpilot Real Send Execute Skeleton

`shopify_review_request_trustpilot_real_send_execute` is a Phase 5.14 locked
executor entry point. It reads the final preflight report and decides whether a
future real send would be allowed, but it does not contain an enabled Gmail send
implementation.

It writes local review files only:

```text
logs/shopify_review_request_trustpilot_real_send_execute.json
logs/shopify_review_request_trustpilot_real_send_execute.html
```

Production final preflight is used by default. Simulator readiness is ignored
unless
`SHOPIFY_REVIEW_REQUEST_REAL_SEND_EXECUTE_USE_SIMULATOR=YES_I_UNDERSTAND_THIS_IS_FAKE_DATA`
is present. Even if final preflight is ready and
`SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_REAL_SEND_EXECUTE=YES_I_APPROVE_REAL_TRUSTPILOT_GMAIL_SEND`
is present, this phase reports
`ready_but_real_send_implementation_not_enabled_in_this_phase` and still calls
no Gmail API, creates/updates/deletes no drafts, sends no email, calls no
Shopify API, writes no Shopify tag, calls no Trustpilot/Kudosi/Ali Reviews API,
and creates no tracking token.

## Review Request Trustpilot Gmail Real-Send Readiness Audit

`shopify_review_request_trustpilot_gmail_real_send_readiness_audit` is a Phase
5.15 local readiness audit for a future Trustpilot Gmail real-send
implementation. It reads only local reports from the auto refresh, locked send
readiness, locked Gmail send gate, no-send executor shell, final preflight, and
execute skeleton phases.

It writes local review files only:

```text
logs/shopify_review_request_trustpilot_gmail_real_send_readiness_audit.json
logs/shopify_review_request_trustpilot_gmail_real_send_readiness_audit.html
```

The audit may check whether Gmail dependency modules are importable and whether
expected local config names are present in the process environment, but it must
not print secret values, read credential contents, exchange OAuth tokens, or
contact Gmail. It must not create/update/delete drafts, send email, call
Shopify APIs, write Shopify tags, call Trustpilot/Kudosi/Ali Reviews APIs, or
create tracking redirects/tokens.

Current production state remains `blocked_no_eligible_candidate`. A future real
send implementation must still require exactly one candidate, final preflight
ready, explicit ACK name
`SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK`, explicit execute flag name
`SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_REAL_SEND_EXECUTE`, single-send limiting,
duplicate suppression, privacy masking, and a post-send audit before any
Shopify tag-write phase.

## Review Request Trustpilot Gmail OAuth Config Helper

`shopify_review_request_trustpilot_gmail_oauth_config_helper` is a Phase 5.16
local helper for diagnosing missing Gmail OAuth/config requirements before any
future Trustpilot real-send implementation.

It writes local review files only:

```text
logs/shopify_review_request_trustpilot_gmail_oauth_config_helper.json
logs/shopify_review_request_trustpilot_gmail_oauth_config_helper.html
```

The helper may check Gmail dependency importability, process environment
variable presence, `.env.example` placeholder names, and whether configured
credential/token path variables point to existing paths. It must not read
credential or token file contents, print secret values, exchange OAuth tokens,
or contact Gmail. It must not create/update/delete drafts, send email, call
Shopify APIs, write Shopify tags, call Trustpilot/Kudosi/Ali Reviews APIs, or
create tracking redirects/tokens.

Required placeholder names for future setup are
`GMAIL_SEND_FROM_EMAIL`, `GMAIL_OAUTH_CLIENT_SECRET_FILE`,
`GMAIL_OAUTH_TOKEN_FILE`, `GMAIL_REQUIRED_SCOPE`,
`SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK`, and
`SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_REAL_SEND_EXECUTE`.

## Review Request Trustpilot Gmail Config Compatibility Audit

`shopify_review_request_trustpilot_gmail_config_compatibility_audit` is a
Phase 5.18A local audit for comparing the older `GOOGLE_GMAIL_*` Trustpilot
Gmail flow with the newer `GMAIL_*` helper names.

It writes local review files only:

```text
logs/shopify_review_request_trustpilot_gmail_config_compatibility_audit.json
logs/shopify_review_request_trustpilot_gmail_config_compatibility_audit.html
```

The audit may scan source files and safe documentation/config placeholders for
variable names, and may check process environment presence booleans. It must
not read `.env`, token files, credential files, or secret values. It must not
call Gmail, create/update/delete drafts, send email, call Shopify, write tags,
call Trustpilot/Kudosi/Ali Reviews, or call `translationsRegister`.

If legacy config is detected, the helper may report
`legacy_config_present`, but real sending still requires final `gmail.send`
verification and a later explicitly approved write/send phase.

## Review Request Trustpilot Gmail Scope Compatibility Resolver

`shopify_review_request_trustpilot_gmail_scope_compatibility_resolver` is a
Phase 5.18B local resolver for classifying configured Gmail scope compatibility
for Trustpilot review request emails.

It writes local review files only:

```text
logs/shopify_review_request_trustpilot_gmail_scope_compatibility_resolver.json
logs/shopify_review_request_trustpilot_gmail_scope_compatibility_resolver.html
```

The resolver may inspect only `GOOGLE_GMAIL_SCOPES` and
`GMAIL_REQUIRED_SCOPE` from the process environment, plus safe scope
placeholders in `.env.example` and helper task constants. It reports whether
the config is draft-only (`gmail.compose`), real-send capable (`gmail.send` or
the broad mail scope), or missing/unknown. It must not call Gmail, create or
send drafts, read token/credential files, print secret values, call Shopify,
write tags, call Trustpilot/Kudosi/Ali Reviews, or call `translationsRegister`.

## Review Request Trustpilot Gmail Env Loading Audit

`shopify_review_request_trustpilot_gmail_env_loading_audit` is a Phase 5.21
local audit for diagnosing why Review Request Gmail tasks cannot see Gmail
scope/config in the runner environment.

It writes local review files only:

```text
logs/shopify_review_request_trustpilot_gmail_env_loading_audit.json
logs/shopify_review_request_trustpilot_gmail_env_loading_audit.html
```

The audit may check expected Gmail key presence in `os.environ`, read only
`.env` key names before `=`, and scan selected Docker/Django/runner files for
safe loader markers. It must not print values, read token or credential file
contents, call Gmail, create/update/delete drafts, send email, call Shopify,
write tags, call Trustpilot/Kudosi/Ali Reviews, or call `translationsRegister`.

## Review Request Trustpilot Gmail Env Loading Fix

Phase 5.22 adds safe project-root `.env` loading to the local remote approval
runner before task execution. The loader parses simple `KEY=VALUE` assignments
from the project `.env`, ignores blank lines and comments, loads values into
the local runner process environment, and does not overwrite existing process
environment values.

The loader reports only counts and booleans, including whether the loader was
enabled, whether the project `.env` file was found, how many keys were loaded,
how many keys were skipped because they already existed, and how many
Gmail-related keys were loaded. It never prints secret values and does not call
Gmail, create/update/delete drafts, send email, call Shopify, write tags, call
Trustpilot/Kudosi/Ali Reviews, or call `translationsRegister`.

This lets local Review Request Gmail tasks such as the scope resolver,
draft-only preflight, and one-draft locked runner see the existing Gmail
scope/config already present in `.env` while preserving the local approval
safety boundary.

## Review Request Approval Queue

Phase 5.24A adds the Django admin `Review Requests` approval queue. The main
page shows `Needs review email` and `Already sent`; eligible rows expose a
single `Review & Send` POST action.

Phase 5.25 enriches that queue with customer/order context: customer display
name, masked customer identifier, customer order count/sequence, order tags,
delivered status, review-request tag alias status, previous Trustpilot
history, eligibility status, and a plain-language blocker reason.

Phase 5.26 adds the merged order group guard. Related order numbers found in
local notes or local report references are treated as one shipment group, shown
with a `Merged order group` badge, and counted as one send candidate. The group
must be fully ready before any `Review & Send` action can appear, and prior
Trustpilot evidence for any order blocks the whole group.

Phase 5.27 changes the main queue to show only candidates from the last 60 days
that are actually ready for admin review/send under the current rules. Blocked
or not-ready rows move to the collapsed `Blocked / Not ready` section. Merged
groups such as `#22582/#22581` remain blocked until the whole group is ready,
so `#22582` must not appear in the main `Needs review email` table.

`shopify_review_request_last_60_days_candidate_scan` is the local audit task
for this queue. It scans synced local Shopify order rows plus existing local
review-request reports, reports eligible/already-sent/blocked counts, and does
not call Gmail, create drafts, send email, call Shopify, write tags, call
Trustpilot/Kudosi/Ali Reviews, or call `translationsRegister`.

Phase 5.28A updates review-request tag reads to accept canonical
`1: review request` and legacy typo `1: reveiw request`, including spacing and
case variants. Future writes still use canonical `1: review request`. It also
prevents repeat-customer orders from being treated as merged shipments unless
explicit merge evidence exists.

Phase 5.28H makes local customer history a hard Trustpilot eligibility gate.
First-order customers, unconfirmed customer history, and any same-customer
historical Trustpilot tag alias such as `1: trustpilot`, `1: trustpoilt`,
`trustpilot`, or `trustpoilt` block the main queue and POST path before Gmail.

`shopify_review_request_tag_alias_and_candidate_correction_audit` is the local
audit task for this correction. It reports `#22562` tag loading, matched review
request tag value, delivered detection, merge evidence source, explicit merge
evidence, final eligibility, blockers, and eligible candidate count after the
fix. It does not call Gmail, create drafts, send email, call Shopify, write
tags, call Trustpilot/Kudosi/Ali Reviews, or call `translationsRegister`.

`shopify_review_request_customer_history_trustpilot_guard_audit` is the local
audit task for Phase 5.28H. It reports first-order blocks, customer-history
unknown blocks, prior Trustpilot customer-history blocks, focus order diagnoses
for `#21070`, `#21075`, `#21076`, `#21102`, and `#21778`, and performs no API
calls or writes.

Phase 5.28I tightens customer-history matching and blocks note-based
aftersales/ticket risk. Name-only customer matches are low confidence and never
count as confirmed order history for Review & Send. Local order notes are
scanned only for safe risk keywords; full note text is not shown in reports or
HTML.

`shopify_review_request_customer_history_precision_audit` is the local audit
task for Phase 5.28I. It reports the `#21083` diagnosis, overcounted history
count, weak name-only matches, note-risk blocks, low-confidence history blocks,
and active Review & Send before/after counts. It performs no Shopify, Gmail,
Trustpilot, Kudosi, Ali Reviews, or external API calls and performs no writes.

Phase 5.31 extends the lifetime customer-history guard to scan historical local
Shopify order notes for Trustpilot evidence such as `trustpilot`, `trustpoilt`,
`truspilot`, `trustpoit`, and spacing/punctuation variants. Matching evidence
blocks the customer from Needs review with only the safe keyword and historical
order number shown; full note text and raw customer email remain hidden.

`shopify_review_request_customer_lifetime_trustpilot_note_audit` is the local
audit task for Phase 5.31. It reports the `#21687` lifetime order count,
matched historical order names, match method/confidence, historical Trustpilot
note evidence order, safe keyword, final eligibility/blockers, note-blocked
candidate count, and active Review & Send before/after counts. It performs no
Shopify, Gmail, Trustpilot, Kudosi, Ali Reviews, or external API calls and
performs no writes.

Phase 5.31B adds `shopify_review_request_customer_identity_drilldown_audit` for
`#21687`. It compares local identity strategies (email, names, phone,
postcode, and combined shipping identity), reports potential local matched
order names, scans only safe historical note fields for Trustpilot/`trustpoilt`
keywords, and recommends a wider Shopify customer/order sync when the local
history is smaller than the Shopify UI count. It outputs no raw email, phone,
address, or full note text and performs no Shopify, Gmail, external API, tag
write, mutation, email send, or `translationsRegister` call.

Phase 5.28J adds `shopify_review_request_review_send_failure_audit` for the
`#21075` Review & Send failure and paginates the Needs review email queue. The
audit reports the exact blocker, Gmail scope status, Gmail send permission
readiness, helper readiness, candidate eligibility, customer-history status,
prior Trustpilot evidence, and note-risk state. The page defaults to 25 visible
eligible candidates and supports `?page=` / `?page_size=` with 25, 50, and 100.
Direct admin sending remains blocked unless Gmail permission and helper
compatibility are both confirmed; no Shopify tag write happens in this phase.

Phase 5.28K adds
`shopify_review_request_review_send_reuse_gmail_helper_audit`. It inspects the
previous successful `#22621` Gmail `drafts.send` path and reports whether that
helper can be reused from the current admin `Review & Send` POST. The audit is
source-inspection only: it does not read secrets, call Gmail, create drafts,
send email, call Shopify, write tags, call Trustpilot/Kudosi/Ali Reviews, or
call `translationsRegister`. If the helper is not dynamic/admin-callable, the
admin page must show the plain blocker that no email was sent because the
previous Gmail send helper is not reusable from this admin action yet.

The `Review & Send` admin POST verifies the
selected order against the current eligible queue and returns a no-send blocker;
no Gmail API call, draft creation, email send, Shopify write, or external
review API call is performed by this phase.

If the selected order is not eligible, no Gmail call occurs. Shopify tag writes
remain disabled until a later post-send audit and separate approved tag-write
phase.

Phase 5.28L adds latest-customer queue filtering and a dynamic admin
`Review & Send` Gmail helper. The send path is still staff POST + CSRF only,
server-revalidates the selected row, requires the row to be the latest eligible
order for that precise customer identity, requires repeat-customer and risk
checks to pass, and sends at most one Trustpilot email through Gmail
`drafts.create` plus `drafts.send`. Shopify tag writes remain disabled.

`shopify_review_request_dynamic_review_send_audit` is the no-send audit task
for Phase 5.28L. It reports latest-filter before/after counts, hidden older
eligible rows, the `#22530`/`#22562` decision, dynamic helper readiness,
`#21075` readiness, visible Review & Send count, and latest-only queue status.
It does not call Gmail, create drafts, send email, call Shopify, write tags,
call Trustpilot/Kudosi/Ali Reviews, or call `translationsRegister`.

Phase 5.28M adds `shopify_review_request_review_send_post_send_audit`. It reads
the latest local Review & Send JSON/HTML report, confirms `email_sent=true`
with `sent_count=1`, and writes a local post-send audit under
`logs/codex_runs/`. It does not call Gmail, create drafts, send email, call
Shopify, write tags, call Trustpilot/Kudosi/Ali Reviews, or call
`translationsRegister`. A confirmed local Review & Send success counts as
Trustpilot sent history until Shopify tag write completes.

Phase 5.29 updates that admin POST flow: after Gmail drafts.send succeeds for
one server-revalidated selected order, the server builds the post-send audit in
memory and calls the shared one-order Shopify tag-write helper. If the audit or
tag write fails, Gmail is not retried and the order remains Sent / Tag pending
for the manual runner. If Gmail send fails, the Shopify tag-write helper is not
called.

Phase 5.29D adds a manual repair runner path for exactly one sent/tag-pending
order, currently locked to `#21284`. It requires
`SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE_ORDER="#21284"` plus the exact
tag-write approval env. The repair source must come from local Review Request
history/queue evidence showing `Sent` and `Tag pending`, or from a safe local
post-send report. It must not resend Gmail, call external review APIs, or repair
more than one order.

Phase 5.29E makes Trustpilot sent tag aliases a hard exclusion before the Needs
review queue. Current local Shopify tags, same-customer history tags, and local
send/tag-write reports are checked before a Review & Send action can appear.
Orders with `1: trustpilot`, `1: trustpoilt`, `trustpilot`, `trustpoilt`, or
spacing/case variants move to Already sent with local evidence instead of
remaining sendable.

`shopify_review_request_trustpilot_tag_exclusion_audit` audits this guard for
`#21225` and writes its local report under `logs/codex_runs/`. It reports local
tags, Trustpilot tag detection/source, before/after queue section, Needs review
removal, Already sent display, the Trustpilot-tagged exclusion count, and
no-Gmail/no-Shopify/no-external-API/no-write safety flags.

## Review Request Trustpilot Gmail Draft-Only Preflight

`shopify_review_request_trustpilot_gmail_draft_only_preflight` is a Phase
5.19A local preflight for the fastest safe Trustpilot rollout path: one future
Gmail draft for admin review and manual send when Gmail compose permission is
available.

It writes local review files only:

```text
logs/shopify_review_request_trustpilot_gmail_draft_only_preflight.json
logs/shopify_review_request_trustpilot_gmail_draft_only_preflight.html
```

The task reads only local safe reports from the Gmail scope resolver, real-send
final preflight/execute skeleton, auto queue refresh, locked send readiness
package, and locked Gmail send gate. It decides whether a later locked phase
could create exactly one Gmail draft. This phase must not call Gmail, create or
update a draft, send email, call Shopify, write tags, call Trustpilot/Kudosi/Ali
Reviews, or call `translationsRegister`.

## Review Request Trustpilot Gmail One-Draft Create Locked Runner

`shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner` is a
Phase 5.19B locked shell for the first future Trustpilot Gmail draft creation
flow.

It writes local review files only:

```text
logs/shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner.json
logs/shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner.html
```

The task reads only local safe reports from the draft-only preflight, Gmail
scope resolver, auto queue refresh, locked send readiness package, locked Gmail
send gate, and real-send final preflight. It explains the missing requirements
before a later phase can create exactly one Gmail draft: Gmail permission,
exactly one safe eligible order, duplicate/risk checks, and explicit local
draft-create approval. This phase must not call Gmail, create/update/delete a
draft, send email, call Shopify, write tags, call Trustpilot/Kudosi/Ali Reviews,
or call `translationsRegister`.

Future draft creation requires the exact env flag:

```text
SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_DRAFT_CREATE=YES_I_APPROVE_ONE_TRUSTPILOT_GMAIL_DRAFT_CREATE
```

Even if that flag is present, Phase 5.19B still creates no draft.

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

- `logs/shopify_translation_csv_json_small_batch_apply_plan_package.json` when present
- `logs/shopify_translation_small_batch_apply_plan_package.json`

The CSV/JSON plan is preferred when both reports exist and the execute report must mark `plan_source=csv_json`. If the CSV/JSON plan is absent, the legacy sample plan is used and the report marks `plan_source=legacy_sample`. A present CSV/JSON plan that is not ready must block as `blocked_csv_json_small_batch_apply_plan_not_ready`; fallback is only allowed when that report is missing.

It writes:

```text
logs/shopify_translation_small_batch_apply_execute.json
logs/shopify_translation_small_batch_apply_execute.html
```

Dry-run mode must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push.

In `dry-run` mode, a ready small batch plan outputs `execution_status=dry_run_small_batch_write_not_executed`, includes `plan_source`, keeps the scope to one product / one locale / at most 5 entries, and reports `real_write_allowed=false`, `write_execution_allowed=false`, `translations_register_allowed=false`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `bulk_write_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

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

### CSV/JSON Small Batch Real-Write Readiness Package

`shopify_translation_csv_json_small_batch_real_write_readiness_package` reads:

- `logs/shopify_translation_csv_json_small_batch_apply_plan_package.json`
- `logs/shopify_translation_small_batch_apply_execute.json`

It writes:

```text
logs/shopify_translation_csv_json_small_batch_real_write_readiness_package.json
logs/shopify_translation_csv_json_small_batch_real_write_readiness_package.html
```

This task is local-report-only. It must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It may include a manual real-run command preview, but the task itself must never execute that command or set any ACK.

The readiness package may output `readiness_status=csv_json_small_batch_real_write_ready_for_human_approval` only when the CSV/JSON plan is ready, the small batch execute report is a no-write dry-run, `plan_source=csv_json`, product/locale/entries match, entry count is at most 5, fields are limited to `meta_title` and `meta_description`, and every proposed value is non-empty and within field limits. It must keep `readiness_package_only=true`, `manual_human_approval_required=true`, `real_write_allowed=false`, `next_step_manual_real_run_required=true`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `bulk_write_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### CSV/JSON Small Batch Manual Real-Run Test Package

`shopify_translation_csv_json_small_batch_manual_real_run_test_package` reads:

- `logs/shopify_translation_csv_json_small_batch_apply_plan_package.json`
- `logs/shopify_translation_small_batch_apply_execute.json`
- `logs/shopify_translation_csv_json_small_batch_real_write_readiness_package.json`

It writes:

```text
logs/shopify_translation_csv_json_small_batch_manual_real_run_test_package.json
logs/shopify_translation_csv_json_small_batch_manual_real_run_test_package.html
```

This task is local-report-only. It must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It may show manual PowerShell commands for a later human-run `real-run` followed by the post-write audit, but it must never execute those commands, set ACK variables, or trigger Shopify work.

The manual test package may output `manual_test_package_status=csv_json_small_batch_manual_real_run_test_ready` only when the CSV/JSON apply plan is ready, the small batch execute report is a no-write dry-run from `plan_source=csv_json`, the CSV/JSON readiness report is ready, product/locale/entries match, entry count is at most 5, fields are limited to `meta_title` and `meta_description`, every proposed value is non-empty and within field limits, and all precondition reports remain no-write. It must keep `manual_test_package_only=true`, `manual_test_required=true`, `real_run_not_executed_by_this_task=true`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `bulk_write_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### CSV/JSON Small Batch Post-Write Audit Package

`shopify_translation_csv_json_small_batch_post_write_audit_package` reads:

- `logs/shopify_translation_csv_json_small_batch_apply_plan_package.json`
- `logs/shopify_translation_small_batch_apply_execute.json`
- `logs/shopify_translation_csv_json_small_batch_real_write_readiness_package.json`
- `logs/shopify_translation_csv_json_small_batch_manual_real_run_test_package.json`

It writes:

```text
logs/shopify_translation_csv_json_small_batch_post_write_audit_package.json
logs/shopify_translation_csv_json_small_batch_post_write_audit_package.html
```

This task is local-report-only. It must not call Shopify APIs, call mutations, call `translationsRegister`, perform readback, perform rollback, publish, apply, update, write the database, or git push. It may preserve facts from a prior human-run CSV/JSON small batch real-run, but the audit task itself must never perform new Shopify actions.

The audit may output `audit_status=csv_json_small_batch_post_write_audit_passed` only when the execute report is task `shopify_translation_small_batch_apply_execute`, mode `real-run` or `execute-real-write`, `plan_source=csv_json`, status `small_batch_real_write_succeeded_and_verified`, product/locale/entry count/fields match the CSV/JSON plan, readiness package, and manual test package, fields are limited to `meta_title` and `meta_description`, every readback value matched, no rollback approval is required, no rollback or automatic rollback happened, no publish or bulk write happened, and source blocking conditions are empty. It must keep `audit_package_only=true`, `shopify_api_call_performed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `readback_performed=false`, `rollback_performed=false`, `publish_performed=false`, `real_apply_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### Shopify Product Translation Console Read-Only

Phase 15.0 adds a staff-only internal admin page:

```text
/admin/shopify_sync/translation-console/
```

The page can read one Shopify product by GID / numeric product ID or perform a limited read-only product search, with at most 5 search results. It displays product basics, `translatableResource` content keys, source values, digests, and existing translations for a selected locale (`ja`, `de`, `fr`, `es`, or `it`).

This page is read-only. It must not call OpenAI, generate translations, call Shopify mutations, call `translationsRegister`, write Shopify, publish, apply, rollback, write the database, add migrations, or expose Shopify access tokens. It must keep visible safety flags such as `shopify_read_only=true`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `real_apply_performed=false`, and `rollback_performed=false`.

### Selected Product Missing Translation Draft Package

`shopify_translation_selected_product_missing_translation_draft_package` reads a single selected Shopify product through read-only `translatableResource` queries and checks existing translations for `ja`, `de`, `fr`, `es`, and `it`. The first allowed fields are `title`, `meta_title`, and `meta_description`; `body_html`, handles, images, variants, collections, pages, blogs, theme text, navigation, metafields, and metaobjects remain out of scope.

The task may call OpenAI only to generate local draft text for missing translations. It must skip empty source values, skip existing current translations, and mark outdated existing translations as manual-review-only instead of overwriting them. If `OPENAI_API_KEY` is unavailable and missing translations require draft generation, the task must block with `blocked_missing_openai_api_key`.

Draft quality rules keep `title` at 65 characters or fewer, `meta_title` at 60 characters or fewer, and `meta_description` at 155 characters or fewer. Over-length drafts may receive at most two natural rewrite attempts and must never be crudely truncated. Drafts that remain over-length, include forbidden CTA/shipping/origin claims, or contain mechanical English phrases such as `RC Plane Clevis` must be marked `draft_needs_manual_review` with `eligible_for_apply_plan=false`; only `draft_ready_for_manual_review` entries may set `eligible_for_apply_plan=true`.

Google SEO checks add `seo_validation_status`, `seo_notes`, recommended min/max character ranges, core keyword/model/forbidden phrase indicators, and SEO eligibility for each draft entry. `title` should be 25-65 characters, `meta_title` 30-60 characters, and `meta_description` 80-155 characters. `eligible_for_apply_plan=true` is allowed only when the draft is `draft_ready_for_manual_review` and `seo_validation_status=seo_ready`; too-short SEO copy, missing core keywords, forbidden phrases, duplicate title/meta_title text, or keyword stuffing must require manual review.

The task writes only local JSON/HTML reports under `logs/`. It must not call Shopify mutations, call `translationsRegister`, write Shopify, publish, apply, rollback, update existing Shopify translations, write the database, add migrations, expose tokens, or git push. It must report `draft_package_only=true`, `shopify_read_only=true`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### Selected Product Translation Apply Plan Package

Phase 15.3 adds a Translation Console action that rebuilds the trusted selected-product draft package on the backend, filters only entries eligible for apply planning, and writes local apply-plan review reports:

```text
logs/shopify_translation_selected_product_apply_plan_package.json
logs/shopify_translation_selected_product_apply_plan_package.html
```

The apply plan may include only entries with `eligible_for_apply_plan=true`, `validation_status=draft_ready_for_manual_review`, `seo_validation_status=seo_ready`, no existing current translation, and no outdated translation. Existing translations, outdated translations, drafts needing manual review, and SEO-needs-review drafts must be skipped. This phase is plan-only and must not call Shopify mutations, call `translationsRegister`, write Shopify, publish, apply, rollback, overwrite existing translations, write the database, add migrations, expose tokens, or git push. It must report `apply_plan_only=true`, `existing_translation_overwrite_allowed=false`, `outdated_translation_overwrite_allowed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `apply_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### Selected Product Translation Final Review Package

Phase 15.4 adds a Translation Console action that rebuilds the trusted selected-product draft package, rebuilds the apply plan, then creates the final no-write review package:

```text
logs/shopify_translation_selected_product_final_review_package.json
logs/shopify_translation_selected_product_final_review_package.html
```

The final review package is the last manual-review gate before any future separate write phase. It must not perform Shopify writes or call Shopify mutations, `translationsRegister`, publish, apply, rollback, overwrite existing translations, write the database, add migrations, expose tokens, or git push. It must reject or flag missing digests, missing proposed values, unsupported fields, existing translations, outdated translations, drafts needing manual review, and SEO-needs-review entries. It must report `final_review_only=true`, `apply_plan_only=true`, `manual_ack_required_for_future_write=true`, `existing_translation_overwrite_allowed=false`, `outdated_translation_overwrite_allowed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `apply_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, and `no_new_shopify_writes_performed=true`.

### Selected Product Real Write Readiness Package

Phase 15.5 adds a Translation Console action that rebuilds the trusted selected-product draft package, rebuilds the apply plan, rebuilds the final review package, then creates a no-write real-write readiness package:

```text
logs/shopify_translation_selected_product_real_write_readiness_package.json
logs/shopify_translation_selected_product_real_write_readiness_package.html
```

The readiness package only checks whether a future separate write phase could be prepared for manual ACK. It must not perform Shopify writes or call Shopify mutations, `translationsRegister`, publish, apply, rollback, overwrite existing translations, write the database, add migrations, expose tokens, or git push. It must verify the final review status is ready, `entry_count > 0`, every entry is `ready_for_final_manual_review`, every entry has a digest, locale, field, source value, and proposed translation, locales are limited to `ja`, `de`, `fr`, `es`, and `it`, fields are limited to `title`, `meta_title`, and `meta_description`, and no existing or outdated translations are being overwritten.

Even when readiness passes, the package must keep real writes disabled. It must report `readiness_package_only=true`, `final_review_only=true`, `future_write_allowed=false`, `manual_ack_required_for_future_write=true`, `existing_translation_overwrite_allowed=false`, `outdated_translation_overwrite_allowed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `apply_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### Selected Product Locked Execution Plan

Phase 15.6 adds a Translation Console action that rebuilds the trusted selected-product draft package, rebuilds the apply plan, rebuilds the final review package, rebuilds the real-write readiness package, then creates a locked execution plan:

```text
logs/shopify_translation_selected_product_locked_execution_plan.json
logs/shopify_translation_selected_product_locked_execution_plan.html
```

The locked execution plan may show future `translationsRegister` plan details such as resource ID, locale, key, digest, and planned value, but it must never call Shopify APIs for writes, call mutations, call `translationsRegister`, publish, apply, rollback, overwrite existing translations, write the database, add migrations, expose tokens, or git push. It must remain locked even if a user submits ACK-like or dangerous parameters in POST data.

This package must report `execution_plan_only=true`, `executor_locked=true`, `real_write_allowed=false`, `future_write_allowed=false`, `dangerous_ack_effective=false`, `manual_ack_required_for_future_write=true`, `future_phase_required=true`, `existing_translation_overwrite_allowed=false`, `outdated_translation_overwrite_allowed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `apply_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### Selected Product Locked Executor Shell

Phase 15.7 adds a Translation Console action that rebuilds the trusted selected-product draft package, rebuilds the apply plan, rebuilds the final review package, rebuilds the real-write readiness package, rebuilds the locked execution plan, then creates a locked executor shell report:

```text
logs/shopify_translation_selected_product_locked_executor_shell.json
logs/shopify_translation_selected_product_locked_executor_shell.html
```

The locked executor shell may record whether a manual ACK preview was entered, but it must not store the ACK value and must not make any ACK effective. It must never call Shopify APIs for writes, call mutations, call `translationsRegister`, publish, apply, real apply, rollback, overwrite existing translations, write the database, add migrations, expose tokens, or git push.

This package must report `executor_shell_only=true`, `executor_locked=true`, `execution_plan_only=true`, `real_write_allowed=false`, `future_write_allowed=false`, `dangerous_ack_effective=false`, `manual_ack_required_for_future_write=true`, `future_phase_required=true`, `existing_translation_overwrite_allowed=false`, `outdated_translation_overwrite_allowed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `apply_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### Selected Product Real Write Executor Dry Run

Phase 16.0 adds a Translation Console action that rebuilds the trusted selected-product draft package, rebuilds the apply plan, rebuilds the final review package, rebuilds the real-write readiness package, rebuilds the locked execution plan, rebuilds the locked executor shell, then creates a real-write executor dry-run package:

```text
logs/shopify_translation_selected_product_real_write_executor.json
logs/shopify_translation_selected_product_real_write_executor.html
```

The executor dry-run package is a future real-run gate only. It must not perform Shopify writes, call mutations, call `translationsRegister`, publish, apply, real apply, rollback, overwrite existing translations, write the database, add migrations, expose tokens, or git push. It must require a non-empty Shopify-provided digest for every candidate entry and must never generate a digest locally.

The package may mark entries as `would_write=true` only in dry-run when the selected product scope matches, `entry_count > 0`, `blocked_entry_count=0`, locales are limited to `ja`, `de`, `fr`, `es`, and `it`, fields are limited to `title`, `meta_title`, and `meta_description`, every entry has source/proposed values and digest, no existing/current translation is present, no outdated translation is present, and no blocking conditions exist. Even when the manual ACK preview phrase is entered, it must report `real_write_executor_only=true`, `dry_run_only=true`, `real_write_allowed=false`, `future_write_allowed=false`, `manual_ack_required=true`, `dangerous_ack_effective=false`, `existing_translation_overwrite_allowed=false`, `outdated_translation_overwrite_allowed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `apply_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### Selected Product Real Write Manual Action Package

Phase 16.1 adds a Translation Console action that rebuilds the trusted selected-product draft package, rebuilds the apply plan, rebuilds the final review package, rebuilds the real-write readiness package, rebuilds the locked execution plan, rebuilds the locked executor shell, rebuilds the real-write executor dry-run package, then creates a manual action package:

```text
logs/shopify_translation_selected_product_real_write_manual_action_package.json
logs/shopify_translation_selected_product_real_write_manual_action_package.html
```

The manual action package is the final no-write package before a future separate real write phase. It may show planned `translationsRegister` variables, future PowerShell command preview, readback verification plan, and rollback approval plan. It must not call Shopify APIs, call mutations, call `translationsRegister`, publish, apply, real apply, rollback, overwrite existing translations, execute commands, read `.env`, expose tokens, write the database, add migrations, or git push.

The package must block when the executor dry-run is not ready, `entry_count=0`, `blocked_entry_count>0`, selected product scope mismatches, locale or field falls outside the requested scope, digest or proposed translation is missing, existing/current translation is present, outdated translation is present, prior blocking conditions exist, or any prior no-write safety flag indicates a write/mutation/register/publish/apply/rollback. It must report `manual_ack_required=true`, `manual_ack_effective=false`, `real_write_allowed=false`, `future_write_allowed=false`, `shopify_write_performed=false`, `mutation_performed=false`, `translations_register_called=false`, `publish_performed=false`, `real_apply_performed=false`, `rollback_performed=false`, `no_new_shopify_writes_performed=true`, and `all_new_actions_no_write_confirmed=true`.

### Translation Console Manual Action Smoke Test

`scripts/smoke_test_translation_console_manual_action_package.py` provides a one-command smoke test for the Translation Console chain. The default `--static-only` mode runs on the Windows host and does not call Shopify, OpenAI, Docker, or Django.

For live dry-run validation, run through the Docker web container so the Django project dependencies are available:

```powershell
python scripts\smoke_test_translation_console_manual_action_package.py --live-dry-run --use-docker
```

Equivalent manual Docker command:

```powershell
docker compose exec -T web python manage.py smoke_test_translation_console_manual_action_package --live-dry-run
```

The wrapper intentionally calls the Django management command rather than a container `scripts/` path because the web container mounts the Django app and `manage.py`, while host-only scripts may not be present inside `/app/scripts`.

If host Python lacks Django and `--use-docker` is not supplied, the script must fail gracefully with `failure_type=missing_django_on_host`, keep `no_write_confirmed=true`, and write the JSON/HTML smoke-test report instead of raising a traceback. Live dry-run remains no-write: it may perform the approved read-only/product-draft chain, but must not call Shopify mutations, call `translationsRegister`, publish, apply, real apply, rollback, overwrite translations, or expose secrets.

Before live smoke validation, the recommended basic checks are:

```powershell
python scripts\validate_translation_console_phase.py
python scripts\smoke_test_translation_console_manual_action_package.py --live-dry-run --use-docker
docker compose exec -T web python manage.py check
```

### Shopify Review Request Automation Preparation

Phase 0 review request automation work is documentation and configuration
preparation only. The checklist lives at:

```text
remote_approval/review_request_integration_checklist.md
```

The `.env.example` review request section must contain placeholders only. Do
not add real Ali Reviews / Kudosi tokens, Gmail OAuth credentials, Shopify
tokens, Trustpilot private links, or other secrets.

Any future review request task must start as a dry-run report-only task. Phase 0
and Phase 1 must not send customer email, call the Gmail API, call the Ali
Reviews / Kudosi API, call Shopify `tagsAdd` / `tagsRemove`, write Shopify data,
write the database, or git push. Shopify tag mutations require a later separate
write phase after `write_orders` and `write_customers` scopes are confirmed.

`shopify_review_request_tag_discovery` is a Phase 0.1 read-only task. It queries
recent Shopify order tags and writes:

```text
logs/shopify_review_request_tag_discovery.json
logs/shopify_review_request_tag_discovery.html
```

The report must preserve exact tag strings from Shopify and include Unicode code
points, half-width/full-width colon detection, spelling detection for `review`
versus `reveiw`, order counts, and example order names/IDs. Treat `1: reveiw
request` and `1: review request` as different tags. Treat `:` / U+003A and `：`
/ U+FF1A as different characters. The task must not normalize, correct, trim,
translate, or rewrite tag values, and must always recommend
`use_exact_shopify_api_value_only`.

The tag discovery task must not call Shopify mutations, `tagsAdd`, `tagsRemove`,
Ali Reviews / Kudosi APIs, Gmail APIs, or any email-sending path.

`shopify_review_request_ali_reviews_capability_discovery` is a Phase 0.2
docs-only task. It writes local reports only:

```text
logs/shopify_review_request_ali_reviews_capability_discovery.json
logs/shopify_review_request_ali_reviews_capability_discovery.html
```

The report records the public API base URL `https://pub.kudosi.ai`, known public
API capabilities, missing or unconfirmed send/status capabilities, dashboard
pages to check, and support questions. It must keep
`automation_decision_status=blocked_until_send_and_status_capabilities_confirmed`
until Ali Reviews / Kudosi confirms whether order-specific review request send
and sent-status APIs exist.

This task must not call Ali Reviews / Kudosi APIs, Gmail APIs, Shopify APIs,
Shopify mutations, `tagsAdd`, `tagsRemove`, or any email-sending path. If Ali
Reviews / Kudosi cannot confirm send/status API support, future automation must
only produce Shopify candidate reports and may require manual sending in the Ali
Reviews dashboard.

`shopify_review_request_gmail_readiness_package` is a Phase 0.3 docs-only task.
It writes local reports only:

```text
logs/shopify_review_request_gmail_readiness_package.json
logs/shopify_review_request_gmail_readiness_package.html
```

The report records Gmail send readiness for `info@kidstoylover.com`, required
OAuth environment variable names, the least-privilege Gmail send scope
`https://www.googleapis.com/auth/gmail.send`, Trustpilot review link readiness,
and `automation_decision_status=blocked_until_gmail_oauth_and_template_confirmed`.

This task must not call Gmail APIs, send email, call Shopify APIs, write Shopify
data, call Shopify mutations, call `tagsAdd`, call `tagsRemove`, or call Ali
Reviews / Kudosi APIs. Future email send phases must start with preview-only
reports and require final human approval before any customer email is sent.

`shopify_review_request_shopify_tag_permission_readiness` is a Phase 0.4
docs-only task. It writes local reports only:

```text
logs/shopify_review_request_shopify_tag_permission_readiness.json
logs/shopify_review_request_shopify_tag_permission_readiness.html
```

The report records required Shopify order/customer tag scopes, future
`tagsAdd` / `tagsRemove` requirements, exact existing tags, future candidate
tags, and `automation_decision_status=blocked_until_shopify_write_scopes_and_manual_approval_confirmed`.
It must confirm full-field tag overwrites are not allowed.

This task must not call Shopify APIs, write Shopify data, call Shopify
mutations, call `tagsAdd`, call `tagsRemove`, call Ali Reviews / Kudosi APIs,
call Gmail APIs, or send email. Future Shopify tag write phases must start with
a dry-run plan and require manual approval before any tag mutation is performed.

`shopify_review_request_candidate_scan` is a Phase 1 / Phase 1.1 read-only dry-run task. It
queries recent Shopify orders and writes local candidate reports only:

```text
logs/shopify_review_request_candidate_scan.json
logs/shopify_review_request_candidate_scan.html
```

The report must preserve exact tag matching for `Delivered` and `1: reveiw
request`, treat `1: reveiw request` and `1: review request` as different tags,
and treat half-width `:` / U+003A and full-width colon U+FF1A as different
characters. It classifies orders into report buckets such as
`ready_for_manual_ali_reviews_check`,
`existing_manual_review_request_tag_present`,
`delivered_but_ali_status_unknown`, `repeat_customer_trustpilot_candidate`,
blocked buckets, and `needs_manual_review`.

Phase 1.1 adds a read-only support ticket / risk filter and should report
`scanner_version=phase_1_1_ticket_filter` with ticket diagnostics such as
`ticket_status_check`, `ticket_query_performed`, `ticket_matches_found_count`,
`orders_with_ticket_match_count`, and `orders_blocked_by_ticket_count`.

Run the Phase 1.1 scanner with:

```powershell
python remote_approval_runner.py --task shopify_review_request_candidate_scan --approval local
```

The ticket filter may match local tickets by Shopify order name, local
`order_no`, Shopify order ID token, or customer email in memory. Reports must
mask customer emails, must not output customer addresses or phone numbers, and
must not output ticket body, ticket comments, or full raw email. Blocking or
uncertain ticket status must route the order/customer to a blocked or
manual-review bucket, not a ready-to-send bucket.

The scanner must not call Gmail APIs, send email, call Ali Reviews / Kudosi
APIs, write Shopify data, call Shopify mutations, call `tagsAdd`, or call
`tagsRemove`.

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
