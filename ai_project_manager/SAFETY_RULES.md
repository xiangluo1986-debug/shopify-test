# Project Safety Rules

- Do not call Shopify APIs.
- Do not write Shopify data.
- Do not call `translationsRegister`.
- Do not call Gmail APIs.
- Do not send emails.
- Do not read, print, copy, write, or expose secrets, tokens, API keys, credentials, database passwords, Django `SECRET_KEY`, cloudflared tokens, or private environment values.
- Do not edit `.env`, `.env.*`, credential files, token files, or secret-bearing config files.
- Do not edit `.codex/config.toml`.
- Do not edit `logs/` except runner-created `logs/codex_runs/` output during an approved runner execution.
- Do not commit generated logs.
- Do not stage files.
- Do not commit.
- Do not push.
- Do not run destructive git commands, including `git reset`, `git restore`, `git checkout`, `git clean`, `git rebase`, or lock-file deletion.
- Do not run destructive database, Docker, or cleanup commands, including `flush`, `drop`, `truncate`, `prune`, or `docker compose down -v`.
- Keep changes minimal, scoped, and limited to the task's allowed files.
- If unrelated local changes are present, leave them untouched.
