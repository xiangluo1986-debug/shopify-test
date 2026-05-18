# Blue-Green Deploy Manual Decisions

This package is for manual review before any active blue-green apply task. It
does not approve a runtime change, restart containers, change
`docker-compose.yml`, switch traffic, run migrations, or change Cloudflare or
proxy routing.

## Current Review Status

- Local apply status: NO-GO until every decision below is marked with an
  approved choice.
- Production apply status: NO-GO.
- Runtime behavior changed by this document: no.
- Current deployment commands remain unchanged.

## Decision Summary

| Area | Recommended default | Current decision status |
| --- | --- | --- |
| Proxy technology | Use nginx in separate draft/example files first. | Pending |
| Port ownership | Keep current `web` ownership of host port `8000` until a proxy switch is explicitly approved. | Pending |
| Cloudflare / external routing | Confirm the real route to host port `8000` before any switch. | Pending |
| Active color tracking | Use a small file-based active color record plus proxy config review. | Pending |
| Migration compatibility | Require backward-compatible migrations and avoid destructive schema changes in the same deploy. | Pending |
| Static/media handling | Keep shared media and current static behavior until two-container handling is tested. | Pending |
| Scheduler handling | Keep scheduler singleton. Do not run duplicate scheduler containers. | Pending |
| Rollback authority and observation window | Assign one rollback operator and keep the old color running during observation. | Pending |
| First apply scope | Local only first, then staging if available, then production only after approval. | Pending |

## Manual Decisions

### 1. Proxy Technology

Decision needed:

- Choose the future stable proxy technology for routing traffic to the active
  color.
- Confirm whether the proxy will run as a Docker Compose service, host-level
  service, or an existing external layer.

Options:

- nginx: recommended because the project already has
  `nginx/bluegreen.example.conf`, it is simple, common, and easy to review.
- Caddy: possible if automatic HTTPS or a simpler config is preferred.
- Traefik: possible if service labels and dynamic routing become useful later.
- HAProxy: possible if detailed traffic switching and health behavior are
  preferred.
- Existing host proxy: possible if production already has one outside this
  repository.

Recommended default:

- Use nginx only in separate example or override files until the apply phase.
- Do not modify active production proxy configuration in the decision phase.

Manual approval field:

- Approved proxy technology:
- Approved proxy location:
- Approver:
- Date:

### 2. Port Ownership

Decision needed:

- Decide whether the future proxy owns host port `8000`, or whether external
  routing moves to a different local proxy port.

Current state:

- The active `web` service owns host port `8000`.
- Existing local and external routing may expect `127.0.0.1:8000` to reach
  Django directly.

Impact:

- If the proxy takes `8000`, the one-time proxy introduction may require a
  planned traffic path change.
- If the proxy uses a new port, Cloudflare or another external routing layer
  must be changed to target that port.

Recommended default:

- Keep current host port `8000` behavior unchanged until proxy ownership is
  explicitly approved.
- Do not change active `docker-compose.yml` during decision review.

Manual approval field:

- Approved future owner of host port `8000`:
- Planned transition method:
- Approver:
- Date:

### 3. Cloudflare / External Routing

Decision needed:

- Confirm whether `tickets.kidstoyloverapps.com` reaches host port `8000`
  directly or through another local or remote layer.
- Confirm the exact target that would need to change during the proxy
  introduction.

Must be confirmed before switch:

- Current Cloudflare tunnel or external route target, without exposing tokens.
- Whether a maintenance window is needed for the first proxy introduction.
- Whether public `/healthz/` will be checked through the stable domain after
  routing changes.

Recommended default:

- Treat Cloudflare and external routing as production-risk items.
- Make no external routing change until the route is confirmed and approved in
  a separate apply task.

Manual approval field:

- Confirmed route to production app:
- Planned route after proxy introduction:
- Maintenance window required:
- Approver:
- Date:

### 4. Active Color Tracking

Decision needed:

- Decide how operators know which color currently receives traffic.

Options:

- File-based active color record: recommended as the primary source of truth
  because it is easy to inspect and can be included in an apply checklist.
- Environment variable: possible, but can drift from proxy configuration if not
  updated carefully.
- nginx include or symlink: useful for actual routing, but should be paired
  with reviewable documentation.
- Manual config edit only: lowest tooling overhead, highest operator-error
  risk.

Recommended default:

- Use a small file-based active color record for operator tracking, and make
  the proxy include/symlink match that record during a future apply task.
- Keep manual confirmation in the checklist before and after every switch.

Manual approval field:

- Approved active color source of truth:
- Approved proxy switch mechanism:
- Approver:
- Date:

### 5. Migration Compatibility

Decision needed:

- Define migration policy for blue-green deploys.

Required policy points:

- Migrations must be backward-compatible while old and new web colors may both
  exist.
- Avoid destructive schema changes in the same deploy as application code.
- Prefer expand/deploy/contract sequencing.
- Confirm database backup and restore process before risky migrations.

Recommended default:

- No destructive migration in the same task as a traffic switch.
- Any migration task must be reviewed separately and approved before deploy.
- Keep old code able to run against the migrated schema during the observation
  window.

Manual approval field:

- Approved migration policy:
- Backup process confirmed:
- Approver:
- Date:

### 6. Static And Media Handling

Decision needed:

- Confirm how static and media files behave when two web colors exist.

Items to confirm:

- Shared media volume behavior for uploads.
- Whether `collectstatic` is run in one container, both containers, or a
  separate static build step.
- Whether static files are served by Django, the web container, the proxy, or
  another service.
- Whether a static change can be rolled back independently of code.

Recommended default:

- Keep the current shared media behavior.
- Do not change static serving in the decision phase.
- Require local or staging validation of static and media paths before
  production apply.

Manual approval field:

- Approved media strategy:
- Approved static strategy:
- Approver:
- Date:

### 7. Scheduler Handling

Decision needed:

- Decide how scheduled jobs are handled during blue-green deploys.

Risk:

- Running scheduler in both colors can duplicate scheduled jobs, API reads, or
  local report generation.

Recommended default:

- Keep exactly one scheduler instance.
- Do not create `scheduler_blue` and `scheduler_green` unless a future design
  adds explicit singleton locking.
- Switch web traffic independently from scheduler changes where possible.

Manual approval field:

- Approved scheduler strategy:
- Singleton enforcement method:
- Approver:
- Date:

### 8. Rollback Authority And Observation Window

Decision needed:

- Assign who can rollback.
- Define how long to observe after a switch.
- Define which logs and health checks must be inspected.

Recommended default:

- Assign one rollback operator before the switch.
- Keep the previous color running for at least 15 minutes after a local or
  staging switch, and longer for production if traffic or risk warrants it.
- Inspect direct color `/healthz/`, public `/healthz/`, web logs, proxy logs,
  and key admin smoke checks.
- Do not attempt automatic database rollback.

Manual approval field:

- Rollback operator:
- Observation window:
- Required checks:
- Approver:
- Date:

### 9. First Apply Scope

Decision needed:

- Decide where the first active blue-green apply is allowed.

Recommended default:

- Apply locally first only.
- Use staging next if available.
- Production remains blocked until local or staging results are reviewed and a
  separate production apply task is approved.

Manual approval field:

- First apply target:
- Production approval task required:
- Approver:
- Date:

## Go / No-Go Checklist

- [ ] Ready to apply locally: all manual decisions above are marked, and the
  local apply scope is approved.
- [x] Not ready for production: production apply requires a separate approved
  task after local or staging validation.
- [x] Missing manual decisions: every decision in this package is currently
  pending.
- [x] Known risk: first proxy introduction may require port ownership or
  Cloudflare routing changes.
- [ ] Rollback available: rollback plan must be assigned, tested, and recorded
  before any active switch.

## Conservative Defaults

- Keep active `docker-compose.yml` untouched until an apply phase is explicitly
  approved.
- Keep current host port `8000` owned by the current `web` service until proxy
  switch approval.
- Use nginx only in separate draft or override files first.
- Keep scheduler as a singleton.
- Require health checks on the inactive color before switching traffic.
- Require public `/healthz/` after switching traffic.
- Keep previous color running during the observation window.
- Keep migrations backward-compatible and reviewed separately.
- Do not change static/media behavior until local or staging validation passes.

## Required Before Any Apply Task

- Every manual approval field above is filled in.
- `docs/BLUE_GREEN_DEPLOY_APPLY_CHECKLIST.md` is reviewed against the approved
  decisions.
- A separate apply task explicitly approves any restart, proxy reload, routing
  change, migration, or traffic switch.
- The apply task confirms no Shopify, Gmail, Trustpilot, Kudosi, Ali Reviews,
  or translation write operations are involved.
