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
- [x] Treat `1: reveiw request` and `1: review request` as separate tags.
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
- Future automation must use exact string matching and the exact Shopify API
  tag value `1: reveiw request` unless a later read-only discovery report proves
  the merchant changed the tag.

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
