# Telegram True-Device Test Notes

This demo never accepts arbitrary shell or PowerShell commands from Telegram.
Only these fixed replies are accepted:

- `1`
- `2`
- `0`
- `SHOW_LOG`

## 1. Configure `.env`

Add these keys in the project root `.env` file:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
APPROVAL_TIMEOUT_SECONDS=3600
```

Do not commit `.env`. Do not paste the token into code, logs, screenshots, or chat.

## 2. Run the demo

From PowerShell in the project root:

```powershell
python remote_approval_runner.py --task demo --mode dry-run
```

Expected Telegram message:

```text
Task: demo
Approval ID: <unique id>
Status: dry-run completed
Result:
- checked_items: 10
- warnings: 2

Choose next step:
1 = generate review file
2 = run simulated test write only
0 = stop task
SHOW_LOG = show recent log summary
```

## 3. Test replies

- Reply `SHOW_LOG` first. The bot should return the latest 20 log lines and keep waiting.
- Reply `0`. The task should stop.
- Run the command again, then reply `1`. It should create `logs/demo_review.json`.
- Run the command again, then reply `2`. It should only run the simulated test write.

## 4. Timeout test

Set a short timeout temporarily:

```env
APPROVAL_TIMEOUT_SECONDS=10
```

Run the demo and do not reply. The task should stop automatically and Telegram should receive:

```text
approval timed out, task stopped
```

Restore the timeout after testing.

## 5. Safety checks

- Old Telegram messages sent before the approval prompt are ignored.
- Each run creates a fresh approval ID.
- Processed approval IDs are stored in `logs/approval_state.json`.
- A processed approval ID will not execute an action a second time.
- Approval records are appended to `logs/approval_history.jsonl`.
