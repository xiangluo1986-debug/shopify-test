# Blue-Green Media Volume Comparison

Date: 2026-05-21

This report is a read-only diagnosis of the aftersales media storage used by
the old `8000` path and the blue-green `18000` path. It does not move, copy,
delete, rename, or inspect uploaded file contents.

## Scope And Safety

- No Shopify API calls were made.
- No Gmail API calls were made.
- No Docker restart, recreate, build, up, down, migration, or collectstatic
  command was run.
- No Cloudflare setting was changed.
- No uploaded files were moved, copied, deleted, renamed, or opened.
- Docker live inspection was attempted with read-only commands only, but the
  host Docker engine was not accessible from this session.

## Compose Evidence

The active `docker-compose.yml` web service for the old `8000` path mounts:

```yaml
- media:/app/media
```

The same active compose file also mounts the same `media` volume into
`scheduler`, and declares a local named volume:

```yaml
volumes:
  media:
```

The blue-green candidate compose file
`docker-compose.bluegreen.proxy-candidate.example.yml` declares:

```yaml
name: aftersales-bluegreen-proxy-candidate
```

Its shared candidate Django service definition, inherited by both `web_blue`
and `web_green`, mounts:

```yaml
- media:/app/media
```

That candidate compose file also declares a local named volume:

```yaml
volumes:
  media:
```

Neither compose file marks the `media` volume as `external`, and neither gives
the volume an explicit global `name`. Under normal Docker Compose scoping, this
means the two compose projects use different Docker named volumes even though
both service definitions say `media:/app/media`.

## Expected Mount Sources

| Runtime path | Container/service | Expected `/app/media` source | Confirmation |
| --- | --- | --- | --- |
| Old `8000` path | `aftersales-web-1` / `web` | Likely `aftersales_media` | Compose-level inference only; live Docker inspect blocked |
| Blue-green `18000` path | `web_blue` | Likely `aftersales-bluegreen-proxy-candidate_media` | Compose-level inference only; live Docker inspect blocked |
| Blue-green `18000` path | `web_green` | Likely `aftersales-bluegreen-proxy-candidate_media` | Compose-level inference only; live Docker inspect blocked |

The old path and the blue-green path are therefore likely reading different
Docker named volumes at `/app/media`.

## Live Docker Check Result

The required read-only Docker checks were attempted:

```powershell
docker ps --format "table {{.Names}}`t{{.Status}}`t{{.Ports}}"
docker volume ls --format "{{.Name}}" | Select-String -Pattern "aftersales|media|bluegreen"
docker inspect --format '{{json .Mounts}}' aftersales-web-1 web_blue web_green
```

All Docker commands were blocked by the Windows host:

```text
Error loading config file: open C:\Users\xiang\.docker\config.json: Access is denied.
permission denied while trying to connect to the docker API at npipe:////./pipe/docker_engine
```

Because Docker API access failed, no `docker exec` file-count or `du` command
was run. The live mount source, file count, and size values below are therefore
not guessed.

| Container | `/app/media` mount source | Approximate file count | Approximate size |
| --- | --- | ---: | ---: |
| `aftersales-web-1` | Not confirmed; Docker inspect blocked | Not collected | Not collected |
| `web_blue` | Not confirmed; Docker inspect blocked | Not collected | Not collected |
| `web_green` | Not confirmed; Docker inspect blocked | Not collected | Not collected |

## Root Cause Likelihood

Root cause likelihood is high for a media storage mismatch, based on compose
configuration:

- The uploaded media URL path did not change; `/media/` remains `/media/`.
- The active web service and candidate blue-green services both mount
  `/app/media`, but through compose-local volume names.
- The active project likely uses `aftersales_media`.
- The blue-green candidate project likely uses
  `aftersales-bluegreen-proxy-candidate_media`.
- If historical uploads are in the active volume, `web_blue` and `web_green`
  can return missing media through `18000` while the old `8000` path still has
  the files.

This is not evidence of data loss. It is evidence that production traffic may
be reading from an empty or incomplete media volume.

## Read-Only Confirmation Commands For Rerun

Run these only from a Windows session with Docker Desktop access. They are
read-only and should not print environment variables or file contents:

```powershell
docker ps --format "table {{.Names}}`t{{.Status}}`t{{.Ports}}"
docker volume ls --format "{{.Name}}" | Select-String -Pattern "aftersales|media|bluegreen"
docker inspect --format '{{json .Mounts}}' aftersales-web-1 web_blue web_green
```

After the mounts are confirmed, collect counts only. Do not print filenames:

```powershell
docker exec aftersales-web-1 sh -lc 'test -d /app/media && printf "files=" && find /app/media -type f | wc -l && du -sh /app/media'
docker exec web_blue sh -lc 'test -d /app/media && printf "files=" && find /app/media -type f | wc -l && du -sh /app/media'
docker exec web_green sh -lc 'test -d /app/media && printf "files=" && find /app/media -type f | wc -l && du -sh /app/media'
```

If any container name differs, first use the read-only `docker ps` output to
select the actual web container names.

## Safest Repair Option

The safest durable repair is to make `web`, `web_blue`, and `web_green` use one
canonical shared media storage target, after the live mount comparison and a
backup are complete.

Recommended target:

- Treat the old `8000` path media volume as the likely historical source of
  uploaded files.
- Treat the blue-green candidate media volume as a possible source of new files
  uploaded while traffic used `18000`.
- Do not discard either volume.
- Do not point services at a different media store until both volumes have a
  backup and sanitized count-only inventory.
- In a later reviewed change, configure the blue-green services to mount the
  canonical media storage explicitly, for example through a reviewed external
  Docker named volume or a reviewed host bind mount.

If customer-facing media is confirmed broken through `18000` while the same
known-safe file works through `8000`, the safest immediate recovery is the
approved rollback route back to `127.0.0.1:8000`. That is a runtime/Cloudflare
change and must be handled as a separate approved operation.

## No-Data-Loss Migration Plan

This plan is for a future approved repair task only.

1. Keep both existing media volumes intact.
2. Collect live read-only mount sources, file counts, and sizes.
3. Pause risky upload-changing activity or route traffic to one reviewed path
   during the repair window.
4. Back up the active media volume and the candidate media volume before any
   merge or remount.
5. Generate a sanitized inventory that reports counts and conflicts without
   exposing customer names, ticket bodies, addresses, phone numbers, or private
   uploaded filenames.
6. Select the canonical storage target.
7. If the candidate volume contains new uploads not present in the canonical
   target, merge them with a no-overwrite strategy and a separate conflict list
   for manual review.
8. Update the blue-green compose/runtime configuration in a reviewed patch so
   `web_blue` and `web_green` mount the canonical media storage.
9. Use the deployment lock for any restart, recreate, deploy, or traffic
   change.
10. Verify representative known-safe media URLs through both `18000` and `8000`
    before considering cleanup.
11. Do not delete either original media volume until a later cleanup task has
    explicit approval and verified backups.

## Rollback Plan

- Preserve the old `8000` path and both Docker media volumes.
- If the candidate media repair fails, route traffic back to the approved
  `127.0.0.1:8000` rollback target after explicit approval.
- If a compose/runtime media mount change causes regressions, return services
  to the last reviewed runtime configuration and keep both media volumes for
  forensic comparison.
- If a future merge discovers conflicts, stop the merge and produce a manual
  review list instead of overwriting files.
- Do not run volume deletion, prune, broad cleanup, or automatic rollback of
  uploaded files.

## Current Conclusion

The repair plan is ready for ChatGPT review as a conservative plan, but real
execution must wait for a successful live Docker mount/count confirmation from
a Docker-accessible session.
