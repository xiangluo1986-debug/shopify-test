# Codex Task Template

## Goal

Describe the exact outcome for this task.

## Files allowed to edit

- `path/to/file`

## Files forbidden to edit

- `.env`
- `.env.*`
- `.codex/config.toml`
- `logs/` except runner-created `logs/codex_runs/`
- `remote_approval/`
- `backend/`

## Safety rules

- Do not read, print, copy, or store secrets, tokens, credentials, API keys, or private environment values.
- Do not call Shopify APIs, write Shopify data, or call `translationsRegister`.
- Do not call Gmail APIs or send emails.
- Do not stage, commit, push, reset, restore, checkout, clean, rebase, or delete lock files.
- Keep edits minimal and limited to the allowed files.

## Implementation

List the concrete changes Codex should make.

## Validation

List safe validation commands Codex should run.

## Final response requirements

- List changed files.
- List validation commands and results.
- Confirm staged files are empty.
- Confirm no commit or push was run.
- Mention any files that were intentionally not touched.
