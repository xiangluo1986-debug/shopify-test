---
name: local-dev-ops
description: Handle local Docker, PowerShell, scheduler, and validation operations.
---

# Local Dev Ops Skill

Use this skill for Docker, Windows PowerShell, scheduler, cloudflared, local validation, and Git-saving questions in this project.

## Environment

- Typical shell: Windows PowerShell.
- Project root: `C:\Users\xiang\OneDrive\桌面\aftersales`.
- Django app runs through Docker Compose.
- `docker-compose.yml` defines `db`, `web`, and `scheduler`.
- Scheduler command runs `bash /app/run_scheduler.sh`.

## Secrets

- Do not read or print `.env`.
- Do not print cloudflared tunnel tokens.
- Do not print Shopify tokens, OpenAI keys, database passwords, or Django `SECRET_KEY`.

## Safe Read-Only Checks

These are generally safe, but still explain why before running:

```powershell
git status
git diff --stat
docker ps
docker compose ps
docker compose logs --tail=100 web
docker compose logs --tail=100 scheduler
docker compose exec -T web python manage.py check
docker compose exec -T web python manage.py showmigrations
```

## Commands Requiring Explicit Confirmation

```powershell
docker compose exec -T web python manage.py migrate
docker compose up -d --build
docker compose restart web
```

Explain whether the command modifies database, containers, files, or only checks code.

## Forbidden Commands

Never run unless the user explicitly requests after risk explanation:

```powershell
docker compose down -v
docker volume rm
docker system prune
python manage.py flush
```

Also avoid commands containing:

- `reset`
- `drop`
- `truncate`
- `clean`
- forced deletes of database files or Docker volumes

## Docker Desktop Problems

If Docker says:

```text
open //./pipe/docker_engine: Access is denied
```

Tell the user:

1. Close Codex App.
2. Reopen Codex App with Run as administrator.
3. Confirm Docker Desktop engine is running.
4. Retry the Docker command.

If Docker says a service is not running, check:

```powershell
docker compose ps
```

## Scheduler Notes

- `backend/run_scheduler.sh` must use LF line endings.
- CRLF can cause:

```text
$'\r': command not found
syntax error near unexpected token `$'{\r''
```

- Scheduler should do incremental orders sync, not large 60-day scans every 30 minutes.
- Product sync should be daily or skip if already successful today.

## cloudflared Notes

- `quick start.txt` contains a cloudflared startup pattern.
- Do not copy, print, or store actual tunnel tokens.
- If documenting cloudflared, use placeholders such as `<cloudflared-token>`.

## Git Notes

- Check `git status --short` before saving a version.
- Do not stage logs or unrelated files.
- Do not commit secrets, DB files, or generated debug dumps.
- If commit fails with `.git/index.lock Permission denied`, report it. Do not delete lock files.
- Avoid `git reset`, `git checkout`, and `git revert` unless explicitly requested.
