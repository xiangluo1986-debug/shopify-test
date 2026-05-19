# Blue-Green Pre-Cutover Live Checklist

## Purpose

This records the final live checklist and the completed manual Cloudflare
route cutover.

This document does not approve cutover by itself.

This document does not perform any runtime action.

Cloudflare cutover PASSED on 2026-05-19 after operator confirmation.

## Operator Approval Phrase

```text
I_APPROVE_MANUAL_CLOUDFLARE_CUTOVER_TO_18000_AFTER_LIVE_CHECKS
```

- This phrase is documentation-only.
- No script should accept it yet.
- Operator must confirm manually before editing Cloudflare.

## Required Live Checks Before Editing Cloudflare

NOT RUN IN THIS TASK.

Check deployment lock status:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action status
```

Check current `8000 /healthz/`:

```powershell
powershell -NoProfile -Command 'try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/healthz/ | Select-Object StatusCode,Content } catch { $_.Exception.Message }'
```

Check `18000` is not serving before candidate start:

```powershell
powershell -NoProfile -Command 'try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18000/healthz/ | Select-Object StatusCode,Content } catch { $_.Exception.Message }'
```

Start candidate compose:

```powershell
docker compose -f .\docker-compose.bluegreen.proxy-candidate.example.yml up -d --no-build
```

Wait 15 seconds:

```powershell
powershell -NoProfile -Command 'Start-Sleep -Seconds 15'
```

Confirm `18000 /healthz/` is HTTP 200:

```powershell
powershell -NoProfile -Command 'try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18000/healthz/ | Select-Object StatusCode,Content } catch { $_.Exception.Message }'
```

Confirm `8000 /healthz/` is HTTP 200:

```powershell
powershell -NoProfile -Command 'try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/healthz/ | Select-Object StatusCode,Content } catch { $_.Exception.Message }'
```

Check candidate compose `ps`:

```powershell
docker compose -f .\docker-compose.bluegreen.proxy-candidate.example.yml ps
```

Confirm `web_blue` and `web_green` healthy:

```powershell
docker compose -f .\docker-compose.bluegreen.proxy-candidate.example.yml ps web_blue web_green
```

Confirm `bluegreen_proxy_candidate` is running on `18000`:

```powershell
docker compose -f .\docker-compose.bluegreen.proxy-candidate.example.yml ps bluegreen_proxy_candidate
```

## Cutover Readiness Checklist

- [ ] 8000 is HTTP 200.
- [ ] 18000 is HTTP 200.
- [ ] web_blue is healthy.
- [ ] web_green is healthy.
- [ ] bluegreen_proxy_candidate is running.
- [ ] deployment lock status reviewed.
- [ ] rollback target confirmed: http://127.0.0.1:8000.
- [ ] tickets route current target confirmed: http://127.0.0.1:8000.
- [ ] shopify route current target confirmed: http://127.0.0.1:8000.
- [ ] new target confirmed: http://127.0.0.1:18000.
- [ ] Cloudflare Access policies will not be changed.
- [ ] rollback owner is present.
- [ ] observation window is ready.

## Manual Cutover Steps

NOT RUN IN THIS TASK.

1. Open Cloudflare One / Zero Trust.
2. Go to Networks > Connectors > `aftersales-ticket`.
3. Go to Published application routes.
4. Edit `tickets.kidstoyloverapps.com` target to `http://127.0.0.1:18000`.
5. Edit `shopify.kidstoyloverapps.com` target to `http://127.0.0.1:18000`.
6. Do not change Access policies.
7. Do not delete routes.
8. Do not change tunnel token.

## Immediate Post-Cutover Checks

NOT RUN IN THIS TASK.

- Confirm local `18000 /healthz/` HTTP 200.
- Confirm local `8000 /healthz/` HTTP 200.
- Check tickets external route behavior.
- Check shopify external route behavior.
- Confirm Access login behavior unchanged.
- Inspect app logs.
- Observe for agreed window.

## Emergency Rollback

NOT RUN IN THIS TASK.

1. Change tickets route back to `http://127.0.0.1:8000`.
2. Change shopify route back to `http://127.0.0.1:8000`.
3. Verify external behavior returns.
4. Keep candidate running until rollback confirmed.
5. Do not rollback database.

## Cleanup After Successful Observation

NOT RUN IN THIS TASK.

- Only after observation passes.
- Do not stop current `8000` path until separately approved.
- Do not remove DB/media volumes.
- Do not stop scheduler unexpectedly.

## Go / No-Go

- Pre-cutover checklist: READY after review.
- Manual cutover: PASSED on 2026-05-19.
- Cloudflare cutover: PASSED.
- Current Cloudflare target: `http://127.0.0.1:18000`.
- Rollback target: `http://127.0.0.1:8000`.
- Candidate services must remain running: `bluegreen_proxy_candidate`,
  `web_blue`, and `web_green`.
- Production blue-green external traffic path: ACTIVE through `18000`
  candidate.
- Production apply scripts remain no-action / blocked unless separately
  approved.
- Next required step: post-cutover observation and hardening plan.

## Post-Cutover Result (2026-05-19)

- Route type: Published application routes.
- Tunnel: `aftersales-ticket`.
- `tickets.kidstoyloverapps.com` now targets `http://127.0.0.1:18000`.
- `shopify.kidstoyloverapps.com` now targets `http://127.0.0.1:18000`.
- Previous target / rollback target: `http://127.0.0.1:8000`.
- Local `18000 /healthz/`: HTTP 200 OK.
- Local `8000 /healthz/`: HTTP 200 OK.
- External tickets and shopify browser login checks: PASSED with no obvious
  errors.
- Deployment lock was acquired and released.
- Access policies, hostname routes, tunnel token, and DNS were not changed.
- No migration, collectstatic, database rollback, proxy reload, traffic
  switch script, active-color state write, or container start/stop/restart/build
  was run by this documentation task.
