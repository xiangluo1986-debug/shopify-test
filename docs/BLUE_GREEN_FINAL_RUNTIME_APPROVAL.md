# Blue-Green Final Runtime Approval

## Purpose

Define the final approval requirements before any future task may enable real
blue-green runtime commands.

This document does not approve production apply. It does not deploy, start or
stop containers, restart containers, build images, run migrations, run
collectstatic, reload proxy, switch traffic, write active-color state, change
Cloudflare or domain routing, modify active Compose files, modify production
proxy configuration, call Shopify APIs, call Gmail APIs, send email, or affect
ticket, review request, translation, settlement, Trustpilot, Kudosi, or Ali
Reviews workflows.

Production remains NO-GO.

## Current Passed Prerequisites

- Local inactive runtime validation: PASSED.
- Local/test proxy routing validation: PASSED.
- Deployment lock: implemented.
- safe_deploy lock enforcement: active.
- Runtime helper: plan-only.
- Production apply skeleton: blocked.
- Production switch/rollback review: complete.

## Final Approval Gates Before Enabling Execution

### A. Deployment Lock Gate

- Acquire the deployment lock before any runtime-changing action.
- An existing lock blocks immediately; there is no automatic queue.
- Release only the matching `lock_id` owned by the same deploy flow.
- Stale lock handling is manual review only.

### B. Production Proxy Gate

- The exact production proxy config path must be known.
- The exact proxy switch/reload command must be reviewed.
- The proxy config validation command must be reviewed.
- No Cloudflare or domain change is allowed unless separately approved.

### C. Active-Color State Gate

- The `.deploy/active-color.json` design must be approved.
- The atomic write helper must be reviewed.
- State updates may happen only after target or rollback health passes.
- The state file must contain no secrets and must not be committed.

### D. Rollback Gate

- The rollback command must be reviewed.
- `previous_color` must be known before apply.
- Rollback also uses the deployment lock.
- No database rollback is allowed unless separately approved.

### E. Migration / Data Safety Gate

- Migration compatibility must be confirmed for the specific deploy.
- Destructive migrations are blocked.
- Scheduler singleton behavior must be confirmed.
- Media, static, and uploads shared storage must be confirmed.

### F. Observation / Cleanup Gate

- The old color stays running during the observation window.
- The observation window must be approved.
- Cleanup may run only after the observation window.
- Database, media, static, and upload volumes must not be removed.
- The scheduler must not be stopped unexpectedly.

### G. Exact Command Gate

- The final production command must be reviewed in full.
- The approval phrase must be supplied.
- The operator must confirm current web health before apply.
- The operator must confirm the rollback command before apply.

## Future Approval Phrase

Future final phrase:

```text
I_APPROVE_ENABLE_BLUE_GREEN_RUNTIME_COMMANDS_AFTER_FINAL_REVIEW
```

This phrase is documented for a future implementation task only. It must not be
accepted by scripts yet.

A future implementation task must still keep production apply separate from
runtime command enablement.

## Go / No-Go

- Final approval design: READY after review.
- Runtime command execution: NOT ENABLED.
- Production apply: NO-GO.
