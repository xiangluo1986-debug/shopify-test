# Blue-Green Deploy Manual Decisions

This package records conservative defaults for future local-only blue-green
planning. It does not approve a runtime change, restart containers, change
`docker-compose.yml`, switch traffic, run migrations, or change Cloudflare or
proxy routing.

## Current Review Status

- Local-only planning status: approved for a future local-only apply dry-run
  design/review task.
- Local runtime apply status: NO-GO until a separate task explicitly approves
  the exact local runtime commands.
- Production apply status: NO-GO.
- Runtime behavior changed by this document: no.
- Current deployment commands remain unchanged.

## Decision Summary

| Area | Chosen conservative default | Local-only planning status | Production status |
| --- | --- | --- | --- |
| Proxy technology | nginx, example-only until apply phase. | Approved | Not approved |
| Port ownership | Keep current `web` service owning host port `8000`. | Approved | Not approved |
| Cloudflare / external routing | No Cloudflare, domain, or external routing change in local-only phase. | Approved | Not approved |
| Active color tracking | Future file-based active color marker documented as draft/example only. | Approved | Not approved |
| Migration compatibility | Backward-compatible migrations only; risky schema work requires separate planning. | Approved | Not approved |
| Static/media handling | Shared media unchanged; keep current `safe_deploy` static behavior until apply design is finalized. | Approved | Not approved |
| Scheduler handling | Scheduler remains singleton; no blue/green scheduler replicas. | Approved | Not approved |
| Rollback authority and observation window | Manual admin approval; keep old color running; minimum 10-minute local/test observation. | Approved | Not approved |
| First apply scope | Local-only apply dry-run first. Production remains blocked. | Approved | Not approved |

## Manual Decisions

### 1. Proxy Technology

Chosen conservative default:

- Use nginx as the default future proxy technology.
- Keep nginx in separate example or draft files until an approved apply task.
- Do not modify active production proxy configuration in this decision phase.

Status:

- Approved for local-only planning.

Production status:

- Not approved.

Reason:

- The project already has `nginx/bluegreen.example.conf`, nginx is simple to
  inspect, and an example-only proxy keeps current runtime behavior unchanged.

What must be checked before production:

- Confirm whether production already has a host-level proxy or Cloudflare
  tunnel target outside this repository.
- Confirm the reviewed nginx config, reload method, and rollback method.
- Confirm the maintenance window for the first proxy introduction if host port
  ownership or external routing changes.

Local planning approval record:

- Approved proxy technology: nginx, example-only.
- Approved proxy location: non-active draft/example config only.
- Approver: conservative local-only planning default.
- Date: 2026-05-18.

### 2. Port Ownership

Chosen conservative default:

- Keep the current `web` service owning host port `8000` for now.
- A future proxy must not take host port `8000` until a separate apply task
  explicitly approves that change.
- Do not change active `docker-compose.yml` during decision review.

Status:

- Approved for local-only planning.

Production status:

- Not approved.

Reason:

- Existing local and external routing may depend on `127.0.0.1:8000` reaching
  Django directly. Keeping port ownership unchanged avoids accidental traffic
  path changes.

What must be checked before production:

- Confirm the current owner and real external target for host port `8000`.
- Decide whether production keeps port `8000` stable by moving it to the proxy
  or changes Cloudflare/local routing to a different proxy port.
- Approve the exact transition command sequence in a separate apply task.

Local planning approval record:

- Approved future owner of host port `8000`: current `web` service until
  separate approval.
- Planned transition method: not approved; future task required.
- Approver: conservative local-only planning default.
- Date: 2026-05-18.

### 3. Cloudflare / External Routing

Chosen conservative default:

- Make no Cloudflare, domain, tunnel, or external routing change in the
  local-only phase.
- Treat all production routing changes as separate approval items.

Status:

- Approved for local-only planning.

Production status:

- Not approved.

Reason:

- Local-only planning can validate draft files without touching public traffic.
  External routing changes carry production risk and may involve secret-bearing
  local configuration that must not be exposed in docs or logs.

What must be checked before production:

- Confirm the current external route target without printing or copying tokens.
- Confirm whether a maintenance window is needed for the first proxy
  introduction.
- Confirm public `/healthz/` and rollback checks through the stable domain
  after any approved routing change.

Local planning approval record:

- Confirmed route to production app: not checked in this local-only decision
  task.
- Planned route after proxy introduction: not approved; future task required.
- Maintenance window required: to be decided before production.
- Approver: conservative local-only planning default.
- Date: 2026-05-18.

### 4. Active Color Tracking

Chosen conservative default:

- Use a file-based active color marker for a future local dry-run design.
- Document the marker as a draft/example only, such as a future
  `docs/runtime/active_color.example` path.
- Do not create an active runtime state file in this task.
- Keep manual confirmation in the checklist before and after every switch.

Status:

- Approved for local-only planning.

Production status:

- Not approved.

Reason:

- A small file-based marker is easy for operators to inspect and compare with
  the proxy config. Keeping it example-only avoids creating false runtime state.

What must be checked before production:

- Confirm where the real active-color state will live outside example docs.
- Confirm how the state marker and proxy upstream change are updated together.
- Confirm post-switch verification catches any mismatch between state and
  routing.

Local planning approval record:

- Approved active color source of truth: future file-based marker, example-only
  during local planning.
- Approved proxy switch mechanism: not approved; future task required.
- Approver: conservative local-only planning default.
- Date: 2026-05-18.

### 5. Migration Compatibility

Chosen conservative default:

- Migrations must be backward-compatible while old and new web colors may both
  exist.
- Do not include destructive schema changes in the same blue-green switch.
- Risky schema changes require separate migration planning and approval.
- Prefer expand/deploy/contract sequencing.

Status:

- Approved for local-only planning.

Production status:

- Not approved.

Reason:

- Blue-green traffic switching does not make incompatible database changes safe.
  The old color may need to run during observation or rollback.

What must be checked before production:

- Review every migration for old-code/new-code compatibility.
- Confirm backup and restore process before risky migrations.
- Separate destructive or contract migrations from the traffic switch.

Local planning approval record:

- Approved migration policy: backward-compatible only during a blue-green
  switch; risky migrations require separate planning.
- Backup process confirmed: not confirmed in this local-only decision task.
- Approver: conservative local-only planning default.
- Date: 2026-05-18.

### 6. Static And Media Handling

Chosen conservative default:

- Keep the current shared media volume behavior unchanged.
- Keep `collectstatic` behavior aligned with the current safe-deploy process
  until the apply design is finalized.
- Do not change static serving in the decision phase.

Status:

- Approved for local-only planning.

Production status:

- Not approved.

Reason:

- Media and static handling can affect user-visible files. Preserving current
  behavior avoids mixing blue-green routing work with storage or asset-serving
  changes.

What must be checked before production:

- Confirm uploads remain consistent when two web colors exist.
- Confirm whether `collectstatic` runs once, in both colors, or as a separate
  static build step.
- Confirm static and media paths through direct color checks and public routing
  before any production switch.

Local planning approval record:

- Approved media strategy: keep current shared media volume unchanged.
- Approved static strategy: keep current safe-deploy behavior until apply
  design is finalized.
- Approver: conservative local-only planning default.
- Date: 2026-05-18.

### 7. Scheduler Handling

Chosen conservative default:

- Scheduler remains singleton.
- Do not create `scheduler_blue` or `scheduler_green` replicas.
- Only one scheduler should run during any blue-green web validation.

Status:

- Approved for local-only planning.

Production status:

- Not approved.

Reason:

- Duplicate schedulers could duplicate scheduled jobs, API reads, local report
  generation, or future write-capable workflows.

What must be checked before production:

- Confirm exactly one scheduler service is running.
- Confirm scheduler code changes are compatible with any migration sequence.
- Confirm rollback does not accidentally start a second scheduler.

Local planning approval record:

- Approved scheduler strategy: singleton scheduler only.
- Singleton enforcement method: keep current single scheduler service; no
  blue/green scheduler replicas.
- Approver: conservative local-only planning default.
- Date: 2026-05-18.

### 8. Rollback Authority And Observation Window

Chosen conservative default:

- Manual admin approval is required before rollback or final cutover decisions.
- Keep the old color running during the observation window.
- Minimum observation window: 10 minutes for local/test.
- Production observation window remains to be decided later.
- Do not attempt automatic database rollback.

Status:

- Approved for local-only planning.

Production status:

- Not approved.

Reason:

- Keeping the old color available makes rollback simpler while the new color is
  observed. Manual authority avoids hidden automatic behavior during early
  rollout phases.

What must be checked before production:

- Name the rollback operator and backup approver for the production window.
- Define production observation length and required health/admin smoke checks.
- Confirm proxy rollback can be performed and verified without database
  rollback.

Local planning approval record:

- Rollback operator: manual admin, to be named in the apply task.
- Observation window: minimum 10 minutes for local/test; production to be
  decided later.
- Required checks: direct color `/healthz/`, public `/healthz/` when routing is
  involved, web/proxy logs, and key admin smoke checks.
- Approver: conservative local-only planning default.
- Date: 2026-05-18.

### 9. First Apply Scope

Chosen conservative default:

- First apply scope is local-only apply dry-run planning.
- Production remains NO-GO.
- Any active runtime compose/proxy change requires a separate approval task.

Status:

- Approved for local-only planning.

Production status:

- Not approved.

Reason:

- Local-only planning lets the draft flow be reviewed before runtime, routing,
  or production commands are introduced.

What must be checked before production:

- Complete and review the local-only apply dry-run result.
- Confirm no production routing, port ownership, migration, scheduler, or static
  behavior change is bundled without separate approval.
- Approve a separate production apply task after local or staging validation.

Local planning approval record:

- First apply target: local-only apply dry-run planning.
- Production approval task required: yes.
- Approver: conservative local-only planning default.
- Date: 2026-05-18.

## Go / No-Go Checklist

- [x] Ready for local-only apply dry-run planning: conservative defaults above
  are filled for local planning.
- [ ] Ready to execute local runtime changes: NO-GO until a separate apply task
  approves exact commands.
- [x] Not ready for production: production apply requires a separate approved
  task after local or staging validation.
- [x] Port ownership protected: host port `8000` remains owned by current `web`
  service until a separate approval changes it.
- [x] Runtime configs protected: active Compose and proxy configuration remain
  unchanged by this decision package.
- [x] Known risk: first proxy introduction may require port ownership or
  Cloudflare routing changes.
- [ ] Rollback execution ready: rollback operator, final observation window,
  and command sequence must be assigned, tested, and recorded before any active
  switch.

## Conservative Defaults

- Keep active `docker-compose.yml` untouched until an apply phase is explicitly
  approved.
- Keep current host port `8000` owned by the current `web` service until proxy
  switch approval.
- Use nginx only in separate draft or example files first.
- Make no Cloudflare, domain, or external routing change in the local-only
  phase.
- Use a future file-based active color marker only as a documented draft until
  an apply task creates real runtime state.
- Keep scheduler as a singleton.
- Require health checks on the inactive color before switching traffic.
- Require public `/healthz/` after any approved public routing switch.
- Keep previous color running during the observation window.
- Keep migrations backward-compatible and reviewed separately.
- Keep shared media unchanged and preserve current safe-deploy static behavior
  until apply design is finalized.
- Do not change Shopify, tickets, review request, translation, Gmail,
  Trustpilot, Kudosi, Ali Reviews, or settlement workflows.

## Required Before Any Apply Task

- `docs/BLUE_GREEN_DEPLOY_APPLY_CHECKLIST.md` is reviewed against these
  local-only defaults.
- A separate apply task explicitly approves any restart, proxy reload, routing
  change, migration, traffic switch, active runtime Compose change, or port
  ownership change.
- The apply task confirms no Shopify, Gmail, Trustpilot, Kudosi, Ali Reviews,
  or translation write operations are involved.
- Production remains blocked until a separate production task approves the
  route, port ownership, rollback operator, observation window, migration
  policy, scheduler handling, static/media behavior, and final command sequence.
