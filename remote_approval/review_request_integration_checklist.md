# Shopify Review Request Automation - Integration Checklist

Phase 0 is integration preparation only. This checklist is for documenting
required systems, permissions, and local readiness before any implementation
that could contact external services.

## Safety Boundary

- Phase 0 must not send customer email.
- Phase 0 must not write Shopify data, add tags, remove tags, or call mutations.
- Phase 0 must not call the Ali Reviews / Kudosi API.
- Phase 0 must not call the Gmail API.
- Phase 1 must remain dry-run report only unless a later project rule explicitly
  changes the phase boundary.
- Do not store real tokens, OAuth credentials, or API keys in this checklist,
  `.env.example`, logs, or Git.

## Required External Integrations

### Shopify Order Tag Discovery

- [x] Run the first review-request task as a read-only Shopify order tag
  discovery report before building any automation.
- [x] Query recent Shopify orders read-only and collect exact raw tag strings
  containing `review`, `reveiw`, `request`, or `Delivered`.
- [x] Confirm the exact Shopify API value for the screenshot-observed candidate
  tag: `1: reveiw request`.
- [x] Confirm the colon in `1: reveiw request` is half-width `:` / U+003A
  COLON, not full-width `：` / U+FF1A FULLWIDTH COLON.
- [x] Confirm the spelling is `reveiw`, not `review`.
- [x] Confirm `Delivered` also exists as an exact order tag.
- [x] Preserve the exact colon, spelling, spacing, and character width returned
  by Shopify; do not normalize, correct, trim, translate, or rewrite tag values.
- [x] Treat `1: reveiw request` and `1: review request` as separate raw Shopify
  tag values, but Phase 5.28A read checks accept both as review-request trigger
  aliases. Future writes must use canonical `1: review request`.
- [x] Treat half-width colon `:` / U+003A and full-width colon `：` / U+FF1A
  as separate characters.
- [x] Include Unicode code points for candidate tags, especially tags containing
  `:` or `：`.
- [x] Count how many orders contain each candidate tag and include example order
  names/IDs for human review.
- [x] Use recommendation `use_exact_shopify_api_value_only` in the report.
- [x] Keep `shopify_review_request_tag_discovery` read-only: no Shopify
  mutation, no `tagsAdd`, no `tagsRemove`, no customer email, no Ali Reviews /
  Kudosi API call, and no Gmail API call.

Confirmed Phase 0.1 report facts:

- Orders queried: 100.
- Candidate tag count: 2.
- Candidate tags found: `1: reveiw request` and `Delivered`.
- Safety confirmed: read-only Shopify query only; no Shopify writes, no
  `tagsAdd`, no `tagsRemove`, no Ali Reviews / Kudosi API call, no Gmail API
  call, and no email sending.
- Future automation must preserve exact Shopify API tag values. Read checks may
  match the approved aliases `1: review request` and `1: reveiw request`; future
  writes must use canonical `1: review request`.

### Ali Reviews / Kudosi API

- [ ] Confirm whether the integration is Ali Reviews, Kudosi, or both.
- [ ] Obtain official API documentation.
- [ ] Confirm the authentication method and token format without recording the
  token value in Git.
- [ ] Confirm read endpoints needed to identify eligible review requests.
- [ ] Confirm whether any write endpoint is required. If yes, defer it to a
  later explicitly approved phase.
- [ ] Confirm rate limits, retry rules, and error response format.
- [ ] Confirm sandbox/test capability or a safe non-production testing path.
- [ ] Confirm how to check whether Ali Reviews / Kudosi has already sent a
  review request email for an order before any future send/tag action.
- [ ] Confirm how Ali Reviews automatic email rules based on order age are
  represented in the backend/API, because those automatic sends do not
  automatically remove the Shopify tag observed in the current manual workflow.

#### Phase 0.2 Capability Discovery

- [x] Public API documentation exists for Ali Reviews / Kudosi.
- [x] Public API base URL documented as `https://pub.kudosi.ai`.
- [ ] Confirm API key availability for the current merchant plan.
- [ ] Confirm where API keys are created and how access can be scoped.
- [ ] Do not store the API key in this checklist, reports, logs, `.env.example`,
  or Git.

Known public API capabilities to document in the Phase 0.2 report:

- List Reviews.
- React to a Review.
- Product Ratings.
- List Questions.
- React to a Question.

Missing or unconfirmed capabilities that block real automation:

- Sending a review request email for a specific Shopify order.
- Checking whether a review request email has already been sent for a Shopify
  order.
- Checking whether a customer already received a review request email.
- Searching request history by Shopify order ID, order name, customer email, or
  product ID.
- Auto-request email scheduled, sent, opened, clicked, failed, or bounced
  status.
- Webhooks for review request sent or review submitted.
- Exporting manual review request history.
- Exporting auto-request history.
- Documented API rate limits.

Questions to ask Ali Reviews / Kudosi support:

- Does Kudosi / Ali Reviews provide an API endpoint to send a review request
  email for a specific Shopify order?
- Does Kudosi / Ali Reviews provide an API endpoint to check whether a review
  request email has already been sent for a Shopify order?
- Can the API search by Shopify order ID, order name, customer email, or product
  ID?
- Does the API expose auto-request email status, scheduled status, sent status,
  opened/clicked status, or failed status?
- Is there a webhook for review request sent / review submitted?
- Can manual review request history be exported?
- Can auto-request history be exported?
- Are API keys available in the current plan?
- Are rate limits documented?

Required Ali Reviews dashboard screenshots/pages to collect:

- Auto-Request email settings page.
- Auto-request rule timing after fulfillment.
- Manual review request send screen.
- Order-level or customer-level review request history.
- Sent, scheduled, failed, opened, clicked, or bounced request-email status
  page, if present.
- Manual request history export page, if present.
- Auto-request history export page, if present.
- API key / developer settings page.
- Rate limit or developer documentation page.

Phase 0.2 automation decision:

- `automation_decision_status=blocked_until_send_and_status_capabilities_confirmed`.
- Do not call Ali Reviews / Kudosi APIs during Phase 0.2.
- Do not send any review request during Phase 0.2.
- If send/status API support cannot be confirmed, future automation must only
  produce Shopify candidate reports and may require manual sending inside the
  Ali Reviews dashboard.
- Never assume Shopify tag `1: reveiw request` means Ali Reviews / Kudosi has
  sent or has not sent the email.

#### Phase 5.1 History / Debug Ledger

- [x] Keep Ali Reviews / Kudosi automation blocked until vendor request API
  documentation is available.
- [x] Use the Trustpilot/Gmail history ledger as a read-only debug surface for
  candidate selection, duplicate blocks, draft evidence, send preflight,
  send result, tag-write evidence, and API capability status.
- [x] Keep ledger reports privacy-safe: masked emails only, partial Gmail IDs
  only, no Gmail draft create/send/delete, no Shopify write/tag change, no
  external review API call, and no tracking token or redirect.

#### Phase 5.28G Review Queue Batch Limit

- [x] Keep the last-60-days candidate scan broad and report the full eligible
  candidate total.
- [x] Add a separate Trustpilot review queue layer for the admin approval page.
- [x] Limit the visible review batch to 20 candidates by default.
- [x] Sort the review batch by most recent delivered/updated/created date,
  clean tags, merge/related ambiguity, duplicate risk, and order number
  descending.
- [x] Include `review_queue_rank`, `visible_in_review_batch`, and
  `hidden_reason` diagnostics for eligible candidates, including #22530 and
  #22562 when present in the candidate report.
- [x] Keep the phase scan/UI/report only: no Gmail API, no email send, no
  Shopify write, no Shopify mutation, no external review API, and no raw email
  output.

#### Phase 5.28N eBay Blocker and Trustpilot Post-Send Tag Write

- [x] Block any order/customer with local Shopify tag text matching `ebay`,
  `eBay`, `EBAY`, `e-bay`, or `e bay` before it can enter Needs review email.
- [x] Show blocked eBay orders with reason
  `eBay order — Trustpilot email not allowed.` and include
  `blocked_ebay_order_count` in scan/audit reports.
- [x] Add locked task
  `shopify_review_request_trustpilot_post_send_tag_write` for one successful
  post-send audited order only.
- [x] Require exact approval env
  `SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE=YES_I_APPROVE_TRUSTPILOT_TAG_WRITE_FOR_SENT_ORDER`
  before any Shopify API call.
- [x] With approval, add exact tag `1: trustpilot` and remove review-request
  trigger aliases `1: review request` and `1: reveiw request` using Shopify
  tag mutations only; preserve all other tags and never touch `Delivered`.
- [x] Without approval, report `blocked_missing_tag_write_approval` and perform
  no Shopify API call, no Shopify write, no Gmail action, and no external
  review API call.

#### Phase 5.28O Post-Send Tag Write Source Reliability

- [x] The Trustpilot post-send tag-write task can use the same Django/web
  post-send audit builder as the Review Request workbench before any Shopify
  tag-write approval branch runs.

#### Phase 5.30 Dashboard Counter Refresh and Already Sent Pagination

- [x] Recalculate dashboard counters from the same live local scan used by the
  visible Review Requests queue, merged with latest Review & Send, post-send
  audit, tag-write reports, and local Shopify tag evidence.
- [x] Show candidate scan freshness, last sent record time, last tag-write time,
  and a stale-data warning when local sync/candidate evidence may be stale.
- [x] Sort Already sent newest first, show sent time or `Time not recorded`,
  show tag status/evidence safely, and paginate independently with
  `sent_page` / `sent_page_size`.
- [x] Add `shopify_review_request_dashboard_counts_audit` as a local no-write
  audit task. It must not call Gmail, Shopify, external review APIs, or
  `translationsRegister`.
- [x] If host-side post-send audit evidence is missing or stale, the task checks
  the web/container audit builder and local history-ledger reports before
  deciding whether the sent order is ready.
- [x] Blocked reports include `source_paths_checked`, host/web/history source
  found flags, selected order, email sent confirmation, sent count, and
  `why_not_ready`.

#### Phase 5.29 Automatic Post-Send Shopify Tag Write

- [x] Admin `Review & Send` now builds an immediate in-memory post-send audit
  after a successful Gmail drafts.send result.
- [x] If the audit confirms exactly one sent order and the selected order
  matches, the same one-order Shopify tag-write helper adds `1: trustpilot`
  and removes `1: review request` / `1: reveiw request` aliases.
- [x] No Shopify tag write is attempted when Gmail send fails, when the
  post-send audit fails, or when the selected order does not match.
- [x] The manual
  `shopify_review_request_trustpilot_post_send_tag_write` runner still requires
  `SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE=YES_I_APPROVE_TRUSTPILOT_TAG_WRITE_FOR_SENT_ORDER`.
- [x] Existing Sent / Tag pending rows remain pending until the strict manual
  one-order post-send tag write handles that exact audited order.
- [x] The no-approval run remains no-write: no Shopify API call, no Shopify tag
  write, no Gmail action, no external review API call, and no
  `translationsRegister`.
- [x] Phase 5.29B fixes the manual post-send tag-write runner shell payload:
  source audit data is passed as a JSON string and parsed with `json.loads(...)`
  inside Django shell, so generated code does not inject JSON `true` / `false`
  literals into Python.
- [x] Phase 5.29C tightens post-send tag-write verification: readback is
  verified only when `1: trustpilot` is present and every review-request alias
  is absent, and the local `ShopifyOrder.shopify_tags` cache is updated from
  the verified Shopify readback before the order is treated as Tag written.
- [x] Phase 5.29D adds a strict one-order Sent / Tag pending repair path for
  `#21284` only. It requires
  `SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE_ORDER="#21284"` and the exact
  tag-write approval env before any Shopify API call.
- [x] The Phase 5.29D repair path verifies local Review Request history/queue
  evidence that the target row is `Sent` and `Tag pending`, blocks any other
  target with `blocked_target_order_not_allowed_for_repair_phase`, and does
  not provide a batch repair path.

### Shopify Admin API Tag Permissions

- [ ] Confirm the app has the required `write_orders` scope before any order tag
  mutation is designed.
- [ ] Confirm the app has the required `write_customers` scope before any
  customer tag mutation is designed.
- [ ] Confirm planned tag names for sent, suppressed, skipped, or failed review
  request states.
- [ ] Confirm the automation can first produce a no-write report showing exactly
  which records would receive `tagsAdd` or `tagsRemove`.
- [ ] Confirm rollback/manual correction expectations for any future tag write
  phase.

#### Phase 0.4 Shopify Tag Write Readiness

Required Shopify scopes for order tags:

- `read_orders`
- `write_orders`

Required Shopify scopes for customer tags:

- `read_customers`
- `write_customers`

Required future GraphQL Admin API mutations:

- `tagsAdd`
- `tagsRemove`

Tag-write safety rules:

- [ ] Phase 0.4 must not call Shopify APIs.
- [ ] Phase 0.4 must not write Shopify data.
- [ ] Phase 0.4 must not run `tagsAdd`.
- [ ] Phase 0.4 must not run `tagsRemove`.
- [ ] Never overwrite the full Shopify `tags` field directly.
- [ ] Use `tagsAdd` and `tagsRemove` only in a later explicitly approved write
  phase.
- [ ] Preserve exact tag strings and use exact string matching.
- [ ] Existing exact review request tag: `1: reveiw request`.
- [ ] Existing exact delivered tag: `Delivered`.
- [ ] Do not remove existing tag `1: reveiw request` in Phase 0.4.
- [ ] Do not remove `Delivered` in Phase 0.4 or later automation.
- [ ] Do not remove `1: reveiw request` until a later phase has confirmed Ali
  Reviews / Kudosi sent-status handling.

Future candidate tags for a later dry-run plan only:

- `review_request_ali_sent`
- `review_request_ali_already_sent`
- `review_request_ali_failed`
- `trustpilot_request_sent`
- `review_request_blocked`
- `review_request_no_email`
- `review_request_has_ticket`
- `review_request_refunded`
- `review_request_cancelled`
- `review_request_shipping_issue`

Phase 0.4 automation decision:

- `automation_decision_status=blocked_until_shopify_write_scopes_and_manual_approval_confirmed`.
- Future tag writes require confirmed Shopify scopes, exact target resources, a
  dry-run plan, and manual approval.
- Phase 0.4 is report-only and does not authorize any Shopify tag write.

### Gmail API Send Permission

- [ ] Confirm Gmail OAuth is configured for `info@kidstoylover.com`.
- [ ] Confirm Gmail API send permission is granted and limited to the required
  sender account.
- [ ] Confirm sender name, reply-to behavior, and unsubscribe/compliance text.
- [ ] Confirm test mode can render email previews without sending.
- [ ] Confirm future send logic requires a separate manual approval gate.

#### Phase 0.3 Gmail Readiness

- [ ] Gmail sending account: `info@kidstoylover.com`.
- [ ] Gmail API must be enabled in Google Cloud.
- [ ] OAuth client ID is required and must be stored only in local secret
  configuration, not in Git.
- [ ] OAuth client secret is required and must be stored only in local secret
  configuration, not in Git.
- [ ] Gmail refresh token is required and must be stored only in local secret
  configuration, not in Git.
- [ ] Minimum Gmail scope:
  `https://www.googleapis.com/auth/gmail.send`.
- [ ] Do not use broad Gmail scope unless a later phase explicitly proves it is
  needed: `https://mail.google.com/`.
- [ ] Sending identity must match or be authorized to send as
  `info@kidstoylover.com`.
- [ ] Trustpilot review link must be configured before preview generation.
- [ ] No real email sending is allowed until a dry-run preview report is
  generated, reviewed, and manually approved.
- [ ] Never use Gmail API read scopes or inbox/message reads unless a future
  phase explicitly approves them.

Required local environment placeholders:

- `GMAIL_SEND_FROM=info@kidstoylover.com`
- `GOOGLE_GMAIL_CLIENT_ID=`
- `GOOGLE_GMAIL_CLIENT_SECRET=`
- `GOOGLE_GMAIL_REFRESH_TOKEN=`
- `GOOGLE_GMAIL_SCOPES=https://www.googleapis.com/auth/gmail.send`
- `TRUSTPILOT_REVIEW_LINK=`

Initial Trustpilot email template draft for review only:

```text
Subject:
Thank you for your support

Body:
Hi {{ first_name }},

Thank you again for your recent order from Kidstoylover.

We really appreciate your continued support. If you have a moment, it would mean a lot to us if you could share your experience on Trustpilot:

{{ trustpilot_review_link }}

Your feedback helps other RC hobby customers feel more confident when choosing from our store.

Thank you again for supporting Kidstoylover.

Kind regards,
Xiang
Kidstoylover
```

Phase 0.3 automation decision:

- `automation_decision_status=blocked_until_gmail_oauth_and_template_confirmed`.
- Do not call Gmail APIs during Phase 0.3.
- Do not send any email during Phase 0.3.
- Future send phases must require customer eligibility checks for
  repeat/high-value status and ticket/refund/shipping issue suppression before
  final human approval.

### Trustpilot Review Link

- [ ] Confirm the official Trustpilot review invitation/review link.
- [ ] Confirm whether links need order/customer-specific parameters.
- [ ] Confirm approved customer-facing wording for review invitations.
- [ ] Confirm whether Trustpilot has its own invitation API that must remain out
  of scope for Phase 0 and Phase 1.

### Ticket System Filtering Rules

- [ ] Define eligible ticket statuses.
- [ ] Define excluded ticket tags, order tags, customer tags, or issue types.
- [ ] Define timing rules, such as days after delivery or ticket resolution.
- [ ] Define duplicate prevention rules.
- [ ] Define suppression rules for refunds, complaints, replacements, returns,
  chargebacks, privacy requests, and manual opt-outs.
- [ ] Confirm how Shopify `Delivered` tags map to ticket/order eligibility.
- [ ] Confirm that Ali Reviews / Kudosi delivery detection is not trusted as the
  sole delivery status source.
- [ ] Confirm report fields needed for human review before any send/write phase.

## Phase 0 Outputs

- [ ] Documentation exists for external integration requirements.
- [ ] `.env.example` contains placeholders only and no real secrets.
- [ ] Project safety rules block external calls and writes during Phase 0.
- [ ] Local approval workflow documentation describes review request preparation
  as docs/config/report-only work.
- [ ] Read-only tag discovery report task is available:
  `shopify_review_request_tag_discovery`.
- [ ] Git status has been reviewed before any later commit request.

## Future Phase Gate Notes

- First implementation must generate a dry-run report only.
- No customer email may be sent during Phase 0 or Phase 1.
- No Shopify write or mutation may be performed during Phase 0 or Phase 1.
- No Ali Reviews / Kudosi API call is allowed until API documentation and token
  handling are confirmed.
- No Gmail sending is allowed until Gmail OAuth and send permission are
  confirmed.
- No Shopify `tagsAdd` or `tagsRemove` call is allowed until required Shopify
  scopes are confirmed and a separate write phase is approved.

## Phase 4.2 Review Request Workbench

- [x] Add a read-only admin workbench at
  `/admin/shopify_sync/review-request-workbench/`.
- [x] Use local synced order data and local review-request JSON reports only.
- [x] Keep customer email display masked by default.
- [x] Do not add send, draft, Shopify tag write, review API, or tracking
  redirect actions.
- [x] Keep the exact existing Shopify review-request tag as
  `1: reveiw request`; do not treat corrected spelling as equivalent.
- [x] Show Trustpilot invitation aliases exactly as local reports recorded
  them, including `1: trustpilot`, `1: trustpoilt`, `1:trustpilot`,
  `1 : trustpilot`, `1:trustpoilt`, and `1 : trustpoilt`.

Future tracking design note:

- Gmail alone cannot prove that a customer clicked a Trustpilot link or left a
  review.
- Future click tracking would need a separate, explicitly approved local
  redirect token/link design.
- Future review detection would need Trustpilot Business/API/export support or
  Kudosi/Ali Reviews API, webhook, or export support.
- Phase 4.2 does not enable redirects, call Trustpilot/Kudosi/Ali Reviews APIs,
  call Gmail APIs, send email, or write Shopify data.

## Phase 4.8C Customer-Level Trustpilot Duplicate Suppression

- [x] Add a local audit task:
  `shopify_review_request_customer_level_trustpilot_duplicate_audit`.
- [x] Audit order `#22620` against prior Trustpilot order `#22621` using local
  DB identity where available and existing local reports only.
- [x] Treat a prior successful Trustpilot Gmail send report, Trustpilot tag
  write report, Trustpilot tag write audit, or local Trustpilot alias tag report
  as a customer-level suppression signal.
- [x] Block any matching customer/email signal with classification
  `blocked_existing_trustpilot_invitation_customer_level`.
- [x] Keep raw customer emails internal only; JSON/HTML reports must contain
  masked email and boolean comparison fields only.
- [x] Existing unsent Gmail drafts for a blocked order must not be sent.
  Optional cleanup/deletion requires a separate locked phase.
- [x] Phase 4.8C does not create Gmail drafts, send Gmail, delete Gmail drafts,
  write Shopify tags, remove Shopify tags, call Trustpilot/Kudosi/Ali Reviews
  APIs, enable tracking redirects, or generate tracking tokens.

## Phase 5.4 First-Class Review Requests Module

- [x] Review Requests appears in the internal admin module navigation as a
  first-class module alongside Tickets and Settlement.
- [x] Existing URL remains:
  `/admin/shopify_sync/review-request-workbench/`.
- [x] Current access rule is admins only: Django superusers or staff users in
  the `Admin` group. Finance and Shenzhen Warehouse users are not granted
  Review Requests access in this phase.
- [x] The workbench page displays an admins-only/read-only note.
- [x] Review Requests remains read-only until future write/send phases are
  explicitly run through locked tasks.
- [x] Phase 5.4 does not create Gmail drafts, send Gmail, delete Gmail drafts,
  write Shopify tags, remove Shopify tags, call Trustpilot/Kudosi/Ali Reviews
  APIs, enable tracking redirects, or generate tracking tokens.

## Phase 5.5 Review Requests Usability Dashboard

- [x] Simplify the Review Requests workbench into an operating dashboard for
  normal admin users.
- [x] Keep the existing URL:
  `/admin/shopify_sync/review-request-workbench/`.
- [x] Keep access admins-only: Django superusers or staff users in the `Admin`
  group.
- [x] Show plain-English status cards for ready orders, blocked orders, sent
  Trustpilot emails, and Ali Reviews API readiness.
- [x] Show a simple Trustpilot automation pipeline and highlight that the
  current state is waiting for eligible orders.
- [x] Show clear next actions for the current known cases:
  `#22620` is blocked as a duplicate customer after Trustpilot was sent via
  `#22621`, and `#22582` is not ready because delivery, canonical review tag,
  and related-order readiness checks are not satisfied.
- [x] Move report paths, technical flags, source report details, ledger rows,
  and low-level queue tables into a collapsed advanced debug section.
- [x] Keep the dashboard read-only. Phase 5.5 does not create Gmail drafts,
  send Gmail, delete Gmail drafts, write Shopify tags, remove Shopify tags,
  call Trustpilot/Kudosi/Ali Reviews APIs, enable tracking redirects, or
  generate tracking tokens.

## Phase 5.6 Trustpilot Automation Dry-Run Orchestrator

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_automation_dry_run`.
- [x] Orchestrate existing local review-request candidate logic, Trustpilot
  eligibility checks, customer-level duplicate blockers, Gmail readiness, and
  Shopify tag-write readiness into one dry-run report.
- [x] Generate local JSON/HTML reports only:
  `logs/shopify_review_request_trustpilot_automation_dry_run.json` and
  `logs/shopify_review_request_trustpilot_automation_dry_run.html`.
- [x] No email is sent.
- [x] No Gmail draft is created, deleted, or sent.
- [x] No Shopify tag is written and no Shopify mutation is called.
- [x] No Trustpilot, Kudosi, or Ali Reviews API is called.
- [x] Current blockers remain enforced:
  `#22620` must not be sent because the same customer already received a
  Trustpilot invitation via `#22621`; `#22582` must not be sent yet because it
  is not delivered, is missing `1: review request`, and related order group
  `#22582/#22581` is not ready.
- [x] The Review Request workbench shows the Trustpilot automation status near
  the top and keeps report paths, raw flags, and source details inside
  collapsed Advanced debug details.
- [x] The next phase should be a locked real-send package only after a truly
  eligible candidate exists and a separate approval confirms the exact action.

## Phase 5.7 Trustpilot Locked Send Readiness Package

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_locked_send_readiness_package`.
- [x] Build a dry-run Trustpilot automation queue from local reports/helpers:
  eligible candidates, blocked candidates, duplicate blockers, delivered-tag
  checks, canonical `1: review request` checks, related-order readiness checks,
  and ticket/refund/risk blockers.
- [x] Generate local JSON/HTML readiness reports only:
  `logs/shopify_review_request_trustpilot_locked_send_readiness_package.json`
  and
  `logs/shopify_review_request_trustpilot_locked_send_readiness_package.html`.
- [x] If no eligible candidate exists, report
  `package_status=blocked_no_eligible_candidate`.
- [x] If exactly one eligible candidate exists later, report
  `package_status=locked_send_ready_for_human_approval` while keeping real
  execution disabled.
- [x] If more than one eligible candidate exists later, report
  `package_status=blocked_multiple_candidates_require_manual_selection`.
- [x] Show the future locked send command shape as a preview only; do not
  execute it and do not create a real-send task in this phase.
- [x] No Gmail draft is created, updated, deleted, or sent.
- [x] No Shopify tag is written, removed, overwritten, or mutated.
- [x] No Trustpilot, Kudosi, or Ali Reviews API is called.
- [x] `#22620` remains blocked because the same customer already received
  Trustpilot via `#22621`.
- [x] `#22582` remains blocked because it is not delivered, is missing
  `1: review request`, and related order group `#22582/#22581` is not ready.
- [x] The Review Requests dashboard shows the Trustpilot Send Readiness status,
  ready/blocked counts, selected candidate, next admin action, known blockers,
  and collapsed future command preview.
- [x] The history/debug ledger includes the locked send readiness package and
  candidate blocker rows while keeping raw technical details in Advanced debug
  details.
- [x] The next phase can create a locked real-send execute task only after a
  true eligible candidate exists and a separate human approval confirms the
  exact action.

## Phase 5.8 Trustpilot Auto Queue Refresh

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_auto_queue_refresh`.
- [x] Refresh the Trustpilot queue/readiness status for the dashboard from local
  reports without sending, drafting, writing tags, or calling external review
  APIs.
- [x] Generate local JSON/HTML refresh reports only:
  `logs/shopify_review_request_trustpilot_auto_queue_refresh.json` and
  `logs/shopify_review_request_trustpilot_auto_queue_refresh.html`.
- [x] Safe for a future scheduler because it is dry-run only.
- [x] No Gmail draft is created, updated, deleted, or sent.
- [x] No Shopify tag is written, removed, overwritten, or mutated.
- [x] No Trustpilot, Kudosi, or Ali Reviews API is called.
- [x] Current result remains no eligible candidate:
  `refresh_status=refreshed_no_eligible_candidate`,
  `next_real_step=wait_no_candidate`, and source readiness remains
  `blocked_no_eligible_candidate`.
- [x] `#22620` remains blocked because the same customer already received
  Trustpilot via `#22621`.
- [x] `#22582` remains blocked because it is not delivered, is missing
  `1: review request`, and related order group `#22582/#22581` is not ready.
- [x] The Review Requests dashboard shows Automation Refresh status, last
  refresh time, ready/blocked counts, next real step, next admin action, and the
  scheduler-safe note.
- [x] The next phase can add a scheduler hook or locked send execute only after
  an eligible candidate appears and a separate human approval confirms the exact
  action.

## Phase 5.9 Shopify Order Sync Auto Refresh Hook

- [x] Add the safe internal hook that refreshes the Trustpilot queue after
  Shopify order sync completes.
- [x] Keep the hook best-effort and non-blocking so Shopify order sync still
  completes if the refresh fails.
- [x] Keep the hook dry-run/read-only only.
- [x] No Gmail draft is created, updated, deleted, or sent.
- [x] No Shopify tag is written, removed, overwritten, or mutated.
- [x] No Trustpilot, Kudosi, or Ali Reviews API is called.
- [x] The existing auto queue refresh report records
  `last_auto_refresh_trigger=shopify_order_sync`,
  `last_auto_refresh_status`, `last_auto_refresh_at`, and sanitized
  `last_auto_refresh_error` when needed.
- [x] The Review Requests dashboard shows the latest hook/refresh status,
  trigger, refresh time, queue counts, known blockers, and sanitized advanced
  debug details.
- [x] Add the fixed local approval audit task
  `shopify_review_request_order_sync_auto_refresh_hook_audit`.
- [x] The next phase can add locked send execute only when a true eligible
  candidate exists and a separate human approval confirms the exact action.

## Phase 5.10 Trustpilot Locked Gmail Send Gate

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_locked_gmail_send_gate`.
- [x] Generate local JSON/HTML gate reports only:
  `logs/shopify_review_request_trustpilot_locked_gmail_send_gate.json` and
  `logs/shopify_review_request_trustpilot_locked_gmail_send_gate.html`.
- [x] Read the latest Trustpilot auto queue refresh, locked send readiness
  package, automation dry-run, and optional history ledger audit reports.
- [x] Current gate blocks because no eligible Trustpilot candidate exists:
  `gate_status=blocked_no_eligible_candidate`.
- [x] No Gmail API is called.
- [x] No Gmail draft is created, updated, deleted, or sent.
- [x] No email is sent.
- [x] No Shopify tag is written, removed, overwritten, or mutated.
- [x] No Trustpilot, Kudosi, or Ali Reviews API is called.
- [x] `#22620` remains blocked because the same customer already received
  Trustpilot via `#22621`.
- [x] `#22582` remains blocked because it is not delivered, is missing
  `1: review request`, and related order group `#22582/#22581` is not ready.
- [x] Future real Trustpilot Gmail send requires exactly one safe eligible
  candidate and explicit ACK
  `SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK=YES_I_APPROVE_ONE_TRUSTPILOT_GMAIL_SEND`.

## Phase 5.11 Trustpilot Gmail Send Executor Shell

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_gmail_send_executor_shell`.
- [x] Generate local JSON/HTML executor shell reports only:
  `logs/shopify_review_request_trustpilot_gmail_send_executor_shell.json` and
  `logs/shopify_review_request_trustpilot_gmail_send_executor_shell.html`.
- [x] Read the latest locked Gmail send gate report and report whether a future
  real send implementation could proceed.
- [x] Current executor remains blocked because no eligible Trustpilot candidate
  exists: `executor_status=blocked_no_eligible_candidate`.
- [x] No Gmail API is called.
- [x] No Gmail draft is created, updated, deleted, or sent.
- [x] No email is sent.
- [x] No Shopify tag is written, removed, overwritten, or mutated.
- [x] No Trustpilot, Kudosi, or Ali Reviews API is called.
- [x] Future real send requires the gate to be ready, exactly one eligible
  candidate, and explicit ACK
  `SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK=YES_I_APPROVE_ONE_TRUSTPILOT_GMAIL_SEND`.
- [x] Current status remains blocked because no eligible candidate exists.

## Phase 5.12 Trustpilot Candidate Simulator

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_candidate_simulator`.
- [x] Generate local JSON/HTML simulator reports only:
  `logs/shopify_review_request_trustpilot_candidate_simulator.json` and
  `logs/shopify_review_request_trustpilot_candidate_simulator.html`.
- [x] Generate simulator-only downstream fixtures for the locked Gmail send
  gate and executor shell.
- [x] Use fake candidate data only, including sandbox order
  `#SIM-TRUSTPILOT-001` and masked email `s***@example.invalid`.
- [x] Default simulator mode is `no_candidate`; supported modes are
  `one_eligible_candidate`, `multiple_eligible_candidates`, and
  `unsafe_candidate`.
- [x] No Shopify API is called.
- [x] No Gmail API is called.
- [x] No Gmail draft is created, updated, deleted, or sent.
- [x] No email is sent.
- [x] No Shopify tag is written, removed, overwritten, or mutated.
- [x] No Trustpilot, Kudosi, or Ali Reviews API is called.
- [x] Simulator fixtures are ignored unless
  `SHOPIFY_REVIEW_REQUEST_USE_SIMULATOR_FIXTURE=YES_I_UNDERSTAND_THIS_IS_FAKE_DATA`
  is explicitly set.
- [x] The simulator is used only to test gate/executor branches before any
  future real-send implementation.

## Phase 5.13 Trustpilot Real Send Final Preflight

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_real_send_final_preflight`.
- [x] Generate local JSON/HTML final preflight reports only:
  `logs/shopify_review_request_trustpilot_real_send_final_preflight.json` and
  `logs/shopify_review_request_trustpilot_real_send_final_preflight.html`.
- [x] Read production reports by default:
  `shopify_review_request_trustpilot_auto_queue_refresh.json`,
  `shopify_review_request_trustpilot_locked_send_readiness_package.json`,
  `shopify_review_request_trustpilot_locked_gmail_send_gate.json`, and
  `shopify_review_request_trustpilot_gmail_send_executor_shell.json`.
- [x] Ignore simulator fixtures unless
  `SHOPIFY_REVIEW_REQUEST_REAL_PREFLIGHT_USE_SIMULATOR=YES_I_UNDERSTAND_THIS_IS_FAKE_DATA`
  is explicitly set.
- [x] Current production state remains blocked because no eligible Trustpilot
  candidate exists: `preflight_status=blocked_no_eligible_candidate`.
- [x] `#22620` remains blocked because the same customer already received
  Trustpilot via `#22621`.
- [x] `#22582` remains blocked because it is not delivered, is missing
  `1: review request`, and related order group `#22582/#22581` is not ready.
- [x] No Gmail API is called.
- [x] No Gmail draft is created, updated, deleted, or sent.
- [x] No email is sent.
- [x] No Shopify API is called.
- [x] No Shopify tag is written, removed, overwritten, or mutated.
- [x] No Trustpilot, Kudosi, or Ali Reviews API is called.
- [x] The next phase can add real-send execute only after final preflight
  reports `ready_for_real_send_execute_next_phase`.

## Phase 5.14 Trustpilot Real Send Execute Skeleton

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_real_send_execute`.
- [x] Generate local JSON/HTML execute skeleton reports only:
  `logs/shopify_review_request_trustpilot_real_send_execute.json` and
  `logs/shopify_review_request_trustpilot_real_send_execute.html`.
- [x] Read production final preflight by default:
  `shopify_review_request_trustpilot_real_send_final_preflight.json`.
- [x] Ignore simulator readiness unless
  `SHOPIFY_REVIEW_REQUEST_REAL_SEND_EXECUTE_USE_SIMULATOR=YES_I_UNDERSTAND_THIS_IS_FAKE_DATA`
  is explicitly set.
- [x] Current production default remains blocked because no eligible Trustpilot
  candidate exists: `execution_status=blocked_no_eligible_candidate`.
- [x] No Gmail API is called.
- [x] No Gmail draft is created, updated, deleted, or sent.
- [x] No email is sent.
- [x] No Shopify API is called.
- [x] No Shopify tag is written, removed, overwritten, or mutated.
- [x] No Trustpilot, Kudosi, or Ali Reviews API is called.
- [x] Future real send requires final preflight ready, exactly one real eligible
  candidate, the explicit ACK, the explicit real-send execute flag
  `SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_REAL_SEND_EXECUTE=YES_I_APPROVE_REAL_TRUSTPILOT_GMAIL_SEND`,
  and a separate real-send implementation phase.

## Phase 5.15 Trustpilot Gmail Real-Send Readiness Audit

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_gmail_real_send_readiness_audit`.
- [x] Generate local JSON/HTML readiness audit reports only:
  `logs/shopify_review_request_trustpilot_gmail_real_send_readiness_audit.json`
  and
  `logs/shopify_review_request_trustpilot_gmail_real_send_readiness_audit.html`.
- [x] Read the latest local production reports where available:
  auto queue refresh, locked send readiness package, locked Gmail send gate,
  Gmail send executor shell, real send final preflight, and real send execute.
- [x] Audit Gmail dependency availability and local config name presence only.
  Do not print secret values, token contents, credential contents, or private
  environment values.
- [x] No Gmail network call is made.
- [x] No Gmail draft is created, updated, deleted, or sent.
- [x] No email is sent.
- [x] No Shopify API is called.
- [x] No Shopify tag is written, removed, overwritten, or mutated.
- [x] No Trustpilot, Kudosi, or Ali Reviews API is called.
- [x] Current production state remains blocked because no eligible Trustpilot
  candidate exists: `readiness_audit_status=blocked_no_eligible_candidate`.
- [x] Future real send implementation must enforce exactly one candidate, final
  preflight ready, explicit ACK, explicit real-send execute flag, single-send
  limit, duplicate suppression, privacy masking, and post-send audit before any
  Shopify tag write.

## Phase 5.16 Trustpilot Gmail OAuth / Config Helper

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_gmail_oauth_config_helper`.
- [x] Generate local JSON/HTML helper reports only:
  `logs/shopify_review_request_trustpilot_gmail_oauth_config_helper.json` and
  `logs/shopify_review_request_trustpilot_gmail_oauth_config_helper.html`.
- [x] Check Gmail dependency/config presence only: dependency importability,
  process environment variable presence, `.env.example` placeholder names, and
  configured path existence booleans.
- [x] Do not read Gmail token or credential file contents.
- [x] Do not print token values, client secret values, private environment
  values, raw customer emails, or full Gmail draft/message IDs.
- [x] Do not call Gmail network/API, create/update/delete Gmail drafts, or send
  email.
- [x] Do not call Shopify APIs, write Shopify tags, call Trustpilot/Kudosi/Ali
  Reviews APIs, or create tracking redirects/tokens.
- [x] Document required placeholders:
  `GMAIL_SEND_FROM_EMAIL`, `GMAIL_OAUTH_CLIENT_SECRET_FILE`,
  `GMAIL_OAUTH_TOKEN_FILE`, `GMAIL_REQUIRED_SCOPE`,
  `SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK`, and
  `SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_REAL_SEND_EXECUTE`.
- [x] Current blocker remains Gmail OAuth config missing and no eligible
  Trustpilot candidate.
- [x] Next phase can add local OAuth setup verification only after config paths
  are provided, still without enabling real send until final preflight and
  readiness audit pass.

## Phase 5.17 Review Requests Admin Usability

- [x] Simplify the Review Requests dashboard for non-technical admins.
- [x] Make the main page focus on ready orders, blocked orders, Gmail setup,
  sent Trustpilot emails, and the next action.
- [x] Move technical task names, report paths, simulator details, safety flags,
  and internal statuses into collapsed Advanced technical details.
- [x] Keep the change UI/readability only with no behavior changes.
- [x] No Gmail API call, Gmail draft create/update/delete, or email send is
  added.
- [x] No Shopify API call, Shopify tag write, Shopify mutation, Trustpilot API
  call, Kudosi API call, or Ali Reviews API call is added.

## Phase 5.18A Trustpilot Gmail Config Compatibility Audit

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_gmail_config_compatibility_audit`.
- [x] Generate local JSON/HTML audit reports only:
  `logs/shopify_review_request_trustpilot_gmail_config_compatibility_audit.json`
  and
  `logs/shopify_review_request_trustpilot_gmail_config_compatibility_audit.html`.
- [x] Detect legacy `GOOGLE_GMAIL_*` config names safely by code reference and
  process environment presence only.
- [x] Do not print secret values, read Gmail token contents, read credential
  file contents, or read `.env`.
- [x] Do not call Gmail network/API, create/update/delete Gmail drafts, or send
  email.
- [x] Do not call Shopify APIs, write Shopify tags, call
  Trustpilot/Kudosi/Ali Reviews APIs, or call `translationsRegister`.
- [x] Explain why Phase 5.16 could show missing even though the earlier Gmail
  flow worked: the older Trustpilot Gmail flow used legacy `GOOGLE_GMAIL_*`
  names while the new helper checked `GMAIL_*` file-path names.
- [x] Add safe legacy fallback detection to the Gmail helper/readiness audit so
  legacy config can be recognized without exposing values.
- [x] Keep real send blocked unless `gmail.send` scope is confirmed and a later
  phase receives explicit human approval.
- [x] Update the Review Requests dashboard to show legacy Gmail config status in
  plain language while keeping technical env names in Advanced details.

## Phase 5.18B Trustpilot Gmail Scope Compatibility Resolver

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_gmail_scope_compatibility_resolver`.
- [x] Generate local JSON/HTML resolver reports only:
  `logs/shopify_review_request_trustpilot_gmail_scope_compatibility_resolver.json`
  and
  `logs/shopify_review_request_trustpilot_gmail_scope_compatibility_resolver.html`.
- [x] Distinguish `gmail.compose` draft-only compatibility from `gmail.send`
  real-send compatibility and the broad `mail.google.com` scope.
- [x] Do not call Gmail network/API, create/update/delete Gmail drafts, or send
  email.
- [x] Do not call Shopify APIs, write Shopify tags, call
  Trustpilot/Kudosi/Ali Reviews APIs, or call `translationsRegister`.
- [x] Keep direct real send blocked unless `gmail.send` or an equivalent
  approved scope is confirmed and a later phase receives explicit human
  approval.
- [x] If only `gmail.compose` exists, future workflow should use draft
  creation/manual send or upgrade OAuth scope before any direct-send phase.
- [x] Update the helper/readiness/dashboard wording so admins can see whether
  Gmail permission is missing, draft-only, or real-send capable without showing
  secret values.

## Phase 5.19A Trustpilot Gmail Draft-Only Preflight

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_gmail_draft_only_preflight`.
- [x] Generate local JSON/HTML draft-only preflight reports only:
  `logs/shopify_review_request_trustpilot_gmail_draft_only_preflight.json`
  and
  `logs/shopify_review_request_trustpilot_gmail_draft_only_preflight.html`.
- [x] Prepare the fastest safe route: if only `gmail.compose` is available,
  a later locked phase can create one Gmail draft for staff review and manual
  sending.
- [x] Do not call Gmail network/API in this phase.
- [x] Do not create, update, delete, or send a Gmail draft in this phase.
- [x] Do not send email.
- [x] Do not call Shopify APIs, write Shopify tags, or mutate Shopify data.
- [x] Do not call Trustpilot, Kudosi, or Ali Reviews APIs.
- [x] Keep the current default blocked until Gmail permission is configured and
  exactly one eligible Trustpilot candidate exists.
- [x] Preserve current known blockers:
  `#22620` already received Trustpilot via `#22621`, and `#22582` is not
  delivered, is missing `1: review request`, and related `#22582/#22581` is
  not ready.
- [x] The next phase can add a one-draft create locked runner only if scope and
  candidate preflight are ready, and that future phase still needs separate
  human approval.

## Phase 5.19B Trustpilot Gmail One-Draft Create Locked Runner

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner`.
- [x] Generate local JSON/HTML locked-runner reports only:
  `logs/shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner.json`
  and
  `logs/shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner.html`.
- [x] Explain missing requirements clearly before draft creation: Gmail
  permission, exactly one safe eligible order, duplicate/risk checks, and final
  local approval.
- [x] Do not call Gmail network/API in this phase.
- [x] Do not create, update, delete, or send a Gmail draft in this phase.
- [x] Do not send email.
- [x] Do not call Shopify APIs, write Shopify tags, or mutate Shopify data.
- [x] Do not call Trustpilot, Kudosi, or Ali Reviews APIs.
- [x] Future draft creation requires compose or send scope, exactly one
  eligible candidate, duplicate/risk checks, and the explicit draft-create
  approval flag
  `SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_DRAFT_CREATE=YES_I_APPROVE_ONE_TRUSTPILOT_GMAIL_DRAFT_CREATE`.
- [x] Update the Review Requests dashboard with "Draft creation readiness" and
  plain-language missing requirements while keeping technical fields in
  Advanced details.

## Phase 5.20 Review Requests Setup Checklist

- [x] Add an admin setup checklist / blocker action panel to the Review
  Requests console.
- [x] Make the main page clearly answer whether a Trustpilot email can be
  prepared now.
- [x] Show Gmail permission, eligible order, safety checks, and final approval
  as checklist items.
- [x] Explain how to make an order eligible: delivered order, exact review
  request tag, no prior Trustpilot email, no open complaint/refund/return risk,
  and safe refresh after Shopify sync.
- [x] Keep this phase UI/readability/reporting only with no behavior changes.
- [x] Do not call Gmail network/API, create/update/delete drafts, or send
  email.
- [x] Do not call Shopify APIs, write Shopify tags, call
  Trustpilot/Kudosi/Ali Reviews APIs, or call `translationsRegister`.
- [x] Do not add Send/Create/Write controls.

## Phase 5.21 Trustpilot Gmail Env Loading Audit

- [x] Add the fixed local approval task
  `shopify_review_request_trustpilot_gmail_env_loading_audit`.
- [x] Generate local JSON/HTML audit reports only:
  `logs/shopify_review_request_trustpilot_gmail_env_loading_audit.json`
  and
  `logs/shopify_review_request_trustpilot_gmail_env_loading_audit.html`.
- [x] Check expected Gmail environment key presence in `os.environ` only;
  report booleans and counts without printing values.
- [x] Read `.env` key names only, never values, and report expected Gmail key
  presence/missing status.
- [x] Diagnose whether the runner process can see the Gmail scope key and
  whether `.env` appears to contain a scope key that is not injected into the
  runner environment.
- [x] Scan selected Docker Compose, Django, runner, and Codex runner files for
  safe loader markers only; do not print full lines or values.
- [x] No Gmail network/API call, no Gmail draft create/update/delete, no Gmail
  send, no Shopify API/write/tag mutation, no Trustpilot/Kudosi/Ali Reviews API
  call, and no `translationsRegister`.
- [x] Next step depends on the audit result:
  - If `.env` has keys but the runner misses them, add safe env loading for
    remote approval tasks or run the runner with required variables injected.
  - If no keys exist, add Gmail scope configuration.
  - If `gmail.compose` exists, move to the one-draft create path once exactly
    one eligible candidate exists.
  - If `gmail.send` exists, continue the real-send path carefully with final
    preflight, exactly one eligible candidate, and explicit approvals.

## Phase 5.22 Trustpilot Gmail Env Loading Fix

- [x] Add safe project-root `.env` loading to the local remote approval runner
  before fixed task execution.
- [x] Load simple `KEY=VALUE` assignments into the runner process environment
  so Review Request Gmail tasks can see existing Gmail scope/config.
- [x] Do not overwrite existing process environment values; skipped keys are
  reported by count only.
- [x] Report loader status by booleans and counts only: loader enabled, `.env`
  file found, keys loaded, existing keys skipped, and Gmail-related keys loaded.
- [x] Never print secret values, token values, client secret values, private
  keys, raw customer emails, or full Gmail draft/message IDs.
- [x] Keep the loader local-only: no Gmail API call, no Gmail draft
  create/update/delete, no email send, no Shopify API/write/tag mutation, no
  Trustpilot/Kudosi/Ali Reviews API call, and no `translationsRegister`.
- [x] Update the env loading audit so the fixed runner path can report
  `gmail_compose_scope_available_in_runner_env`,
  `gmail_send_scope_available_in_runner_env`,
  `gmail_scope_loaded_but_unrecognized`, or
  `env_file_loaded_but_scope_still_missing`.

## Phase 5.24A Review Request Approval Queue

- [x] Add a simple Review Requests approval queue in the Django admin
  workbench.
- [x] Main page shows only `Needs review email` and `Already sent`.
- [x] Eligible rows expose one admin action named `Review & Send`.
- [x] The action is POST-only, admin-only, CSRF protected, and verifies the
  selected order against the current eligible queue before any Gmail call.
- [x] With `gmail.compose`, the system uses Gmail draft creation plus
  `drafts.send` internally after admin approval.
- [x] No direct automatic send is enabled without admin approval yet.
- [x] If no eligible candidate exists, no Gmail call occurs and the admin sees
  `No email was sent. This order is not eligible.`
- [x] Preserve known blockers: `#22620` is already sent to this customer via
  `#22621`, and `#22582` is not ready because it is not delivered, is missing
  `1: review request`, and related `#22582/#22581` are not ready.
- [x] No Shopify tag write happens in this phase; after send, the page reports
  that Shopify tag write waits for post-send audit.
- [x] Later automation path: after the algorithm is trusted, remove the manual
  approval step; after send audit, write `1: trustpilot` in a separate
  approved phase.

## Phase 5.25 Approval Queue Customer Context And Review & Send

- [x] Approval queue rows now show business context for non-technical admins:
  order number, customer display name, masked customer identifier when
  available, customer order count/sequence, current tag chips, delivered
  status, canonical `1: review request` status, previous Trustpilot history,
  eligibility status, and a plain-language reason.
- [x] The `Needs review email` table uses the columns `Order`, `Customer`,
  `Orders`, `Tags`, `Trustpilot history`, `Status`, `Reason`, and `Action`.
- [x] The `Already sent` table uses the columns `Order`, `Customer`, `Orders`,
  `Trustpilot email`, `Evidence`, and `Tags`.
- [x] Previous Trustpilot status is detected from the local history ledger,
  Trustpilot tag aliases such as `1: trustpilot` and `1: trustpoilt`, and
  customer-level duplicate evidence such as `#22620` already sent via `#22621`.
- [x] `Review & Send` is shown only for currently eligible rows. The server
  still revalidates the selected order on POST before any Gmail draft/send
  path can run.
- [x] With the current no-eligible state, no active `Review & Send` button is
  shown, no Gmail API call happens, and no email is sent.
- [x] `#22582` remains not ready because it is not delivered, is missing
  `1: review request`, and related `#22582/#22581` are not ready.
- [x] `#22620` remains already sent / duplicate because the customer already
  received a Trustpilot email via `#22621`; `#22621` remains already sent and
  recorded.
- [x] Shopify tag writes remain disabled in this phase. Any future
  post-send Shopify tag write must be a separate audit and approval step.

## Phase 5.26 Merged Order Group Guard

- [x] Add an explicit merged/related order group guard to the Review Requests
  workbench.
- [x] Related order numbers extracted from local order notes and local report
  references are treated as one shipment group without exposing raw notes.
- [x] Merged groups receive at most one Trustpilot email; the UI must never show
  separate `Review & Send` buttons for multiple orders in the same group.
- [x] A merged group is eligible only when every order in the group is delivered,
  has the canonical `1: review request` tag, has no refund/return/cancel/ticket
  risk, and has no prior Trustpilot send evidence.
- [x] If any order in the group already received Trustpilot, the whole group is
  already sent or blocked as a duplicate with evidence naming the order that
  received Trustpilot.
- [x] `#22582/#22581` should remain blocked until the whole merged group is
  ready; no Trustpilot email should be sent for only one order in that group.
- [x] Phase 5.26 does not call Gmail APIs, send emails, create drafts, call
  Shopify APIs, write Shopify tags, call external review APIs, or call
  `translationsRegister`.

## Phase 5.27 Last 60 Days Reviewable Candidate Queue

- [x] Main `Needs review email` now shows only candidates from the current
  last-60-days scan that are actually eligible for admin review/send.
- [x] Blocked and not-ready orders are moved out of the main queue into the
  collapsed `Blocked / Not ready` section or advanced technical details.
- [x] Added `shopify_review_request_last_60_days_candidate_scan` to scan synced
  local Shopify order rows and existing local review-request reports without
  Shopify, Gmail, or external review API calls.
- [x] The scan reports `scanned_order_count`, `delivered_order_count`,
  `eligible_candidate_count`, `already_sent_count`, `blocked_count`,
  merged-group blocks, duplicate-customer blocks, missing review-request tag
  blocks, not-delivered blocks, and eligible/blocked/already-sent summaries.
- [x] Merged groups such as `#22582/#22581` remain blocked until the whole
  group is delivered, has canonical `1: review request`, has no risk, and has
  no prior Trustpilot send evidence.
- [x] `#22582` must not be presented for admin send review and must not show a
  `Review & Send` button while its merged group is not ready.
- [x] `#22621` remains visible as already sent; `#22620` remains visible as
  already sent / duplicate via `#22621`; neither can show `Review & Send`.
- [x] Phase 5.27 is scan/UI only. The admin POST path is locked and performs no
  Gmail API call, draft create/update/delete, send, Shopify write/tag mutation,
  Trustpilot/Kudosi/Ali Reviews API call, or `translationsRegister`.

## Phase 5.28A Tag Alias And #22562 Candidate Correction

- [x] Read checks treat `1: review request` and legacy typo
  `1: reveiw request` as equivalent review-request trigger tags, including
  spacing/case variants such as `1:review request` and `1 : reveiw request`.
- [x] Future Shopify writes still use canonical `1: review request`; this phase
  performs no Shopify writes.
- [x] Delivered evidence accepts `Delivered` and case-normalized `delivered`.
- [x] Trustpilot sent aliases remain `1: trustpilot` and legacy typo
  `1: trustpoilt`, including spacing variants.
- [x] Repeat-customer orders are not grouped into a merged shipment unless
  explicit merge evidence exists in local notes, staff/report evidence, or a
  verified related-order field.
- [x] `#22562` must not be blocked for missing `1: review request` when the
  loaded tag is `1: reveiw request`.
- [x] `#22562` must not be grouped with other same-customer orders unless an
  explicit merge note/evidence connects them.
- [x] Added
  `shopify_review_request_tag_alias_and_candidate_correction_audit` to report
  `#22562` tag detection, delivered detection, merge evidence source, final
  eligibility, blockers, and eligible count after the fix.
- [x] Phase 5.28A is scan/UI/report only. It performs no Gmail API call, email
  send, Shopify API call/write/mutation/tag write, Trustpilot/Kudosi/Ali Reviews
  API call, or `translationsRegister`.

## Phase 5.28B Shopify Order Sync Coverage

- [x] Review Requests requires full local Shopify order coverage, not
  Shenzhen-only settlement data, before the candidate list can be trusted.
- [x] The initial setup path should sync the last 60 days of Shopify orders into
  local `ShopifyOrder` rows using
  `docker compose exec -T web python manage.py sync_review_request_shopify_orders --days 60 --request-delay 1.0 --apply-local --skip-fulfillment-orders`.
- [x] The daily refresh path should sync the latest 3 days with
  `docker compose exec -T web python manage.py sync_review_request_shopify_orders --days 3 --request-delay 1.0 --apply-local --skip-fulfillment-orders`.
- [x] The candidate scan now reports `scan_source` as `full_shopify_orders`,
  `shenzhen_only_orders`, `fallback_report_only`, or `sqlite_report_fallback`.
- [x] Coverage warnings include `incomplete_local_order_source`,
  `order_not_found_in_local_data`, and `delivered_order_data_missing`.
- [x] `#22530` missing from the scan is treated as a local data coverage
  problem: if it is not in `ShopifyOrder`, the report says to run the Review
  Request 60-day Shopify sync.
- [x] The dashboard shows an `Order data coverage` section with the last sync
  window, local data source, `#22530` presence, candidate scan freshness, and
  coverage warnings.
- [x] `Needs review email` must show only truly eligible candidates; blocked,
  incomplete, or not-ready orders remain secondary.
- [x] Phase 5.28B does not call Gmail APIs, send email, create drafts, write
  Shopify data, call Shopify mutations, run `tagsAdd` / `tagsRemove`, call
  Trustpilot/Kudosi/Ali Reviews APIs, or call `translationsRegister`.

## Phase 5.28D Fulfillment Detail Rate Limit Guard

- [x] Review Request Shopify order sync skips per-order fulfillment-order detail
  reads by default to avoid Shopify 429 rate limits during broad candidate
  coverage syncs.
- [x] The sync command supports `--skip-fulfillment-orders` for explicit safe
  mode and `--include-fulfillment-orders` for a later deeper sync when
  fulfillment details are truly needed.
- [x] Deeper fulfillment detail sync must use `--fulfillment-request-delay 2.0`
  or higher and may be limited with `--fulfillment-max-orders`.
- [x] When fulfillment details are skipped, the sync still reads base order
  fields from the Shopify orders page, including tags, `fulfillment_status`,
  financial status, notes, note attributes, customer, shipping, and line-item
  snapshots available in the order payload.
- [x] Skipping fulfillment details must not overwrite existing local
  fulfillment-derived location fields with `unknown`.
- [x] Candidate scanning should use delivered/review-request tag evidence,
  `fulfillment_status`, and local report evidence first. Missing fulfillment
  detail evidence is treated as uncertain local coverage, not as a fatal sync
  error.
- [x] Phase 5.28D performs no Shopify writes, tag mutations, Gmail API calls,
  email sends, Trustpilot/Kudosi/Ali Reviews API calls, or
  `translationsRegister` calls.

## Phase 5.28F Shopify Order Tags Persistence

- [x] Local Review Request sync persists Shopify REST order `tags` into
  nullable `ShopifyOrder.shopify_tags`; `NULL` means the row has not been
  populated by the tag-aware sync yet, while an empty string means Shopify
  returned no order tags.
- [x] Candidate scanning reads persisted local tags first, then falls back to
  existing local report evidence only when the local tag field is unavailable.
- [x] Review-request detection accepts `1: review request`, legacy typo
  `1: reveiw request`, and spacing/case variants; Trustpilot sent detection
  accepts `1: trustpilot`, legacy typo `1: trustpoilt`, and spacing/case
  variants; Delivered detection accepts `Delivered` and `delivered`.
- [x] `#22530` diagnosis now reports the selected local tag field, safe tags
  summary, tag data availability, matched review-request tag value, and exact
  local reason when tags are unavailable or empty.
- [x] Added `shopify_review_request_order_tags_persistence_audit` to report the
  selected tag field, migration presence, #22530/#22562 safe tag summaries,
  alias detection, candidate count after tag availability, and no-write safety
  flags.
- [x] Phase 5.28F performs no Shopify writes, tag mutations, Gmail API calls,
  email sends, Trustpilot/Kudosi/Ali Reviews API calls, or
  `translationsRegister` calls.

## Phase 5.28H Customer History Trustpilot Guard

- [x] Trustpilot review email flow is repeat-customer only: local customer
  history count must be confirmed and greater than one before Review & Send can
  appear.
- [x] First-order customers are blocked with a plain first-order reason and
  moved to Blocked / Not ready.
- [x] Customer history is resolved from local `ShopifyOrder` history by
  customer email first, with customer name plus shipping fields only as a safe
  fallback; raw customer email is not written to reports or HTML.
- [x] Prior Trustpilot detection checks same-customer historical order tags
  across all local `ShopifyOrder` rows, not only the current 60-day scan.
- [x] Trustpilot sent aliases include `1: trustpilot`, `1: trustpoilt`,
  `trustpilot`, `trustpoilt`, and spacing/case variants.
- [x] `#21076` is blocked when same-customer history contains a prior
  Trustpilot alias tag on `#21778`.
- [x] The Review Requests page shows Customer orders and Trustpilot history in
  the main and blocked queues, without raw customer email.
- [x] Added `shopify_review_request_customer_history_trustpilot_guard_audit` to
  report first-order blocks, prior Trustpilot customer blocks, unknown history,
  focus order diagnoses, active Review & Send count, and no-write safety flags.
- [x] Phase 5.28H performs no Shopify writes, tag mutations, Gmail API calls,
  email sends, Trustpilot/Kudosi/Ali Reviews API calls, or
  `translationsRegister` calls.

## Phase 5.28I Customer History Precision And Note Risk Guard

- [x] Customer history now counts only high/medium confidence identity matches:
  Shopify customer ID if available, exact email, exact normalized name plus
  shipping phone, or exact normalized name plus shipping address/postcode.
- [x] Name-only matches are reported as low confidence, excluded from confirmed
  customer order counts, and blocked from Review & Send until manually reviewed.
- [x] Candidate reports expose exact matched order names, match method,
  confidence, weak-match count, exact-match count, and excluded weak matches.
- [x] Local note fields are scanned for aftersales/ticket/refund/return risk
  keywords, but reports and UI show only the safe field name, keyword, and plain
  reason `Aftersales/ticket note found`.
- [x] Added `shopify_review_request_customer_history_precision_audit` to report
  `#21083` diagnosis, history overcount metrics, note-risk blocks,
  low-confidence history blocks, and active Review & Send before/after counts.
- [x] Phase 5.28I performs no Shopify writes, tag mutations, Gmail API calls,
  email sends, Trustpilot/Kudosi/Ali Reviews API calls, or
  `translationsRegister` calls.

## Phase 5.28J Review Send Failure Audit And Queue Pagination

- [x] Added `shopify_review_request_review_send_failure_audit` to diagnose the
  latest `#21075` Review & Send attempt with candidate, customer-history,
  Trustpilot duplicate, note-risk, Gmail scope, Gmail helper, and exact
  user-message fields.
- [x] Improved Review & Send blocked messages so Gmail draft-only scope reports
  that direct sending requires `gmail.send` instead of showing only a vague
  sending-permission message.
- [x] Needs review email queue is paginated with default page size 25 and
  allowed page sizes 25, 50, and 100 via `?page=` and `?page_size=`.
- [x] Review & Send buttons render only for rows visible on the current page;
  blocked rows remain secondary and limited in the collapsed section.
- [x] No Shopify tag write, Shopify mutation, external review API call,
  Gmail API call, email send, or `translationsRegister` call is performed by
  this phase. Direct send depends on Gmail permission and helper compatibility.

## Phase 5.28K Review Send Gmail Helper Reuse Audit

- [x] Added `shopify_review_request_review_send_reuse_gmail_helper_audit` to
  inspect the proven `#22621` Gmail `drafts.send` path without Gmail, Shopify,
  Trustpilot/Kudosi/Ali Reviews, or `translationsRegister` calls.
- [x] The previous `#22621` `drafts.send` helper was found, but it is
  hard-coded to a fixed order/draft identity and local runner ACK flow, so the
  current admin `Review & Send` POST cannot safely reuse it for dynamic rows
  such as `#21075` yet.
- [x] `Review & Send` no longer reports the misleading blocker that
  `gmail.send` is required when the real missing step is a reviewed dynamic
  `drafts.create` plus `drafts.send` integration.
- [x] Admin `Review & Send` still requires staff POST, CSRF, current eligible
  queue membership, server-side revalidation, repeat-customer confirmation,
  duplicate suppression, risk checks, delivered/review-request tags, merged
  group readiness, and one-send limit enforcement before any future send.
- [x] Shopify tag write remains a separate post-send audit/tag-write phase.
  No automatic sending is enabled by this phase.

## Phase 5.28L Dynamic Review Send And Latest-Customer Queue

- [x] Needs review email queue now keeps only the latest eligible order per
  precise customer identity. Latest means highest numeric order number first,
  then newest local order date when an order number is unavailable.
- [x] Older eligible rows for the same confirmed customer are blocked with the
  plain reason `A newer eligible order exists for this customer: #...`.
- [x] Customer grouping uses protected high/medium confidence identity keys
  derived from Shopify customer ID/email or the Phase 5.28H medium-confidence
  shipping fallbacks; weak name-only matches are not grouped for sending.
- [x] Admin `Review & Send` now has a dynamic Gmail `drafts.create` plus
  `drafts.send` helper for one server-revalidated latest eligible order.
- [x] The dynamic send path keeps Shopify tag writes disabled and never calls
  Gmail during audits or blocked route checks.
- [x] Added `shopify_review_request_dynamic_review_send_audit` to report
  latest-filter counts, hidden older eligible count, the `#22530`/`#22562`
  latest decision, helper readiness, `#21075` readiness, visible send count,
  latest-only queue status, and no-write safety flags.

## Phase 5.28M Post-Send Audit And Local Sent Ledger

- [x] Added `shopify_review_request_review_send_post_send_audit` to read the
  latest local Review & Send JSON/HTML report and confirm `email_sent=true`
  with `sent_count=1`.
- [x] The post-send audit writes local runner reports under `logs/codex_runs/`
  and performs no Gmail API call, Shopify API call, Shopify write, external
  review API call, or `translationsRegister` call.
- [x] A locally confirmed Review & Send success is now Trustpilot sent evidence
  before Shopify tag write. The order/customer moves out of Needs review email
  and appears in Already sent with `Sent` and `Tag pending` status.
- [x] Customer lifetime order count and Trustpilot history are resolved from all
  matching local ShopifyOrder rows by high/medium confidence identity. Weak
  name-only matching remains blocked/manual-review only.
- [x] Customer-level Trustpilot history includes local Review & Send reports in
  addition to Shopify tag aliases such as `1: trustpilot`, `1: trustpoilt`,
  `trustpilot`, `trustpoilt`, and spacing/case variants.
- [x] Shopify tag write remains a later phase after post-send audit.

## Phase 5.29 Automatic Review & Send Tag Completion

- [x] After a successful admin `Review & Send`, the server builds a post-send
  audit immediately and runs the shared Shopify tag-write helper for the same
  selected order only.
- [x] Success status becomes `completed_email_sent_tag_written`; the Already
  sent table shows `Sent`, `Tag written`, and evidence that the Trustpilot
  email was sent and Shopify tag updated.
- [x] If the tag write fails after Gmail succeeds, the workflow remains
  `email_sent_tag_pending`; the order stays out of Needs review and can be
  repaired by the manual one-order tag-write runner without resending Gmail.
- [x] If Gmail send fails or server-side revalidation blocks before send,
  Shopify tag write is not attempted.
- [x] Phase 5.29D manual repair is locked to `#21284` and requires both
  `SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE_ORDER="#21284"` and
  `SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_WRITE=YES_I_APPROVE_TRUSTPILOT_TAG_WRITE_FOR_SENT_ORDER`.
- [x] The repair path is for Sent / Tag pending evidence only; it does not batch
  repair orders, resend Gmail, call external review APIs, or write Shopify for
  any unrelated order.
- [x] Phase 5.29E excludes any order/customer with Trustpilot sent tag aliases
  such as `1: trustpilot`, `1: trustpoilt`, `trustpilot`, `trustpoilt`, and
  spacing/case variants before Needs review or Review & Send can appear.
- [x] `#21225` is audited as an Already sent row when local Shopify tags include
  `1: trustpilot`; it must show `Tag written`, not `Tag pending`, and evidence
  `Trustpilot tag found on Shopify order.`
- [x] Added `shopify_review_request_trustpilot_tag_exclusion_audit` under
  `logs/codex_runs/` to report `#21225` local tags, Trustpilot tag detection,
  Needs review removal, Already sent display, exclusion count, and no-write /
  no-API safety flags.
