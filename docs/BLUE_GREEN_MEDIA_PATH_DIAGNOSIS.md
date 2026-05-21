# Blue-Green Media Path Diagnosis

## Scope

This is a read-only diagnosis of uploaded image/video/file path behavior after
the controlled `--noreload` blue-green apply.

No runtime behavior was changed. No Docker restart, recreate, build, deploy,
migration, collectstatic, Cloudflare change, proxy config change, Shopify API
call, Gmail API call, email send, uploaded file move, uploaded file copy, or
uploaded file deletion was performed.

## Current Traffic Context

Current production traffic path reported for this task:

```text
Cloudflare Tunnel
  -> 127.0.0.1:18000
  -> bluegreen_proxy_candidate
  -> web_blue / web_green
```

Rollback target:

```text
127.0.0.1:8000
```

## Django Media Configuration

Repo inspection shows the Django media URL path itself did not change:

```text
MEDIA_URL = "/media/"
MEDIA_ROOT = os.getenv("MEDIA_ROOT", str(BASE_DIR / "media"))
```

`backend/config/urls.py` explicitly serves `/media/<path>` through Django:

```text
re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT})
```

Discovered upload paths:

```text
TicketAttachment.file:
  ticket_uploads/%Y/%m/%d/

ShenzhenSettlementPayment.payment_proof:
  settlement_payment_proofs/
```

No separate `/uploads/` URL route was found in the inspected Django URL
configuration. Uploaded ticket files and settlement payment proof files are
therefore expected under `MEDIA_ROOT`, normally `/app/media` inside the
containers.

## Compose Storage Findings

`docker-compose.yml` mounts the active `web` service media storage as:

```text
media:/app/media
```

The active `scheduler` service also mounts:

```text
media:/app/media
```

The active compose file declares a local named volume:

```text
volumes:
  media:
```

`docker-compose.bluegreen.proxy-candidate.example.yml` has a separate compose
project name:

```text
name: aftersales-bluegreen-proxy-candidate
```

The shared candidate web definition used by `web_blue` and `web_green` mounts:

```text
media:/app/media
```

That candidate compose file also declares a local named volume:

```text
volumes:
  media:
```

Because neither file marks `media` as `external`, Docker Compose normally scopes
the named volume by compose project. That means the likely effective volumes
are different:

```text
Active 8000 path:
  aftersales_media

Blue-green 18000 candidate path:
  aftersales-bluegreen-proxy-candidate_media
```

This means:

- `web` and `scheduler` likely share the active compose media volume.
- `web_blue` and `web_green` likely share the candidate compose media volume.
- The old `web` path and the blue-green candidate path likely do not share the
  same media volume by default.

Recreating `web_blue` and `web_green` should not by itself delete a Docker named
volume. The risk is not proven data loss. The likely risk is that production
traffic moved to a different, empty, or incomplete media volume.

## Proxy Findings

`nginx/bluegreen.proxy-candidate.example.conf` defines upstreams for
`web_blue:8000` and `web_green:8000`, then proxies all normal paths through:

```text
location / {
    proxy_pass http://bluegreen_active_candidate;
}
```

No special `location /media/` or `location /uploads/` block was found in the
candidate nginx config. Therefore `/media/...` requests are passed through the
proxy to Django rather than being served directly by nginx from a shared media
directory.

No media/video-specific proxy settings were found in the candidate config, such
as a direct media alias, explicit range handling, media cache policy, or large
file tuning. The normal path uses `proxy_read_timeout 60s`. For large uploaded
videos, the future hardened design should avoid relying on Django `runserver`
to stream production media.

## Read-Only Runtime Checks Attempted

Docker live inspection could not be completed from this session because Docker
access is blocked by local Windows/Docker permissions:

```text
docker ps
docker volume ls
```

Both failed with Docker config / API pipe access denied errors. Therefore this
diagnosis could not directly compare live mounts or file counts inside
`web`, `web_blue`, and `web_green`.

Local host directory metadata, without reading uploaded file contents:

```text
media                missing
uploads              missing
backend\media        exists, 0 files
backend\uploads      missing
static               missing
backend\static       missing
backend\staticfiles  exists, 127 files
```

This is consistent with uploaded files being stored in Docker named volumes
rather than in the host `backend\media` directory.

Small HTTP probes were run only against health and nonexistent media paths:

```text
http://127.0.0.1:18000/healthz/  -> 200
http://127.0.0.1:8000/healthz/   -> 200

http://127.0.0.1:18000/media/ticket_uploads/_codex_nonexistent_probe.txt
  -> 404
http://127.0.0.1:8000/media/ticket_uploads/_codex_nonexistent_probe.txt
  -> 404

http://127.0.0.1:18000/media/settlement_payment_proofs/_codex_nonexistent_probe.txt
  -> 404
http://127.0.0.1:8000/media/settlement_payment_proofs/_codex_nonexistent_probe.txt
  -> 404
```

The 404 checks are expected for nonexistent paths. They only confirm that the
local HTTP paths are reachable and that `/media/...` is being handled as a web
route. They do not prove whether a real uploaded file exists in either volume.

## Diagnosis

Media URL paths do not appear to have changed in Django. The configured public
path remains `/media/...`.

The suspected root cause is storage backing, not URL construction:

```text
Cloudflare now reaches 18000 -> bluegreen_proxy_candidate -> web_blue/web_green.
web_blue/web_green likely mount a different Compose-scoped Docker named volume
at /app/media than the old 8000 web service uses.
```

If existing uploaded files were originally stored in the active `web` media
volume, then the blue-green candidate services would return 404 for those files
because their `/app/media` points at a different volume.

This does not prove that uploaded files were deleted. It points to the current
production path reading from the wrong or incomplete storage location.

## Safest Repair Plan

1. Preserve evidence and do not perform cleanup.
2. From a user report or Django admin record, pick one small representative
   uploaded media URL. Avoid exposing customer names, ticket bodies, addresses,
   phone numbers, or private filenames in shared notes.
3. From an elevated/admin shell with Docker access, inspect only mounts and
   counts, not environment variables:

```powershell
docker ps
docker volume ls
docker container inspect web_blue --format "{{json .Mounts}}"
docker container inspect web_green --format "{{json .Mounts}}"
docker container inspect aftersales-web-1 --format "{{json .Mounts}}"
```

4. Compare the representative file through both paths:

```powershell
Invoke-WebRequest -Method Head -Uri "http://127.0.0.1:18000/media/<known-safe-relative-path>" -Headers @{Host="tickets.kidstoyloverapps.com"} -UseBasicParsing
Invoke-WebRequest -Method Head -Uri "http://127.0.0.1:8000/media/<known-safe-relative-path>" -Headers @{Host="tickets.kidstoyloverapps.com"} -UseBasicParsing
```

5. If `8000` can serve the file but `18000` cannot, treat the issue as a
   confirmed blue-green media volume split.
6. Choose one canonical shared media storage target before any runtime change.
   The likely fix is to make the blue-green services mount the same existing
   media storage as the old `web` path, either through an explicitly named
   external Docker volume or a reviewed host bind mount.
7. Before any copy or merge, back up both media volumes and produce sanitized
   file count/hash summaries. Do not print private filenames.
8. If any new uploads were created while traffic used `18000`, reconcile the
   candidate volume back into the canonical media storage before decommissioning
   or remounting it.
9. Apply any compose/proxy/storage change only in a separate approved runtime
   task under the deployment lock.
10. After repair, verify a small representative media URL through both
    `18000` and `8000`, then spot-check ticket and settlement upload views.

## Rollback And Recovery Plan

If customer-facing media is confirmed broken through `18000` while the same
files still work through `8000`, the safest immediate recovery is to use the
approved rollback route back to `127.0.0.1:8000` after explicit human approval.
That avoids copying or moving uploaded files during the incident.

After rollback:

- Keep `bluegreen_proxy_candidate`, `web_blue`, and `web_green` available for
  investigation unless an approved runtime task says otherwise.
- Preserve both media volumes.
- Inspect and back up both volumes before any merge.
- Treat the active `web` media volume as the likely source of historical
  uploads unless live mount inspection proves otherwise.
- Treat the candidate media volume as a possible source of new uploads created
  after the Cloudflare cutover.

## Commands That Must Not Be Run For This Diagnosis

Do not run:

```powershell
docker compose down -v
docker volume rm
docker system prune
python manage.py flush
docker compose up -d --build
docker compose restart web
docker compose restart web_blue
docker compose restart web_green
docker compose restart bluegreen_proxy_candidate
python manage.py collectstatic
python manage.py migrate
```

Also do not delete, move, rename, overwrite, or copy uploaded files until a
separate repair task has explicit approval, a backup plan, and a verified
source/destination decision.

## Conclusion

The uploaded media path repair plan is ready for ChatGPT review.

The current best diagnosis is:

```text
URL paths did not change.
Media storage likely split because the blue-green compose project uses a
separate Compose-scoped named media volume.
Uploaded files are not assumed lost.
The 18000 production path is likely reading from the wrong or incomplete
/app/media volume.
```
