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

### Gmail API Send Permission

- [ ] Confirm Gmail OAuth is configured for `info@kidstoylover.com`.
- [ ] Confirm Gmail API send permission is granted and limited to the required
  sender account.
- [ ] Confirm sender name, reply-to behavior, and unsubscribe/compliance text.
- [ ] Confirm test mode can render email previews without sending.
- [ ] Confirm future send logic requires a separate manual approval gate.

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
